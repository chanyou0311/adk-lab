"""ツール環境の定義 (agent-composition の tool-overload / confusability 軸)。

エージェントに提示するツール集合を 3 段階で定義する:

- ``CLEAN``      = bq 3 + slack 3               (6 tools)  — gold ツールのみ
- ``DISTINCT``   = CLEAN + billing 3 + oncall 3 (12 tools) — 別ドメインを足して「数」を増やす
- ``CONFUSABLE`` = DISTINCT + portal 6          (18 tools) — near-synonym distractor で「紛らわしさ」を足す

ツールに知識は載せない (rich=False)。本実験の変数はエージェント構成と環境であって知識配置ではない
(知識配置は knowledge-placement 実験で扱う)。

ツール提示順は run ごとに seeded shuffle する (位置バイアスを run 間で平均化)。``shuffle_tools`` は
決定的 (同じ seed → 同じ順序) で、使用 seed は呼び出し側 (run_eval) が raw record に残す。
"""

from __future__ import annotations

import random

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


def _gold_tools() -> list:
    """gold ツール (bq 3 + slack 3)。知識は載せない (rich=False)。"""
    return [*make_bq_tools(rich=False), *make_slack_tools(rich=False)]


def _distinct_domains() -> list:
    """別ドメイン (billing 3 + oncall 3)。tool-overload の「数」を作る。"""
    return [*make_billing_tools(), *make_oncall_tools()]


def tools_for_env(env: str) -> list:
    """環境名に対応するツール一覧を **正準順序** で返す (shuffle は shuffle_tools で別途行う)。

    正準順序は [gold, distinct domains, portal distractors] の積み上げ。実 run では位置バイアスを
    避けるため shuffle_tools でシャッフルする。
    """
    if env == CLEAN:
        return _gold_tools()
    if env == DISTINCT:
        return [*_gold_tools(), *_distinct_domains()]
    if env == CONFUSABLE:
        return [*_gold_tools(), *_distinct_domains(), *make_portal_tools()]
    raise ValueError(f"unknown environment {env!r}; expected one of {ENVIRONMENTS}")


def shuffle_tools(tools: list, seed: int) -> list:
    """ツール順を seed で決定的にシャッフルした新リストを返す (入力リストは変更しない)。

    位置バイアス (提示順による選択の偏り) を run 間で平均化するため、run ごとに run_index を seed
    として渡す。同じ seed なら常に同じ順序になり、使用 seed を raw record に残せば再現できる。
    """
    shuffled = list(tools)
    random.Random(seed).shuffle(shuffled)
    return shuffled
