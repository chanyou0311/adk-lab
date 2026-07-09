"""ツール環境の定義 (agent-composition の tool-overload / confusability 軸)。

エージェントに提示するツール集合を 3 段階で定義する:

- ``CLEAN``      = bq 3 + slack 3               (6 tools)  — gold ツールのみ
- ``DISTINCT``   = CLEAN + billing 3 + oncall 3 (12 tools) — 別ドメインを足して「数」を増やす
- ``CONFUSABLE`` = DISTINCT + portal 6          (18 tools) — near-synonym distractor で「紛らわしさ」を足す

ツールに知識は載せない。本実験の変数はエージェント構成と環境であって知識配置ではない
(知識配置は knowledge-placement 実験で扱う)。

環境はドメイン単位 (bq/slack/billing/oncall/portal) で構成する。バリアント (single_flat/
single_skills/multi_*) は ``domains_for_env`` / ``make_domain_tools`` を使ってツールを組み立てる
(single_skills は 1 ドメイン=1 skill、multi_* は 1 ドメイン=1 sub-agent)。

提示順 (single_flat のツール順、multi_*/single_skills のドメイン順) は run ごとに seeded shuffle
する (位置バイアスを run 間で平均化)。``shuffle_tools`` / ``ordered_domains`` は決定的 (同じ seed →
同じ順序) で、使用 seed は呼び出し側 (run_eval) が raw record (tool_order_seed) に残す。
"""

from __future__ import annotations

import random
from collections.abc import Callable

from .naming import DOMAINS
from .tools import (
    make_billing_tools,
    make_bq_tools,
    make_oncall_tools,
    make_portal_tools,
    make_slack_tools,
)

CLEAN = "clean"
DISTINCT = "distinct"
CONFUSABLE = "confusable"
ENVIRONMENTS = (CLEAN, DISTINCT, CONFUSABLE)

# ドメイン → ツール生成関数。ツールに知識は載せない (本実験の変数はエージェント構成と環境)。
_DOMAIN_TOOLS: dict[str, Callable[[], list]] = {
    "bq": make_bq_tools,
    "slack": make_slack_tools,
    "billing": make_billing_tools,
    "oncall": make_oncall_tools,
    "portal": make_portal_tools,
}
# 正準ドメイン順 (naming が単一ソース。gold → distinct domains → portal distractor)。
DOMAIN_ORDER = list(DOMAINS)
# 各環境に存在するドメイン (正準順)。CONFUSABLE でのみ portal が加わる。
ENV_DOMAINS: dict[str, list[str]] = {
    CLEAN: ["bq", "slack"],
    DISTINCT: ["bq", "slack", "billing", "oncall"],
    CONFUSABLE: ["bq", "slack", "billing", "oncall", "portal"],
}


def domains_for_env(env: str) -> list[str]:
    """環境に存在するドメインの正準順リストを返す。"""
    if env not in ENV_DOMAINS:
        raise ValueError(f"unknown environment {env!r}; expected one of {ENVIRONMENTS}")
    return list(ENV_DOMAINS[env])


def make_domain_tools(domain: str) -> list:
    """1 ドメイン分のツール (bq/slack/billing/oncall=3 本、portal=6 本) を新規生成する。"""
    if domain not in _DOMAIN_TOOLS:
        raise ValueError(f"unknown domain {domain!r}; expected one of {DOMAIN_ORDER}")
    return list(_DOMAIN_TOOLS[domain]())


def tools_for_env(env: str) -> list:
    """環境名に対応するツール一覧を **正準順序** で返す (shuffle は shuffle_tools で別途行う)。

    正準順序は [gold, distinct domains, portal distractors] の積み上げ。実 run では位置バイアスを
    避けるため shuffle_tools でシャッフルする。
    """
    tools: list = []
    for domain in domains_for_env(env):
        tools.extend(make_domain_tools(domain))
    return tools


def ordered_domains(env: str, seed: int | None = None) -> list[str]:
    """環境のドメイン順を返す。seed 指定時は決定的にシャッフルする (multi_*/single_skills 用)。"""
    domains = domains_for_env(env)
    if seed is not None:
        random.Random(seed).shuffle(domains)
    return domains


def shuffle_tools(tools: list, seed: int) -> list:
    """ツール順を seed で決定的にシャッフルした新リストを返す (入力リストは変更しない)。

    位置バイアス (提示順による選択の偏り) を run 間で平均化するため、run ごとに run_index を seed
    として渡す。同じ seed なら常に同じ順序になり、使用 seed を raw record に残せば再現できる。
    """
    shuffled = list(tools)
    random.Random(seed).shuffle(shuffled)
    return shuffled
