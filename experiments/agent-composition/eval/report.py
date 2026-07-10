"""集計 (Wilson 95% CI) と Markdown レポート生成 — run_eval と rescore で共有する。

オフラインの純関数のみ (ADK / Vertex への依存なし)。rescore はここだけに依存することで、
純オフライン再採点が ADK ランタイムの import に巻き込まれない。
"""

from __future__ import annotations

import math
import statistics
from typing import Any


def is_scored(record: dict) -> bool:
    """集計に含める record か。エージェント挙動起因の失敗 (``agent_error``、例: ツール幻覚) は
    passed=False の採点済みとして pass rate に含め、インフラ起因エラー (transient API・設定バグ等、
    ``error`` はあるが ``agent_error`` なし) のみ除外する。error record を一律除外すると、幻覚で
    落ちやすい multi 系に有利なバイアスがかかるのを防ぐ (tasks._classify_agent_error 参照)。
    """
    return not record.get("error") or bool(record.get("agent_error"))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def mean(xs: list[float]) -> float:
    return statistics.mean(xs) if xs else 0.0


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def aggregate(records: list[dict], variants: list[str], categories: list[str],
              group_field: str = "variant") -> dict:
    """records を group_field (既定 "variant"、agent-composition は "cell") で群化して集計する。

    群化キーを引数化することで、run_eval / rescore が `{**r, "variant": r["cell"]}` の詐称コピーを
    作らずに済む (cell=variant×env 集計をそのまま渡せる)。
    """
    summary: dict[str, Any] = {}
    for v in variants:
        rows = [r for r in records if r[group_field] == v]
        # agent_error (ツール幻覚等) は passed=False で pass rate に含める。除外は純インフラ error のみ。
        ok_rows = [r for r in rows if is_scored(r)]
        k = sum(1 for r in ok_rows if r["passed"])
        lo, hi = wilson(k, len(ok_rows))
        route_rows = [r for r in ok_rows if r["route_ok"] is not None]
        summary[v] = {
            "n": len(rows),
            "n_ok": len(ok_rows),
            "n_error": len(rows) - len(ok_rows),
            "pass_rate": k / len(ok_rows) if ok_rows else 0.0,
            "pass_ci": [lo, hi],
            "route_ok_rate": mean([1.0 if r["route_ok"] else 0.0 for r in route_rows]),
            "refusal_rate": mean([1.0 if r["refused"] else 0.0 for r in ok_rows]),
            "tokens": mean([r["tokens"] for r in ok_rows]),
            "latency": mean([r["latency"] for r in ok_rows]),
            "tool_calls": mean([r["n_tool_calls"] for r in ok_rows]),
            "llm_calls": mean([r["llm_calls"] for r in ok_rows]),
            "by_category": {
                c: mean([1.0 if r["passed"] else 0.0
                         for r in ok_rows if r["category"] == c])
                for c in categories
            },
            "by_task": {},
        }
        for r in ok_rows:
            summary[v]["by_task"].setdefault(r["task_id"], []).append(1.0 if r["passed"] else 0.0)
        summary[v]["by_task"] = {t: mean(xs) for t, xs in summary[v]["by_task"].items()}
    return summary


def render_markdown(summary: dict, variants: list[str], task_ids: list[str],
                    categories: list[str], runs: int, model: str) -> str:
    lines = [
        "# 知識配置バリアント評価 — 結果",
        "",
        f"- model: `{model}`  ·  runs/(variant,task): {runs}  ·  cells: {len(variants)}  ·  tasks: {len(task_ids)}",
        "- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた実ツールのドメインが expected と完全一致した割合 (委譲呼び出し *_assistant / transfer_to_agent と skill メタは無視)。",
        "- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録)。E 以外は refused=True で不正解にする (refused ゲート)。",
        "- errors 列 = インフラ起因エラー (transient API・設定バグ等) の件数で、pass rate から除外。ツール幻覚 (存在しないツールを呼んで停止) 等のエージェント挙動起因の失敗は agent_error として passed=False で pass rate に含める。",
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
            f"| `{v}` | {pct(s['pass_rate'])} [{pct(lo)}–{pct(hi)}] | {pct(s['route_ok_rate'])} | "
            f"{pct(s['refusal_rate'])} | {s['tokens']:.0f} | {s['latency']:.1f} | "
            f"{s['tool_calls']:.1f} | {s['llm_calls']:.1f} | {s['n_error']} |"
        )
    lines += ["", "## カテゴリ別 pass rate", "",
              "| variant | " + " | ".join(categories) + " |",
              "| --- | " + " | ".join("---" for _ in categories) + " |"]
    for v in variants:
        row = [f"`{v}`"] + [pct(summary[v]["by_category"].get(c, 0.0)) for c in categories]
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## タスク別 pass rate", "",
              "| task | " + " | ".join(f"`{v}`" for v in variants) + " |",
              "| --- | " + " | ".join("---" for _ in variants) + " |"]
    for tid in task_ids:
        row = [tid] + [pct(summary[v]["by_task"].get(tid, 0.0)) for v in variants]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"
