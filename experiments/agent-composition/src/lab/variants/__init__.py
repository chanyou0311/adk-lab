"""agent-composition バリアントのレジストリ。

各バリアントは ``build() -> Agent`` を公開し、Agent.name はバリアント名に一致する。
バリアント実装 (単一エージェント / multi-agent 構成の各パターン) は本実験の設計が固まってから
追加する (後続作業)。scaffold 時点ではレジストリは空。共通の instruction 部品は
``common.py`` (PERSONA / OPEN_MANDATE / ROUTING_GUIDANCE 等) に置く。
"""

from __future__ import annotations

from collections.abc import Callable

from google.adk.agents import Agent

# name -> build() -> Agent。バリアント実装追加時にここへ登録する。
VARIANTS: dict[str, Callable[[], Agent]] = {}

__all__ = ["VARIANTS"]
