"""agent-composition バリアントのレジストリ。

各バリアントは ``build(env: str, seed: int | None = None)`` を公開し、root の name は
バリアント名に一致する (workflow_graph は Workflow ノード、他は Agent)。env でツール環境
(CLEAN/DISTINCT/CONFUSABLE) を切り替え、seed で提示順を run 毎シャッフルする。共通の instruction
部品と sub-agent ファクトリは ``common.py`` に置く。

- single_flat     : 単一エージェントが env の全ツールを直接持つ (基準線)
- single_skills   : SkillToolset でドメイン別にツールをゲーティング (root は直接ツールを持たない)
- multi_agenttool : root + ドメイン別 sub-agent を AgentTool で保持
- multi_transfer  : 同じドメイン分割を transfer (sub_agents) で
- workflow_graph  : Workflow (graph) エンジンで planner→dispatcher→synthesizer を写像
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import (
    multi_agenttool,
    multi_transfer,
    single_flat,
    single_skills,
    workflow_graph,
)

# name -> build(env, seed=None) -> Agent | Workflow
VARIANTS: dict[str, Callable[..., Any]] = {
    single_flat.NAME: single_flat.build,
    single_skills.NAME: single_skills.build,
    multi_agenttool.NAME: multi_agenttool.build,
    multi_transfer.NAME: multi_transfer.build,
    workflow_graph.NAME: workflow_graph.build,
}

__all__ = ["VARIANTS"]
