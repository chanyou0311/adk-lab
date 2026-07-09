"""multi_agenttool: root coordinator + ドメイン別 sub-agent を AgentTool で保持。

root は直接ツールを持たず、env に存在するドメインごとに 1 sub-agent (SUBAGENT_PERSONA +
OPEN_MANDATE + そのドメインのツール) を AgentTool として公開する。CONFUSABLE では portal も
独立 sub-agent (portal_assistant) になる — ルーティングで丸ごと回避可能にするのが設計意図。

AgentTool のオプションは既定 (include_plugins=True) のまま。これにより eval の MetricsPlugin が
子 Runner に伝播し、sub-agent 内部のトークン・tool 呼び出しも横断計測できる (ADK 2.4.0 では
AgentTool の sub-agent イベントは親の event ストリームに出ないため Plugin 方式が唯一の横断手段)。
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from ..environments import ordered_domains
from ..model import make_generate_config, make_model
from .common import MULTI_ROUTING_GUIDANCE, OPEN_MANDATE, PERSONA, make_domain_subagent

NAME = "multi_agenttool"


def build(env: str, seed: int | None = None) -> Agent:
    tools = [AgentTool(agent=make_domain_subagent(d)) for d in ordered_domains(env, seed)]
    return Agent(
        name=NAME,
        model=make_model(),
        description="Online store coordinator delegating to per-domain specialist sub-agents (AgentTool).",
        instruction=f"{PERSONA}\n\n{OPEN_MANDATE}\n\n{MULTI_ROUTING_GUIDANCE}",
        tools=tools,
        generate_content_config=make_generate_config(),
    )
