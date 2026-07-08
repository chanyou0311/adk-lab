"""fat_closed: 知識を root instruction 全文 + 閉じた列挙 mandate。

知識配置=root、mandate=閉じた列挙。fat_open との差は mandate の開閉だけ (交絡分離用)。
"""

from __future__ import annotations

from google.adk.agents import Agent

from ..knowledge import knowledge_block
from ..model import make_generate_config, make_model
from ..tools import make_bq_tools, make_slack_tools
from .common import CLOSED_ENUMERATION, PERSONA

NAME = "fat_closed"


def build() -> Agent:
    instruction = (
        f"{PERSONA}\n\n{CLOSED_ENUMERATION}\n\n"
        f"# ドメイン知識 (社内ルール)\n{knowledge_block()}"
    )
    tools = [*make_bq_tools(rich=False), *make_slack_tools(rich=False)]
    return Agent(
        name=NAME,
        model=make_model(),
        description="Online store data assistant (knowledge in root instruction, closed mandate).",
        instruction=instruction,
        tools=tools,
        generate_content_config=make_generate_config(),
    )
