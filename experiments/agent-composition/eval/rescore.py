"""保存済み eval 結果をオフラインで再採点する (LLM 呼び出しなし)。

`results_<tag>.json` の各 record には final / tool_names / refused / variant / task_id が保存
されているので、tasks.py の *現行* チェック関数を全 record に再適用して passed / route_ok /
refused を再計算し、summary を再集計する。採点器 (例: E2 の免罪フレーズ) を直したあと、
高価な本番 eval を回し直さずに結果を更新するために使う。元ファイルは変更しない。

採点は tasks.score_record、集計/Markdown は report.py — どちらも run_eval.py と同一実装を
共有するので、再採点が本番 eval と別の数値を出す乖離は構造的に起きない。依存は
tasks/report のみ (ADK / Vertex への import なし = 純オフライン)。

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

from report import aggregate, render_markdown  # noqa: E402
from tasks import TASKS_BY_ID, score_record  # noqa: E402


def _rescore_record(rec: dict) -> dict:
    """1 record を現行のチェック関数で再採点する (error record はそのまま保持)。"""
    if rec.get("error"):
        return rec
    out = {**rec}
    # 旧採点フィールドは現行採点の結果で置き換える。旧スキーマの残骸 (families/expected_families /
    # score_error) を除いてから update しないと、新旧フィールドが混在した矛盾 record になる。
    for stale in ("score_error", "families", "expected_families"):
        out.pop(stale, None)
    task = TASKS_BY_ID.get(rec["task_id"])
    out.update(score_record(task, rec.get("final", ""), rec.get("tool_names", []),
                            tool_calls=rec.get("tool_calls")))
    return out


def _group_key(records: list[dict]) -> str:
    """集計群のキー。agent-composition は cell (variant×env)、旧実験は variant。"""
    return "cell" if any("cell" in r for r in records) else "variant"


def _pass_counts(records: list[dict], group_key: str) -> dict[tuple[str, str], list[int]]:
    """(task_id, group) → [pass 数, ok 数] を 1 パスで集計する。"""
    counts: dict[tuple[str, str], list[int]] = {}
    for r in records:
        if r.get("error"):
            continue
        cell = counts.setdefault((r["task_id"], r[group_key]), [0, 0])
        cell[1] += 1
        cell[0] += int(bool(r["passed"]))
    return counts


def _task_before_after_table(before: dict, after: dict, task_id: str, group_label: str) -> str:
    groups = sorted({g for (t, g) in before if t == task_id})
    lines = [f"| {group_label} | {task_id} before | {task_id} after |", "| --- | --- | --- |"]
    for g in groups:
        b = before.get((task_id, g), [0, 0])
        a = after.get((task_id, g), [0, 0])
        lines.append(f"| `{g}` | {b[0]}/{b[1]} | {a[0]}/{a[1]} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline re-scoring of saved eval results.")
    ap.add_argument("--tag", default="_main", help="results_<tag>.json のタグ (例: _main)")
    args = ap.parse_args()

    src = RESULTS_DIR / f"results{args.tag}.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    original = data["records"]
    rescored = [_rescore_record(r) for r in original]

    # 集計群は run_eval と揃える (agent-composition は cell=variant×env)。report.py は "variant"
    # フィールドで群化するので、group_key を "variant" 位置に写した浅いコピーで集計する。
    group_key = _group_key(rescored)
    groups = (data.get("cells") if group_key == "cell" else data.get("variants")) \
        or sorted({r[group_key] for r in rescored})
    task_ids = data.get("task_ids") or sorted({r["task_id"] for r in rescored})
    categories = sorted({r["category"] for r in rescored})
    runs = data.get("runs", 0)
    model = data.get("model", "")

    summary = aggregate(rescored, groups, categories, group_field=group_key)
    out_json = RESULTS_DIR / f"results{args.tag}_rescored.json"
    out_key = "cells" if group_key == "cell" else "variants"
    out_json.write_text(
        json.dumps(
            {"model": model, "runs": runs, out_key: groups, "task_ids": task_ids,
             "rescored_from": src.name, "summary": summary, "records": rescored},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    md = render_markdown(summary, groups, task_ids, categories, runs, model)
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

    before_counts = _pass_counts(original, group_key)
    after_counts = _pass_counts(rescored, group_key)
    changed = sorted({t for (t, g), b in before_counts.items() if b != after_counts.get((t, g))})
    if not changed:
        print("\n(採点結果に変化のあったタスクはありません)")
    for tid in changed:
        print(f"\n{tid} before/after ({group_key} 別):")
        print(_task_before_after_table(before_counts, after_counts, tid, group_key))


if __name__ == "__main__":
    main()
