"""agent-composition バリアントのレジストリ。

各バリアントは ``build(env: str, seed: int | None = None) -> Agent`` を公開し、Agent.name は
バリアント名に一致する。env でツール環境 (CLEAN/DISTINCT/CONFUSABLE) を切り替え、seed で提示順を
run 毎シャッフルする。共通の instruction 部品は ``common.py`` に置く。

- single_flat     : 単一エージェントが env の全ツールを直接持つ (基準線)
- single_skills   : SkillToolset でドメイン別にツールをゲーティング (root は直接ツールを持たない)
- multi_agenttool : root + ドメイン別 sub-agent を AgentTool で保持
- multi_transfer  : 同じドメイン分割を transfer (sub_agents) で
"""

from __future__ import annotations

from collections.abc import Callable

from google.adk.agents import Agent

from . import multi_agenttool, multi_transfer, single_flat, single_skills

# name -> build(env, seed=None) -> Agent
VARIANTS: dict[str, Callable[..., Agent]] = {
    single_flat.NAME: single_flat.build,
    single_skills.NAME: single_skills.build,
    multi_agenttool.NAME: multi_agenttool.build,
    multi_transfer.NAME: multi_transfer.build,
}

__all__ = ["VARIANTS"]
