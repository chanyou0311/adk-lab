"""agent composition のクロス評価ランナー。

同一のタスクセットを全バリアント (単一エージェント / multi-agent 構成) に対して実行し、
正答率 (Wilson 95% CI)・トークン・レイテンシ・ツールルーティング精度・拒否率を決定的に採点して
比較する。採点は tasks.score_record、集計/レポートは report.py に置き、オフライン再採点
(rescore.py) と完全に共有する。

トークンと tool 呼び出しは Plugin (before_model_callback / after_model_callback /
before_tool_callback) で収集する。これは root エージェントだけでなく AgentTool 配下の sub-agent の
LLM 呼び出し・tool 呼び出しも拾う (AgentTool は plugin を子 Runner に伝播する) ため、multi-agent
構成でもトークンと trajectory を漏れなく数えられる。ADK 2.4.0 では AgentTool の sub-agent
イベントは親の event ストリームに出ないので、この Plugin 方式が唯一の横断計測手段。

Gemini 3 (thinking) 向けに、thoughts / tool-use-prompt / cached の各トークンと、
function_call part の thought_signature 欠落数 (signature_missing_count) も計測する
(multi-agent 構成で thought signature が伝播せず 400 になる回帰を検知するため)。

ジョブは (variant, env, task, run) の直交。収集セル計画 (_CELL_ENVS) は single_flat を 3 環境、
他 4 バリアントを CLEAN/CONFUSABLE の 2 環境で回す計 11 セル。record に variant/env/cell/
tool_order_seed を残し、集計は cell (variant×env) 単位で行う。

Usage:
    # V-1 smoke (11 セル × 代表 3 タスク × 1 run)
    GOOGLE_CLOUD_PROJECT=<proj> uv run python eval/run_eval.py --smoke --tag _smoke
    # 本番 (11 セル × 16 タスク × runs=8)
    GOOGLE_CLOUD_PROJECT=<proj> uv run python eval/run_eval.py --runs 8 --tag _main
    # 絞り込み (バリアント/環境/タスク)
    uv run python eval/run_eval.py --variants single_flat --envs clean --tasks A1 C1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google.adk.apps import App
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import InMemoryRunner
from google.genai import types

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
sys.path.insert(0, str(EVAL_DIR))

from report import aggregate, render_markdown  # noqa: E402
from tasks import TASKS, score_record  # noqa: E402

from lab.environments import CLEAN, CONFUSABLE, DISTINCT, ENVIRONMENTS  # noqa: E402
from lab.model import MODEL  # noqa: E402
from lab.variants import VARIANTS  # noqa: E402

load_dotenv()

USER_ID = "eval"
APP_NAME = "adk_agent_composition_lab"

# 収集セル計画: single_flat は 3 環境で劣化曲線を引き、他 4 バリアントは CLEAN と CONFUSABLE の
# 両端で比較する (計 11 セル)。DISTINCT の中間点は single_flat のみで測る。
_CELL_ENVS: dict[str, list[str]] = {
    "single_flat": [CLEAN, DISTINCT, CONFUSABLE],
    "single_skills": [CLEAN, CONFUSABLE],
    "multi_agenttool": [CLEAN, CONFUSABLE],
    "multi_transfer": [CLEAN, CONFUSABLE],
    "workflow_graph": [CLEAN, CONFUSABLE],
}
# smoke (V-1) 用の代表タスク: A (単純 lookup) / C (confusable 罠) / E (捏造) を 1 本ずつ。
_SMOKE_TASKS = ["A1", "C1", "E1"]
_MAX_ATTEMPTS = 3
_BACKOFF = [5, 15]  # seconds before retry attempt 2 / 3 (最終試行後は sleep しない)
# 一時的エラーの部分一致マーカー (照合は小文字化して行う)。
_TRANSIENT_MARKERS = (
    "429", "500", "503", "resource_exhausted", "unavailable", "internal",
    "deadline", "timeout", "temporarily", "connection", "servererror",
    "serviceunavailable",
)
# thought signature 起因の 400 を切り分けるマーカー (照合は小文字化して行う。両表記に対応)。
_SIGNATURE_MARKERS = ("thought_signature", "thought signature")


class MetricsPlugin(BasePlugin):
    """1 ジョブ (variant×task×run) の LLM トークンと tool 呼び出しを横断収集する Plugin。

    Gemini 3 (thinking) 向けに、標準トークンに加えて thoughts / tool-use-prompt / cached の
    各トークンと、リクエストに載る function_call part の thought_signature 欠落数を計測する。
    """

    def __init__(self) -> None:
        super().__init__(name="metrics")
        self.tool_calls: list[dict] = []
        self.tool_names: list[str] = []
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.candidate_tokens = 0
        # Gemini 3 (thinking) 向けの内訳トークン。usage_metadata から独立集計する。
        self.thoughts_tokens = 0
        self.tool_use_prompt_tokens = 0
        self.cached_tokens = 0
        self.llm_calls = 0
        # signature 監査。各リクエストで欠落した function_call part 数の「リクエスト単位の最大」
        # (signature_missing_max) と「一度でも欠落したか」(signature_ever_missing) を持つ。全履歴を
        # 毎リクエスト再走査して累積すると超線形に膨らむため、per-request の値を集約する。
        self.signature_missing_max = 0
        self.signature_ever_missing = False

    async def before_model_callback(self, *, callback_context, llm_request) -> None:
        """送信前 contents を走査し、model ロールの function_call part の thought_signature 欠落を数える。

        Gemini 3 は multi-turn の tool 利用で function_call part の thought_signature を次リクエストへ
        echo する必要がある。欠落すると 400 になりうるため監査する。累積ではなく **このリクエストの
        欠落数** を取り、per-job の最大と ever フラグに集約する (全履歴を毎回数える二重計上を回避)。
        """
        missing = 0
        for content in getattr(llm_request, "contents", None) or []:
            if getattr(content, "role", None) != "model":
                continue
            for part in getattr(content, "parts", None) or []:
                if getattr(part, "function_call", None) is None:
                    continue
                if getattr(part, "thought_signature", None) is None:
                    missing += 1
        if missing > self.signature_missing_max:
            self.signature_missing_max = missing
        if missing > 0:
            self.signature_ever_missing = True
        return None

    async def before_tool_callback(self, *, tool, tool_args, tool_context) -> dict | None:
        self.tool_names.append(tool.name)
        # args は概要のみ (SQL/クエリ文字列などは長いので先頭を切る)。
        summary = {k: (str(v)[:160]) for k, v in (tool_args or {}).items()}
        self.tool_calls.append({"name": tool.name, "args": summary})
        return None

    async def after_model_callback(self, *, callback_context, llm_response) -> None:
        # streaming の partial レスポンスは最終レスポンスと usage が二重に来るため、partial は
        # 集計しない (トークンの二重計上を防ぐ)。
        if getattr(llm_response, "partial", False):
            return None
        usage = getattr(llm_response, "usage_metadata", None)
        if usage is not None:
            self.llm_calls += 1
            self.total_tokens += getattr(usage, "total_token_count", 0) or 0
            self.prompt_tokens += getattr(usage, "prompt_token_count", 0) or 0
            self.candidate_tokens += getattr(usage, "candidates_token_count", 0) or 0
            # 内訳トークンは turn によって None のことがあるため `or 0` で正規化する。
            self.thoughts_tokens += getattr(usage, "thoughts_token_count", 0) or 0
            self.tool_use_prompt_tokens += getattr(usage, "tool_use_prompt_token_count", 0) or 0
            self.cached_tokens += getattr(usage, "cached_content_token_count", 0) or 0
        return None


def _is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _TRANSIENT_MARKERS)


def _is_signature_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _SIGNATURE_MARKERS)


def _zero_metrics() -> dict:
    """メトリクスの空形。_run_once の初期値と error fallback で共有し、スキーマを 1 箇所にする。"""
    return {
        "final": "",
        "turns": [],
        "latency": 0.0,
        "tool_calls": [],
        "tool_names": [],
        "n_tool_calls": 0,
        "llm_calls": 0,
        "tokens": 0,
        "prompt_tokens": 0,
        "candidate_tokens": 0,
        "thoughts_tokens": 0,
        "tool_use_prompt_tokens": 0,
        "cached_tokens": 0,
        "signature_missing_max": 0,
        "signature_ever_missing": False,
        "signature_400": False,
    }


async def _run_once(variant: str, env: str, prompts: list[str], seed: int) -> dict:
    """1 ジョブを実行する。マルチターンは同一 session を turn 間で共有する。

    variant を env でツール環境化し、seed で提示順を run 毎シャッフルして構築する。session を turn
    ごとに作り直さないのが要点 — turn 2 は turn 1 の結果を参照するので、session を使い回すことで
    AgentTool の文脈喪失 (sub-agent が前 turn の文脈を持たない) を露出させる。全 turn の最終応答を
    turns に残し、採点は最終 turn (final) で行う。tool_names は全 turn を通した順序付き trajectory。
    """
    root = VARIANTS[variant](env, seed)
    plugin = MetricsPlugin()
    app = App(name=APP_NAME, root_agent=root, plugins=[plugin])
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(
        app_name=runner.app_name, user_id=USER_ID
    )

    turns: list[str] = []
    start = time.perf_counter()
    try:
        for prompt in prompts:
            message = types.UserContent(prompt)
            final = ""
            async for event in runner.run_async(
                user_id=USER_ID, session_id=session.id, new_message=message
            ):
                content = getattr(event, "content", None)
                parts = content.parts if content is not None else None
                # thought part (推論の途中出力) は最終回答に含めない (採点対象は最終応答テキスト)。
                text = "".join(
                    p.text for p in (parts or [])
                    if getattr(p, "text", None) and not getattr(p, "thought", False)
                )
                if event.is_final_response() and text:
                    final = text
            turns.append(final)
    finally:
        latency = time.perf_counter() - start
        await runner.close()

    return {
        **_zero_metrics(),
        "final": turns[-1] if turns else "",
        "turns": turns,
        "latency": latency,
        "tool_calls": plugin.tool_calls,
        "tool_names": plugin.tool_names,
        "n_tool_calls": len(plugin.tool_names),
        "llm_calls": plugin.llm_calls,
        "tokens": plugin.total_tokens,
        "prompt_tokens": plugin.prompt_tokens,
        "candidate_tokens": plugin.candidate_tokens,
        "thoughts_tokens": plugin.thoughts_tokens,
        "tool_use_prompt_tokens": plugin.tool_use_prompt_tokens,
        "cached_tokens": plugin.cached_tokens,
        "signature_missing_max": plugin.signature_missing_max,
        "signature_ever_missing": plugin.signature_ever_missing,
    }


async def _eval_one(variant: str, env: str, task, run_index: int, sem: asyncio.Semaphore) -> dict:
    async with sem:
        metrics: dict = {}
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                metrics = await _run_once(variant, env, task.prompts, run_index)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt < _MAX_ATTEMPTS and _is_transient(exc):
                    await asyncio.sleep(_BACKOFF[attempt - 1])
                    continue
                # thought signature 起因の 400 は別フラグで残す (multi-agent の伝播回帰を切り分ける)。
                metrics = {
                    **_zero_metrics(),
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                    "signature_400": _is_signature_error(exc),
                }
                break

        metrics.update(
            score_record(task, metrics["final"], metrics["tool_names"], metrics.get("error"),
                         tool_calls=metrics.get("tool_calls"))
        )
        # tool_order_seed = run_index。提示順 shuffle (environments) の seed であり、raw record に
        # 残すことでどの提示順で得た結果かを後から再現できる。cell は (variant,env) の集計キー。
        metrics.update({"variant": variant, "env": env, "cell": f"{variant}@{env}",
                        "task_id": task.id, "category": task.category,
                        "run_index": run_index, "tool_order_seed": run_index})
        return metrics


def _planned_cells(variant_filter: list[str] | None, env_filter: list[str] | None) -> list[tuple[str, str]]:
    """収集セル (variant, env) の一覧を計画から生成し、CLI フィルタで絞る。"""
    cells = [(v, e) for v, envs in _CELL_ENVS.items() for e in envs]
    if variant_filter:
        cells = [(v, e) for (v, e) in cells if v in variant_filter]
    if env_filter:
        cells = [(v, e) for (v, e) in cells if e in env_filter]
    return cells


# --------------------------------------------------------------------------- #
# チェックポイント (kill 耐性)
# --------------------------------------------------------------------------- #
# 長時間 run が途中で kill されると、末尾一括書き込みでは課金済みの全ジョブが失われる。
# ジョブ完了ごとに 1 行 JSON を追記し、--resume で完了済み (cell, task_id, run_index) を
# スキップして続きから再開する。error record も「完了」扱い (勝手に再実行しない方針)。
# checkpoint は scratch であり results の append-only 規約の対象外 (.gitignore 済み)。


def _ckpt_key(rec: dict) -> tuple[str, str, int]:
    return (rec["cell"], rec["task_id"], rec["run_index"])


def _append_checkpoint(path, rec: dict) -> None:
    """1 record を 1 行 JSON で追記する (書き込みごとに close = flush)。"""
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _load_checkpoint(path) -> list[dict]:
    """checkpoint を読み込む。kill による部分書き込みで壊れた行は捨てる。"""
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _pending_specs(cells: list[tuple[str, str]], tasks: list, runs: int,
                   done_keys: set) -> list[tuple]:
    """未完了ジョブ (variant, env, task, run_index) を列挙する (done_keys の (cell,task,run) をスキップ)。"""
    return [(v, e, t, run_idx)
            for (v, e) in cells for t in tasks for run_idx in range(runs)
            if (f"{v}@{e}", t.id, run_idx) not in done_keys]


async def _main_async(args) -> None:
    cells = _planned_cells(args.variants, args.envs)
    task_filter = _SMOKE_TASKS if args.smoke else args.tasks
    runs = 1 if args.smoke else args.runs
    tasks = [t for t in TASKS if not task_filter or t.id in task_filter]
    task_ids = [t.id for t in tasks]
    categories = sorted({t.category for t in tasks})
    cell_labels = [f"{v}@{e}" for (v, e) in cells]
    sem = asyncio.Semaphore(args.concurrency)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = args.tag or ("_smoke" if args.smoke else "")
    ckpt_path = RESULTS_DIR / f"results{suffix}.checkpoint.jsonl"
    prior = _load_checkpoint(ckpt_path) if args.resume else []
    if not args.resume:
        # 新規実行: 過去の中断で残った checkpoint を破棄する (追記で新旧が混ざるのを防ぐ)。
        ckpt_path.unlink(missing_ok=True)
    done_keys = {_ckpt_key(r) for r in prior}

    jobs = [_eval_one(v, e, t, run_idx, sem)
            for (v, e, t, run_idx) in _pending_specs(cells, tasks, runs, done_keys)]
    total = len(jobs)
    mode = "SMOKE " if args.smoke else ""
    resumed = f", resumed={len(prior)} from {ckpt_path.name}" if prior else ""
    print(f"running {mode}{total} jobs ({len(cells)} cells={cell_labels}, tasks={task_ids}, "
          f"runs={runs}, concurrency={args.concurrency}, model={MODEL}{resumed})", flush=True)
    if total == 0 and not prior:
        print("no jobs to run — cells が空 (variant/env フィルタが全除外) か、tasks フィルタが全除外。")
        return

    records: list[dict] = list(prior)
    done = 0
    for coro in asyncio.as_completed(jobs):
        rec = await coro
        records.append(rec)
        _append_checkpoint(ckpt_path, rec)
        done += 1
        if done % 5 == 0 or done == total:
            print(f"  [{done}/{total}]", flush=True)

    # 集計は cell 単位 (variant×env)。aggregate に group_field="cell" を渡し、詐称コピーを作らない。
    summary = aggregate(records, cell_labels, categories, group_field="cell")
    (RESULTS_DIR / f"results{suffix}.json").write_text(
        json.dumps(
            {"model": MODEL, "runs": runs, "cells": cell_labels, "task_ids": task_ids,
             "summary": summary, "records": records},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    md = render_markdown(summary, cell_labels, task_ids, categories, runs, MODEL)
    (RESULTS_DIR / f"RESULTS{suffix}.md").write_text(md, encoding="utf-8")
    ckpt_path.unlink(missing_ok=True)  # 正常完了: 最終結果に合流済みなので checkpoint は不要
    print("\n" + md)

    n_err = sum(1 for r in records if r.get("error"))
    if n_err:
        print(f"⚠ {n_err}/{total} records had errors (集計から除外済み)。results{suffix}.json を参照。")


def main() -> None:
    p = argparse.ArgumentParser(description="Cross-variant×env agent-composition eval.")
    p.add_argument("--variants", nargs="*", choices=sorted(VARIANTS))
    p.add_argument("--envs", nargs="*", choices=list(ENVIRONMENTS))
    p.add_argument("--tasks", nargs="*")
    p.add_argument("--runs", type=int, default=8)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--tag", default=None, help="出力ファイル名のサフィックス (例: _main)")
    p.add_argument("--smoke", action="store_true",
                   help="V-1 smoke: 11 セル × 代表 3 タスク (A1/C1/E1) × 1 run に絞る")
    p.add_argument("--resume", action="store_true",
                   help="checkpoint (results_<tag>.checkpoint.jsonl) の完了済みジョブを"
                        "スキップして再開 (error record も完了扱い = 自動再実行しない)")
    asyncio.run(_main_async(p.parse_args()))


if __name__ == "__main__":
    main()
