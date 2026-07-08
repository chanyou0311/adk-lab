"""fat_open: 知識を root instruction 全文 + 役割指示。

知識配置=root。fat_closed との差は「役割指示か閉じた列挙か」だけ。
"""

from __future__ import annotations

from google.adk.agents import Agent

from ..knowledge import knowledge_block
from ..model import make_generate_config, make_model
from ..tools import make_bq_tools, make_slack_tools
from .common import OPEN_MANDATE, PERSONA

NAME = "fat_open"


def build() -> Agent:
    instruction = (
        f"{PERSONA}\n\n{OPEN_MANDATE}\n\n"
        f"# ドメイン知識 (社内ルール)\n{knowledge_block()}"
    )
    tools = [*make_bq_tools(rich=False), *make_slack_tools(rich=False)]
    return Agent(
        name=NAME,
        model=make_model(),
        description="Online store data assistant (knowledge in root instruction, open mandate).",
        instruction=instruction,
        tools=tools,
        generate_content_config=make_generate_config(),
    )
