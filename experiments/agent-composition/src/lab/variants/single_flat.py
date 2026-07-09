"""single_flat: 単一 LlmAgent が env の全ツールを直接持つ (基準線)。

instruction は PERSONA + 開いた役割指示 (OPEN_MANDATE) のみ。ツールに知識は載せない (rich=False)。
提示順は seed 指定時に run 毎シャッフルする (位置バイアスの平均化)。
"""

from __future__ import annotations

from google.adk.agents import Agent

from ..environments import shuffle_tools, tools_for_env
from ..model import make_generate_config, make_model
from .common import OPEN_MANDATE, PERSONA

NAME = "single_flat"


def build(env: str, seed: int | None = None) -> Agent:
    tools = tools_for_env(env)
    if seed is not None:
        tools = shuffle_tools(tools, seed)
    return Agent(
        name=NAME,
        model=make_model(),
        description="Online store data assistant (single flat agent holding all tools directly).",
        instruction=f"{PERSONA}\n\n{OPEN_MANDATE}",
        tools=tools,
        generate_content_config=make_generate_config(),
    )
