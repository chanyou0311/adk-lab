"""run_eval のチェックポイント/レジューム機構のテスト (LLM 不要)。

長時間 run が kill されても課金済みジョブを失わないための機構。round-trip・部分書き込み
破損行の除去・完了済みキーのスキップ判定を固定する。
"""

import json

from run_eval import _append_checkpoint, _ckpt_key, _load_checkpoint


def _rec(cell: str, task_id: str, run_index: int, **extra) -> dict:
    return {"cell": cell, "task_id": task_id, "run_index": run_index, "passed": True, **extra}


def test_checkpoint_round_trip(tmp_path):
    path = tmp_path / "results_x.checkpoint.jsonl"
    recs = [_rec("single_flat@clean", "A1", 0), _rec("multi_transfer@confusable", "C1", 7)]
    for r in recs:
        _append_checkpoint(path, r)
    assert _load_checkpoint(path) == recs


def test_load_checkpoint_missing_file(tmp_path):
    assert _load_checkpoint(tmp_path / "nope.jsonl") == []


def test_load_checkpoint_drops_corrupt_tail(tmp_path):
    """kill による部分書き込み (途中で切れた最終行) は捨て、先行の完全な行は残す。"""
    path = tmp_path / "results_x.checkpoint.jsonl"
    _append_checkpoint(path, _rec("single_flat@clean", "A1", 0))
    with path.open("a", encoding="utf-8") as f:
        f.write('{"cell": "single_flat@clean", "task_id": "A2", "run')  # 途中で kill された行
    loaded = _load_checkpoint(path)
    assert len(loaded) == 1
    assert loaded[0]["task_id"] == "A1"


def test_ckpt_key_matches_job_identity():
    """スキップ判定のキーが (cell, task_id, run_index) の 3 つ組であることを固定する。

    run_eval のジョブ生成は (f"{v}@{e}", t.id, run_idx) でこの組と突き合わせる —
    キーの形が変わるとレジュームが全ジョブを再実行してしまう。
    """
    rec = _rec("multi_agenttool@confusable", "D2", 3)
    assert _ckpt_key(rec) == ("multi_agenttool@confusable", "D2", 3)


def test_resume_skip_filtering():
    """完了済みキー集合によるジョブのスキップが、run_eval と同じ式で成立することを固定する。"""
    prior = [_rec("single_flat@clean", "A1", 0), _rec("single_flat@clean", "A1", 1)]
    done_keys = {_ckpt_key(r) for r in prior}
    planned = [("single_flat", "clean", "A1", 0), ("single_flat", "clean", "A1", 1),
               ("single_flat", "clean", "A1", 2), ("single_flat", "clean", "A2", 0)]
    remaining = [(v, e, t, r) for (v, e, t, r) in planned
                 if (f"{v}@{e}", t, r) not in done_keys]
    assert remaining == [("single_flat", "clean", "A1", 2), ("single_flat", "clean", "A2", 0)]


def test_checkpoint_line_is_single_line(tmp_path):
    """1 record = 1 行 (改行を含む値があっても JSON エスケープされ行が割れない)。"""
    path = tmp_path / "results_x.checkpoint.jsonl"
    _append_checkpoint(path, _rec("single_flat@clean", "A1", 0, final="行1\n行2"))
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln]
    assert len(lines) == 1
    assert json.loads(lines[0])["final"] == "行1\n行2"
