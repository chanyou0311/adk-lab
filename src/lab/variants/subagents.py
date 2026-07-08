"""subagents: 知識を sub-agent の instruction に分割配置。

root は薄い (PERSONA + 開いた mandate + ルーティング指針) で、直接ツールを持たず、2 つの
スペシャリスト sub-agent を AgentTool として公開する:
- data_analyst: sales-analytics 知識 + bq ツール (rich=False)
- comms_analyst: slack-ops 知識 + slack ツール (rich=False)

注意 (ADK 2.4.0): AgentTool は sub-agent を別 Runner で実行するため、sub-agent 内部の
tool 呼び出し・トークンは親の event ストリームには現れない。eval ハーネスは Plugin
(before_tool_callback / after_model_callback) で root+sub 横断に収集する。
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from ..knowledge import knowledge_bodies_for_family
from ..model import make_generate_config, make_model
from ..tools import make_bq_tools, make_slack_tools
from .common import OPEN_MANDATE, PERSONA, ROUTING_GUIDANCE, SUBAGENT_PERSONA

NAME = "subagents"


def _data_analyst() -> Agent:
    instruction = (
        f"{SUBAGENT_PERSONA}\n\n{OPEN_MANDATE}\n\n"
        f"# data warehouse の社内ルール\n{knowledge_bodies_for_family('bq')}"
    )
    return Agent(
        name="data_analyst",
        model=make_model(),
        description=(
            "Warehouse & sales data specialist: answers questions about sales, revenue, "
            "orders, daily active users and support-ticket SLAs using the data warehouse."
        ),
        instruction=instruction,
        tools=make_bq_tools(rich=False),
        generate_content_config=make_generate_config(),
    )


def _comms_analyst() -> Agent:
    instruction = (
        f"{SUBAGENT_PERSONA}\n\n{OPEN_MANDATE}\n\n"
        f"# Slack 運用規約\n{knowledge_bodies_for_family('slack')}"
    )
    return Agent(
        name="comms_analyst",
        model=make_model(),
        description=(
            "Team communication specialist: answers questions about incidents (#alerts), "
            "releases (#releases) and customer support (#support) from Slack."
        ),
        instruction=instruction,
        tools=make_slack_tools(rich=False),
        generate_content_config=make_generate_config(),
    )


def build() -> Agent:
    instruction = f"{PERSONA}\n\n{OPEN_MANDATE}\n\n{ROUTING_GUIDANCE}"
    return Agent(
        name=NAME,
        model=make_model(),
        description="Online store data assistant (knowledge split across specialist sub-agents).",
        instruction=instruction,
        tools=[AgentTool(agent=_data_analyst()), AgentTool(agent=_comms_analyst())],
        generate_content_config=make_generate_config(),
    )
