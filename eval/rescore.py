"""保存済み eval 結果をオフラインで再採点する (LLM 呼び出しなし)。

`results_<tag>.json` の各 record には final / tool_names / refused / variant / task_id が保存
されているので、tasks.py の *現行* チェック関数を全 record に再適用して passed / route_ok /
refused を再計算し、summary を再集計する。採点器 (例: E2 の免罪フレーズ) を直したあと、
高価な本番 eval を回し直さずに結果を更新するために使う。元ファイルは変更しない。

集計 (`_aggregate`) と Markdown 生成 (`_render_markdown`)・Wilson CI は run_eval.py から
import して再利用する (run_eval の import は完全オフライン — Vertex 呼び出しは main() 内だけ)。

Usage:
    uv run python eval/rescore.py --tag _main
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
sys.path.insert(0, str(EVAL_DIR))

from run_eval import _aggregate, _render_markdown  # noqa: E402
from tasks import GT, TASKS_BY_ID, called_families, is_refused  # noqa: E402


def _rescore_record(rec: dict) -> dict:
    """1 record を現行のチェック関数で再採点する (error record はそのまま保持)。"""
    if rec.get("error"):
        return rec
    task = TASKS_BY_ID.get(rec["task_id"])
    final = rec.get("final", "")
    tool_names = rec.get("tool_names", [])
    refused = is_refused(final)
    passed = False
    score_error = None
    if task is not None:
        try:
            passed = bool(task.check(final, tool_names, GT, refused))
        except Exception as exc:  # noqa: BLE001 - 採点例外は fail 扱い
            score_error = f"{type(exc).__name__}: {exc}"[:200]
    fams = called_families(tool_names)
    route_ok = None
    if task is not None and task.route_scored:
        route_ok = fams == task.expected_families
    out = {
        **rec,
        "passed": passed,
        "refused": refused,
        "families": sorted(fams),
        "expected_families": sorted(task.expected_families) if task else rec.get("expected_families", []),
        "route_ok": route_ok,
    }
    if score_error:
        out["score_error"] = score_error
    return out


def _task_before_after(original: list[dict], rescored: list[dict], task_id: str) -> str:
    """指定タスクの before/after pass 数をバリアント別に集計したテーブル文字列。"""
    variants = sorted({r["variant"] for r in original if r["task_id"] == task_id})

    def counts(records):
        by = {v: [0, 0] for v in variants}  # [pass, ok_total]
        for r in records:
            if r["task_id"] != task_id or r.get("error"):
                continue
            by[r["variant"]][1] += 1
            if r["passed"]:
                by[r["variant"]][0] += 1
        return by

    b, a = counts(original), counts(rescored)
    lines = [f"| variant | {task_id} before | {task_id} after |", "| --- | --- | --- |"]
    for v in variants:
        lines.append(f"| `{v}` | {b[v][0]}/{b[v][1]} | {a[v][0]}/{a[v][1]} |")
    return "\n".join(lines)


def _changed_tasks(original: list[dict], rescored: list[dict]) -> list[str]:
    """before→after で 1 バリアントでも pass 数が変わったタスク ID を返す。"""
    orig_by = {}
    resc_by = {}
    for r in original:
        if not r.get("error"):
            orig_by[(r["task_id"], r["variant"])] = orig_by.get((r["task_id"], r["variant"]), 0) + int(r["passed"])
    for r in rescored:
        if not r.get("error"):
            resc_by[(r["task_id"], r["variant"])] = resc_by.get((r["task_id"], r["variant"]), 0) + int(r["passed"])
    changed = {k[0] for k in orig_by if orig_by.get(k) != resc_by.get(k)}
    return sorted(changed)


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline re-scoring of saved eval results.")
    ap.add_argument("--tag", default="_main", help="results_<tag>.json のタグ (例: _main)")
    args = ap.parse_args()

    src = RESULTS_DIR / f"results{args.tag}.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    original = data["records"]
    rescored = [_rescore_record(r) for r in original]

    variants = data.get("variants") or sorted({r["variant"] for r in rescored})
    task_ids = data.get("task_ids") or sorted({r["task_id"] for r in rescored})
    categories = sorted({r["category"] for r in rescored})
    runs = data.get("runs", 0)
    model = data.get("model", "")

    summary = _aggregate(rescored, variants, categories)
    out_json = RESULTS_DIR / f"results{args.tag}_rescored.json"
    out_json.write_text(
        json.dumps(
            {"model": model, "runs": runs, "variants": variants, "task_ids": task_ids,
             "rescored_from": src.name, "summary": summary, "records": rescored},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    md = _render_markdown(summary, variants, task_ids, categories, runs)
    md = md.replace(
        "# 知識配置バリアント評価 — 結果",
        f"# 知識配置バリアント評価 — 結果 (再採点: {src.name})",
        1,
    )
    (RESULTS_DIR / f"RESULTS{args.tag}_rescored.md").write_text(md, encoding="utf-8")

    # before/after の要約を標準出力へ。
    def overall_pass(records):
        ok = [r for r in records if not r.get("error")]
        k = sum(1 for r in ok if r["passed"])
        return k, len(ok)

    kb, nb = overall_pass(original)
    ka, na = overall_pass(rescored)
    print(f"rescored {src.name} -> {out_json.name}")
    print(f"総合 pass: before {kb}/{nb} ({kb / nb * 100:.1f}%)  ->  after {ka}/{na} ({ka / na * 100:.1f}%)")
    changed = _changed_tasks(original, rescored)
    if not changed:
        print("\n(採点結果に変化のあったタスクはありません)")
    for tid in changed:
        print(f"\n{tid} before/after (variant 別):")
        print(_task_before_after(original, rescored, tid))


if __name__ == "__main__":
    main()
