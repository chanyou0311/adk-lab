"""エージェント挙動起因の失敗 (ツール幻覚) の分類と集計包含のテスト (Vertex 不要)。

sub-agent が保持しないツールを幻覚して `Tool '...' not found` で停止するのはモデルの選択ミスであり、
インフラ障害ではない。error record として集計除外すると幻覚で落ちやすい multi 系に有利なバイアスが
かかるので、agent_error として passed=False で pass rate に含める (transient/設定バグは除外のまま)。
"""

from __future__ import annotations

from report import aggregate, is_scored
from rescore import _rescore_record
from tasks import _classify_agent_error, score_record

# ADK が投げる実際の文字列 (results_main.json / results_smoke2.json の一次データ由来)。
_TOOL_HALLUCINATION = (
    "ValueError: Tool 'sql_query' not found.\n"
    "Available tools: slack_list_channels, slack_read_channel, slack_search_messages"
)
_RERUN_CONFIG_BUG = (
    "ValueError: A node must have rerun_on_resume=True. Reason is that dynamically "
    "scheduled nodes might be interrupted, and the workflow wakes-up/re-runs the parent node."
)
_TRANSIENT = "ServerError: 503 The service is currently unavailable."


# --- 分類子 (agent 起因 vs インフラ起因) ---
def test_classify_tool_hallucination():
    assert _classify_agent_error(_TOOL_HALLUCINATION) == "tool_hallucination"
    # workflow_graph は DynamicNodeFailError でラップするが、内側の文言でも拾える。
    assert _classify_agent_error(
        "DynamicNodeFailError: ... caused by Tool 'bq_query' not found ..."
    ) == "tool_hallucination"
    # ダブルクオート形式も拾う。
    assert _classify_agent_error('ValueError: Tool "x" not found') == "tool_hallucination"


def test_classify_infra_errors_are_not_agent_error():
    # 設定バグ (rerun_on_resume) と transient API はエージェント挙動起因ではない → 除外のまま。
    assert _classify_agent_error(_RERUN_CONFIG_BUG) is None
    assert _classify_agent_error(_TRANSIENT) is None
    assert _classify_agent_error(None) is None
    assert _classify_agent_error("") is None
    # "not found" 単体 (ツール以外) は誤検出しない。
    assert _classify_agent_error("KeyError: session not found") is None


# --- score_record が agent_error を付し、is_scored が含める ---
def test_score_record_tags_and_includes_tool_hallucination():
    out = score_record(None, "", [], error=_TOOL_HALLUCINATION)
    assert out["agent_error"] == "tool_hallucination"
    assert out["passed"] is False
    # error はあるが agent_error なので集計に含める。
    rec = {**out, "error": _TOOL_HALLUCINATION}
    assert is_scored(rec) is True


def test_score_record_infra_error_stays_excluded():
    out = score_record(None, "", [], error=_RERUN_CONFIG_BUG)
    assert "agent_error" not in out
    rec = {**out, "error": _RERUN_CONFIG_BUG}
    assert is_scored(rec) is False


def test_is_scored_plain_pass_record():
    assert is_scored({"passed": True}) is True  # error なし → 含める


# --- aggregate: 幻覚 record が pass rate の分母に入り、errors 列には入らない ---
def _rec(cell, passed, category="A", task_id="A1", **extra):
    base = {
        "cell": cell, "category": category, "task_id": task_id, "passed": passed,
        "route_ok": None if extra.get("error") else True, "refused": False,
        "tokens": 100, "latency": 1.0, "n_tool_calls": 1, "llm_calls": 1,
    }
    base.update(extra)
    return base


def test_aggregate_counts_tool_hallucination_as_failure():
    records = [
        _rec("multi@confusable", True),
        _rec("multi@confusable", True),
        # ツール幻覚で停止 → passed=False・agent_error 付き。
        _rec("multi@confusable", False, error=_TOOL_HALLUCINATION,
             agent_error="tool_hallucination"),
        # 純 transient error → 除外。
        _rec("multi@confusable", False, error=_TRANSIENT),
    ]
    s = aggregate(records, ["multi@confusable"], ["A"], group_field="cell")["multi@confusable"]
    # ok_rows = 2 pass + 1 幻覚 fail = 3 (transient は除外)。pass_rate = 2/3。
    assert s["n"] == 4
    assert s["n_ok"] == 3
    assert s["n_error"] == 1  # transient のみ
    assert abs(s["pass_rate"] - 2 / 3) < 1e-9
    assert abs(s["by_category"]["A"] - 2 / 3) < 1e-9


def test_aggregate_without_reclassification_would_overstate():
    # 対照: 幻覚 record を除外すると pass_rate=100% になってしまう (バイアスの実証)。
    records = [
        _rec("multi@confusable", True),
        _rec("multi@confusable", True),
        _rec("multi@confusable", False, error=_TOOL_HALLUCINATION),  # agent_error 無し = 除外
    ]
    s = aggregate(records, ["multi@confusable"], ["A"], group_field="cell")["multi@confusable"]
    assert s["pass_rate"] == 1.0  # 幻覚を除外すると 100% に膨らむ (= 修正が必要な理由)


# --- rescore が保存済み error record へ遡及分類する (再実行なし) ---
def test_rescore_retroactively_reclassifies_saved_error_record():
    # _main の一次データを模した保存済み error record (agent_error フィールドは未付与)。
    original = {
        "task_id": "E1", "cell": "multi_agenttool@clean", "category": "E",
        "final": "", "tool_names": [], "tool_calls": [], "passed": False,
        "error": _TOOL_HALLUCINATION,
    }
    assert is_scored(original) is False  # 分類前は除外されていた
    rescored = _rescore_record(original)
    assert rescored["agent_error"] == "tool_hallucination"
    assert rescored["passed"] is False
    assert is_scored(rescored) is True  # 再採点で pass rate に含まれるようになる
    assert rescored["error"] == _TOOL_HALLUCINATION  # error 文字列は保持


def test_rescore_leaves_infra_error_excluded():
    original = {
        "task_id": "A1", "cell": "workflow_graph@clean", "category": "A",
        "final": "", "tool_names": [], "tool_calls": [], "passed": False,
        "error": _RERUN_CONFIG_BUG,
    }
    rescored = _rescore_record(original)
    assert "agent_error" not in rescored
    assert is_scored(rescored) is False
