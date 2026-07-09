"""環境定義 (tools_for_env / shuffle_tools) のテスト (Vertex 不要・決定的)。

各環境のツール数 (6/12/18)・積み上げ関係・提示順 shuffle の決定性を固定する。
"""

from __future__ import annotations

import pytest

from lab.environments import (
    CLEAN,
    CONFUSABLE,
    DISTINCT,
    shuffle_tools,
    tools_for_env,
)

_GOLD = {
    "bq_list_tables", "bq_get_table_info", "bq_query",
    "slack_list_channels", "slack_read_channel", "slack_search_messages",
}


def _names(tools: list) -> list[str]:
    return [t.__name__ for t in tools]


def test_env_tool_counts():
    assert len(tools_for_env(CLEAN)) == 6
    assert len(tools_for_env(DISTINCT)) == 12
    assert len(tools_for_env(CONFUSABLE)) == 18


def test_clean_is_exactly_gold():
    assert set(_names(tools_for_env(CLEAN))) == _GOLD


def test_env_names_unique_and_layers_present():
    conf = _names(tools_for_env(CONFUSABLE))
    assert len(conf) == len(set(conf))  # 名前重複なし
    assert {"billing_list_charges", "billing_get_invoice", "billing_list_refunds"} <= set(conf)
    assert {"oncall_list_schedules", "oncall_get_shift", "oncall_list_assignments"} <= set(conf)
    assert {"portal_run_report", "portal_search_archive", "portal_list_groups"} <= set(conf)


def test_env_is_strict_superset_chain():
    assert set(_names(tools_for_env(CLEAN))) < set(_names(tools_for_env(DISTINCT)))
    assert set(_names(tools_for_env(DISTINCT))) < set(_names(tools_for_env(CONFUSABLE)))


def test_unknown_env_raises():
    with pytest.raises(ValueError):
        tools_for_env("bogus")


def test_shuffle_is_deterministic_and_permutation():
    tools = tools_for_env(CONFUSABLE)
    a = _names(shuffle_tools(tools, 0))
    b = _names(shuffle_tools(tools, 0))
    assert a == b  # 同じ seed → 同じ順序 (再現可能)
    assert sorted(a) == sorted(_names(tools))  # 並べ替えは置換 (集合不変)
    # 異なる seed では順序が変わりうる (seed が実際に効いている)。
    orderings = {tuple(_names(shuffle_tools(tools, s))) for s in range(5)}
    assert len(orderings) > 1


def test_shuffle_does_not_mutate_input():
    tools = tools_for_env(CLEAN)
    before = _names(tools)
    shuffle_tools(tools, 3)
    assert _names(tools) == before  # 入力リストは非破壊
