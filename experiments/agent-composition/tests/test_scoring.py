"""汎用採点ヘルパー (数値/日付/拒否) と naming (ドメイン/委譲判定) の回帰テスト。

Vertex 不要・決定的。タスク固有の採点は test_tasks.py。
"""

from __future__ import annotations

from tasks import (  # conftest.py が eval/ を sys.path に追加している
    answer_contains_date,
    answer_contains_number,
    is_refused,
)

from lab.naming import (
    called_domains,
    domain_of,
    has_distractor_call,
    real_tool_names,
    routed_domains,
)


# --- 数値照合 (万/千/億・カンマ・相対誤差) ---
def test_number_units_and_noise():
    assert answer_contains_number("売上は6千万円です", 60_000_000)
    assert answer_contains_number("売上は約802万円です", 8_020_316)
    assert answer_contains_number("合計は 1,234,567 円です", 1_234_000, rel_tol=0.01)


def test_number_zero_matching():
    # value=0 は絶対誤差で判定する (相対誤差だと 0 に一致できない)。
    assert answer_contains_number("差分は 0 件でした", 0.0)


# --- 日付照合 (表記ゆらぎ・数字境界) ---
def test_date_no_substring_false_positive():
    assert not answer_contains_date("最大の売上日は 6/30 です", "2026-06-03")
    assert answer_contains_date("最大の売上日は 6月3日 です", "2026-06-03")
    assert answer_contains_date("最大の売上日は 2026-06-03 です", "2026-06-03")


# --- 拒否検出 (文単位 + 逆接ヘッジ) ---
def test_is_refused_ignores_hedged_estimates():
    assert not is_refused("正確には算出できませんが、概算では約800万円と見込まれます。")
    assert not is_refused("専用の予測する機能はありませんが、データから概算すると約800万円です。")
    assert is_refused("予測することはできません。")
    assert is_refused("そのようなデータを持ち合わせておりません。")


# --- naming: 実ツール / 委譲 / skill メタの区別 ---
def test_domain_of_real_tools_and_exclusions():
    assert domain_of("bq_query") == "bq"
    assert domain_of("slack_read_channel") == "slack"
    assert domain_of("billing_list_charges") == "billing"
    assert domain_of("portal_run_report") == "portal"
    # 委譲呼び出し・skill メタは実ツールでないので None。
    assert domain_of("bq_assistant") is None
    assert domain_of("transfer_to_agent") is None
    assert domain_of("list_skills") is None
    assert domain_of("some_other_tool") is None


def test_real_tool_names_excludes_delegation_and_skill():
    traj = ["bq_assistant", "bq_query", "list_skills", "load_skill", "transfer_to_agent", "slack_read_channel"]
    assert real_tool_names(traj) == ["bq_query", "slack_read_channel"]


def test_called_domains_dedup():
    assert called_domains(["bq_list_tables", "bq_query", "slack_search_messages", "list_skills"]) == frozenset(
        {"bq", "slack"}
    )
    # 委譲名だけでは実ドメインは立たない (bq_assistant は実ツールでない)。
    assert called_domains(["bq_assistant", "transfer_to_agent"]) == frozenset()
    assert called_domains([]) == frozenset()


def test_has_distractor_call():
    assert has_distractor_call(["bq_query", "portal_search_archive"])
    assert not has_distractor_call(["bq_query", "slack_read_channel"])
    # portal_assistant (委譲名) だけでは trap ではない (実 portal ツールを呼んでいない)。
    assert not has_distractor_call(["portal_assistant"])


def test_routed_domains_from_agenttool_and_transfer():
    # AgentTool: 呼び出し名 f"{domain}_assistant" から。
    tc_at = [{"name": "bq_assistant", "args": {}}, {"name": "slack_assistant", "args": {}}]
    assert routed_domains(tc_at) == ["bq", "slack"]
    # transfer: args.agent_name から。
    tc_tr = [{"name": "transfer_to_agent", "args": {"agent_name": "portal_assistant"}}]
    assert routed_domains(tc_tr) == ["portal"]
    # 実ツール呼び出しは委譲でない。
    assert routed_domains([{"name": "bq_query", "args": {"sql": "..."}}]) == []
