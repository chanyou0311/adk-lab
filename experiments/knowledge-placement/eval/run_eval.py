"""知識配置バリアントのクロス評価ランナー。

同一のタスクセットを全バリアントに対して実行し、正答率 (Wilson 95% CI)・トークン・レイテンシ・
ツールルーティング精度・拒否率を決定的に採点して比較する。採点は tasks.score_record、
集計/レポートは report.py に置き、オフライン再採点 (rescore.py) と完全に共有する。

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

from lab.model import MODEL  # noqa: E402
from lab.variants import VARIANTS  # noqa: E402

load_dotenv()

USER_ID = "eval"
APP_NAME = "adk_thin_agent_lab"
_MAX_ATTEMPTS = 3
_BACKOFF = [5, 15]  # seconds before retry attempt 2 / 3 (最終試行後は sleep しない)
# 一時的エラーの部分一致マーカー (照合は小文字化して行う)。
_TRANSIENT_MARKERS = (
    "429", "500", "503", "resource_exhausted", "unavailable", "internal",
    "deadline", "timeout", "temporarily", "connection", "servererror",
    "serviceunavailable",
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
    msg = str(exc).lower()
    return any(m in msg for m in _TRANSIENT_MARKERS)


def _zero_metrics() -> dict:
    """メトリクスの空形。_run_once の初期値と error fallback で共有し、スキーマを 1 箇所にする。"""
    return {
        "final": "",
        "latency": 0.0,
        "tool_calls": [],
        "tool_names": [],
        "n_tool_calls": 0,
        "llm_calls": 0,
        "tokens": 0,
        "prompt_tokens": 0,
        "candidate_tokens": 0,
    }


async def _run_once(variant: str, prompt: str) -> dict:
    root = VARIANTS[variant]()
    plugin = MetricsPlugin()
    app = App(name=APP_NAME, root_agent=root, plugins=[plugin])
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(
        app_name=runner.app_name, user_id=USER_ID
    )
    message = types.UserContent(prompt)

    final = ""
    start = time.perf_counter()
    try:
        async for event in runner.run_async(
            user_id=USER_ID, session_id=session.id, new_message=message
        ):
            content = getattr(event, "content", None)
            parts = content.parts if content is not None else None
            text = "".join(p.text for p in (parts or []) if getattr(p, "text", None))
            if event.is_final_response() and text:
                final = text
    finally:
        latency = time.perf_counter() - start
        await runner.close()

    return {
        **_zero_metrics(),
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
                metrics = {**_zero_metrics(), "error": f"{type(exc).__name__}: {exc}"[:300]}
                break

        metrics.update(
            score_record(task, metrics["final"], metrics["tool_names"], metrics.get("error"))
        )
        metrics.update({"variant": variant, "task_id": task.id, "category": task.category})
        return metrics


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

    summary = aggregate(records, variants, categories)
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
    md = render_markdown(summary, variants, task_ids, categories, args.runs, MODEL)
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
