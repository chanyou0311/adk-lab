"""multi_transfer: multi_agenttool と同じドメイン分割を transfer (sub_agents) で行う。

root は直接ツールを持たず、env に存在するドメインごとの sub-agent を ``sub_agents=`` に持つ。
ADK は sub_agents があると transfer_to_agent を自動注入する。root instruction に軽いルーティング
指針 (MULTI_ROUTING_GUIDANCE) を含め、各 sub の description で委譲先を選ばせる。
disallow_transfer_* は既定 (False) のまま。

multi_agenttool との違いは委譲機構 (AgentTool 呼び出し vs transfer)。sub-agent の役割文言
(SUBAGENT_PERSONA + OPEN_MANDATE) とドメイン分割は両者で揃える。
"""

from __future__ import annotations

from google.adk.agents import Agent

from ..environments import make_domain_tools, ordered_domains
from ..model import make_generate_config, make_model
from .common import (
    DOMAIN_DESCRIPTIONS,
    MULTI_ROUTING_GUIDANCE,
    OPEN_MANDATE,
    PERSONA,
    SUBAGENT_PERSONA,
)

NAME = "multi_transfer"


def _sub_agent(domain: str) -> Agent:
    return Agent(
        name=f"{domain}_assistant",
        model=make_model(),
        description=DOMAIN_DESCRIPTIONS[domain],
        instruction=f"{SUBAGENT_PERSONA}\n\n{OPEN_MANDATE}",
        tools=make_domain_tools(domain),
        generate_content_config=make_generate_config(),
    )


def build(env: str, seed: int | None = None) -> Agent:
    sub_agents = [_sub_agent(d) for d in ordered_domains(env, seed)]
    return Agent(
        name=NAME,
        model=make_model(),
        description="Online store coordinator transferring to per-domain specialist sub-agents.",
        instruction=f"{PERSONA}\n\n{OPEN_MANDATE}\n\n{MULTI_ROUTING_GUIDANCE}",
        sub_agents=sub_agents,
        generate_content_config=make_generate_config(),
    )
