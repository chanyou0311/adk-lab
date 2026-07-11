"""canonical_report のマージ規則 (supersede / 13 セル) をコミット済み結果に対して検証する。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

from canonical_report import EXPECTED_CELLS, load_topup, merge_base, render, scoreboard


def test_merge_base_is_13_cells_without_stale_graph():
    base = merge_base()
    cells = {(r["variant"], r["env"]) for r in base}
    assert len(cells) == EXPECTED_CELLS
    # _main2 の workflow_graph (旧実装) が混入していないこと: graph の record 数は _graph2 の
    # 2 セル × 16 タスク × 8 runs のみ。
    graph = [r for r in base if r["variant"] == "workflow_graph"]
    assert len(graph) == 2 * 16 * 8


def test_scoreboard_covers_all_variants():
    base = merge_base()
    topup = load_topup()
    board = scoreboard(base, topup)
    assert {row["variant"] for row in board} == {
        "single_flat", "single_skills", "multi_agenttool",
        "multi_transfer", "multi_taskmode", "workflow_graph",
    }
    # C 列は追い足し込みで n≈64 (エラー除外で 63 のことがある)
    assert all(row["c"][1] >= 60 for row in board)


def test_render_reproduces_committed_canonical():
    committed = (Path(__file__).resolve().parent.parent
                 / "eval" / "results" / "RESULTS_canonical.md")
    assert render(merge_base(), load_topup()) == committed.read_text(encoding="utf-8")
