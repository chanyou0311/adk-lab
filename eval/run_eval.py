"""知識配置バリアントのクロス評価ランナー。

同一のタスクセットを全バリアントに対して実行し、正答率 (Wilson 95% CI)・トークン・レイテンシ・
ツールルーティング精度・拒否率を決定的に採点して比較する。

トークンと tool 呼び出しは Plugin (after_model_callback / before_tool_callback) で収集する。
これは root エージェントだけでなく AgentTool 配下の sub-agent の LLM 呼び出し・tool 呼び出しも
拾う (AgentTool は plugin を子 Runner に伝播する) ため、subagents / skills バリアントでも
トークンと trajectory を漏れなく数えられる。ADK 2.4.0 では AgentTool の sub-agent イベントは
親の event ストリームに出ないので、この Plugin 方式が唯一の横断計測手段。

Usage:
    GOOGLE_CLOUD_PROJECT=<proj> uv run python eval/run_eval.py \
        --variants fat_closed thin_none skills --tasks A1 A3 D1 E2 --runs 1 --tag _smoke
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.adk.apps import App
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import InMemoryRunner
from google.genai import types

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
sys.path.insert(0, str(EVAL_DIR))

from tasks import TASKS, called_families, is_refused  # noqa: E402

from lab.model import MODEL  # noqa: E402
from lab.variants import VARIANTS  # noqa: E402

load_dotenv()

USER_ID = "eval"
APP_NAME = "adk_thin_agent_lab"
_MAX_ATTEMPTS = 3
_BACKOFF = [5, 15, 45]  # seconds before retry attempt 2 / 3
_TRANSIENT_MARKERS = (
    "429", "500", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL",
    "DEADLINE", "deadline", "timeout", "Timeout", "temporarily",
    "connection", "Connection", "ServerError", "ServiceUnavailable",
)


class MetricsPlugin(BasePlugin):
    """1 ジョブ (variant×task×run) の LLM トークンと tool 呼び出しを横断収集する Plugin。"""

    def __init__(self) -> None:
        super().__init__(name="metrics")
        self.tool_calls: list[dict] = []
        self.tool_names: list[str] = []
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.candidate_tokens = 0
        self.llm_calls = 0

    async def before_tool_callback(self, *, tool, tool_args, tool_context) -> dict | None:
        self.tool_names.append(tool.name)
        # args は概要のみ (SQL/クエリ文字列などは長いので先頭を切る)。
        summary = {k: (str(v)[:160]) for k, v in (tool_args or {}).items()}
        self.tool_calls.append({"name": tool.name, "args": summary})
        return None

    async def after_model_callback(self, *, callback_context, llm_response) -> None:
        usage = getattr(llm_response, "usage_metadata", None)
        if usage is not None:
            self.llm_calls += 1
            self.total_tokens += getattr(usage, "total_token_count", 0) or 0
            self.prompt_tokens += getattr(usage, "prompt_token_count", 0) or 0
            self.candidate_tokens += getattr(usage, "candidates_token_count", 0) or 0
        return None


def _is_transient(exc: Exception) -> bool:
    msg = str(exc)
    return any(m in msg for m in _TRANSIENT_MARKERS)


async def _run_once(variant: str, prompt: str) -> dict:
    root = VARIANTS[variant]()
    plugin = MetricsPlugin()
    app = App(name=APP_NAME, root_agent=root, plugins=[plugin])
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(
        app_name=runner.app_name, user_id=USER_ID
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    final = ""
    start = time.perf_counter()
    try:
        async for event in runner.run_async(
            user_id=USER_ID, session_id=session.id, new_message=message
        ):
            content = getattr(event, "content", None)
            parts = content.parts if content is not None else None
            text = "".join(
                p.text or "" for p in (parts or []) if getattr(p, "text", None)
            )
            if event.is_final_response() and text:
                final = text
    finally:
        latency = time.perf_counter() - start
        await runner.close()

    return {
        "final": final,
        "latency": latency,
        "tool_calls": plugin.tool_calls,
        "tool_names": plugin.tool_names,
        "n_tool_calls": len(plugin.tool_names),
        "llm_calls": plugin.llm_calls,
        "tokens": plugin.total_tokens,
        "prompt_tokens": plugin.prompt_tokens,
        "candidate_tokens": plugin.candidate_tokens,
    }


async def _eval_one(variant: str, task, sem: asyncio.Semaphore) -> dict:
    async with sem:
        metrics: dict = {}
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                metrics = await _run_once(variant, task.prompt)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt < _MAX_ATTEMPTS and _is_transient(exc):
                    await asyncio.sleep(_BACKOFF[attempt - 1])
                    continue
                metrics = {
                    "final": "", "latency": 0.0, "tool_calls": [], "tool_names": [],
                    "n_tool_calls": 0, "llm_calls": 0, "tokens": 0, "prompt_tokens": 0,
                    "candidate_tokens": 0, "error": f"{type(exc).__name__}: {exc}"[:300],
                }
                break

        from tasks import GT  # 遅延 import (fixtures 依存の GT)
        error = metrics.get("error")
        refused = is_refused(metrics["final"])
        passed = False
        if not error:
            try:
                passed = bool(task.check(metrics["final"], metrics["tool_names"], GT, refused))
            except Exception as exc:  # noqa: BLE001 - 採点例外は fail 扱い
                metrics["score_error"] = f"{type(exc).__name__}: {exc}"[:200]
        fams = called_families(metrics["tool_names"])
        route_ok = None
        if task.route_scored and not error:
            route_ok = fams == task.expected_families
        metrics.update(
            {
                "variant": variant,
                "task_id": task.id,
                "category": task.category,
                "passed": passed,
                "refused": refused,
                "families": sorted(fams),
                "expected_families": sorted(task.expected_families),
                "route_ok": route_ok,
            }
        )
        return metrics


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _mean(xs: list[float]) -> float:
    return statistics.mean(xs) if xs else 0.0


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _aggregate(records: list[dict], variants: list[str], categories: list[str]) -> dict:
    summary: dict[str, Any] = {}
    for v in variants:
        rows = [r for r in records if r["variant"] == v]
        ok_rows = [r for r in rows if not r.get("error")]
        k = sum(1 for r in ok_rows if r["passed"])
        lo, hi = _wilson(k, len(ok_rows))
        route_rows = [r for r in ok_rows if r["route_ok"] is not None]
        summary[v] = {
            "n": len(rows),
            "n_ok": len(ok_rows),
            "n_error": len(rows) - len(ok_rows),
            "pass_rate": _mean([1.0 if r["passed"] else 0.0 for r in ok_rows]),
            "pass_ci": [lo, hi],
            "route_ok_rate": _mean([1.0 if r["route_ok"] else 0.0 for r in route_rows]),
            "refusal_rate": _mean([1.0 if r["refused"] else 0.0 for r in ok_rows]),
            "tokens": _mean([r["tokens"] for r in ok_rows]),
            "latency": _mean([r["latency"] for r in ok_rows]),
            "tool_calls": _mean([r["n_tool_calls"] for r in ok_rows]),
            "llm_calls": _mean([r["llm_calls"] for r in ok_rows]),
            "by_category": {
                c: _mean([1.0 if r["passed"] else 0.0
                          for r in ok_rows if r["category"] == c])
                for c in categories
            },
            "by_task": {},
        }
        for r in ok_rows:
            summary[v]["by_task"].setdefault(r["task_id"], []).append(1.0 if r["passed"] else 0.0)
        summary[v]["by_task"] = {t: _mean(xs) for t, xs in summary[v]["by_task"].items()}
    return summary


def _render_markdown(summary: dict, variants: list[str], task_ids: list[str],
                     categories: list[str], runs: int) -> str:
    lines = [
        "# 知識配置バリアント評価 — 結果",
        "",
        f"- model: `{MODEL}`  ·  runs/(variant,task): {runs}  ·  variants: {len(variants)}  ·  tasks: {len(task_ids)}",
        "- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた tool family (bq/slack) が expected と完全一致した割合 (skill 系呼び出しは無視、C3 は記録のみ)。",
        "- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録、C カテゴリの合否に使用)。",
        "",
        "## バリアント別サマリ",
        "",
        "| variant | pass (95% CI) | route ok | refusal | tokens | latency(s) | tool calls | LLM calls | errors |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for v in variants:
        s = summary[v]
        lo, hi = s["pass_ci"]
        lines.append(
            f"| `{v}` | {_pct(s['pass_rate'])} [{_pct(lo)}–{_pct(hi)}] | {_pct(s['route_ok_rate'])} | "
            f"{_pct(s['refusal_rate'])} | {s['tokens']:.0f} | {s['latency']:.1f} | "
            f"{s['tool_calls']:.1f} | {s['llm_calls']:.1f} | {s['n_error']} |"
        )
    lines += ["", "## カテゴリ別 pass rate", "",
              "| variant | " + " | ".join(categories) + " |",
              "| --- | " + " | ".join("---" for _ in categories) + " |"]
    for v in variants:
        row = [f"`{v}`"] + [_pct(summary[v]["by_category"].get(c, 0.0)) for c in categories]
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## タスク別 pass rate", "",
              "| task | " + " | ".join(f"`{v}`" for v in variants) + " |",
              "| --- | " + " | ".join("---" for _ in variants) + " |"]
    for tid in task_ids:
        row = [tid] + [_pct(summary[v]["by_task"].get(tid, 0.0)) for v in variants]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


async def _main_async(args) -> None:
    variants = args.variants or list(VARIANTS)
    tasks = [t for t in TASKS if not args.tasks or t.id in args.tasks]
    task_ids = [t.id for t in tasks]
    categories = sorted({t.category for t in tasks})
    sem = asyncio.Semaphore(args.concurrency)

    jobs = [_eval_one(v, t, sem) for v in variants for t in tasks for _ in range(args.runs)]
    total = len(jobs)
    print(f"running {total} cells (variants={variants}, tasks={task_ids}, "
          f"runs={args.runs}, concurrency={args.concurrency}, model={MODEL})", flush=True)

    records: list[dict] = []
    done = 0
    for coro in asyncio.as_completed(jobs):
        rec = await coro
        records.append(rec)
        done += 1
        if done % 5 == 0 or done == total:
            print(f"  [{done}/{total}]", flush=True)

    summary = _aggregate(records, variants, categories)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = args.tag or ""
    (RESULTS_DIR / f"results{suffix}.json").write_text(
        json.dumps(
            {"model": MODEL, "runs": args.runs, "variants": variants, "task_ids": task_ids,
             "summary": summary, "records": records},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    md = _render_markdown(summary, variants, task_ids, categories, args.runs)
    (RESULTS_DIR / f"RESULTS{suffix}.md").write_text(md, encoding="utf-8")
    print("\n" + md)

    n_err = sum(1 for r in records if r.get("error"))
    if n_err:
        print(f"⚠ {n_err}/{total} records had errors (集計から除外済み)。results{suffix}.json を参照。")


def main() -> None:
    p = argparse.ArgumentParser(description="Cross-variant knowledge-placement eval.")
    p.add_argument("--variants", nargs="*", choices=sorted(VARIANTS))
    p.add_argument("--tasks", nargs="*")
    p.add_argument("--runs", type=int, default=10)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--tag", default=None, help="出力ファイル名のサフィックス (例: _smoke)")
    asyncio.run(_main_async(p.parse_args()))


if __name__ == "__main__":
    main()
