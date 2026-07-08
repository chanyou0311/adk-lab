"""thin_none: 知識を一切置かない下限対照。

root instruction は PERSONA + 役割指示のみ。ツールも rich=False。ドメイン知識 (K1-K6)
がどこにも無いので、知識依存タスク (E1/E2 等) は解けないはず — 他バリアントの上げ幅の基準線。
"""

from __future__ import annotations

from google.adk.agents import Agent

from ..model import make_generate_config, make_model
from ..tools import make_bq_tools, make_slack_tools
from .common import OPEN_MANDATE, PERSONA

NAME = "thin_none"


def build() -> Agent:
    instruction = f"{PERSONA}\n\n{OPEN_MANDATE}"
    tools = [*make_bq_tools(rich=False), *make_slack_tools(rich=False)]
    return Agent(
        name=NAME,
        model=make_model(),
        description="Online store data assistant (no domain knowledge — lower-bound control).",
        instruction=instruction,
        tools=tools,
        generate_content_config=make_generate_config(),
    )
