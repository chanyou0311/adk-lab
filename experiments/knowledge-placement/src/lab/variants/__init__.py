"""知識配置バリアントのレジストリ。

各バリアントは ``build() -> Agent`` を公開し、Agent.name はバリアント名に一致する。
"""

from __future__ import annotations

from collections.abc import Callable

from google.adk.agents import Agent

from . import fat_closed, fat_open, skills, subagents, thin_none, tool_desc

# name -> build() -> Agent
VARIANTS: dict[str, Callable[[], Agent]] = {
    fat_closed.NAME: fat_closed.build,
    fat_open.NAME: fat_open.build,
    thin_none.NAME: thin_none.build,
    tool_desc.NAME: tool_desc.build,
    subagents.NAME: subagents.build,
    skills.NAME: skills.build,
}

__all__ = ["VARIANTS"]
