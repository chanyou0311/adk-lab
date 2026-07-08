"""tool_desc: 知識を tool docstring に置く。

root instruction は薄い (PERSONA + 役割指示)。ツールを rich=True で作り、K1-K6 を
各ツールの description (docstring) に埋め込む。root は薄いまま、知識はツールに付随する。
"""

from __future__ import annotations

from google.adk.agents import Agent

from ..model import make_generate_config, make_model
from ..tools import make_bq_tools, make_slack_tools
from .common import OPEN_MANDATE, PERSONA

NAME = "tool_desc"


def build() -> Agent:
    instruction = f"{PERSONA}\n\n{OPEN_MANDATE}"
    tools = [*make_bq_tools(rich=True), *make_slack_tools(rich=True)]
    return Agent(
        name=NAME,
        model=make_model(),
        description="Online store data assistant (domain knowledge lives in tool docstrings).",
        instruction=instruction,
        tools=tools,
        generate_content_config=make_generate_config(),
    )
