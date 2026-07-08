"""skills: 知識を Agent Skill (SKILL 本文 = L2) に置き、progressive disclosure で読ませる。

root は薄い (PERSONA + 開いた mandate)。ツール (bq+slack, rich=False) は常時露出のまま
(ツールゲーティングはしない — 知識配置だけを変える統制)。SkillToolset が
list_skills / load_skill / ... を注入し、L1 (name/description) を提示、モデルが必要と判断したら
load_skill で L2 本文 (= KNOWLEDGE body) を読む。SKILL の frontmatter description は
KNOWLEDGE の description を流用する。

ADK 2.4.0 の SkillToolset は Experimental。inline に models.Skill を構築して渡す
(ディスク上の SKILL.md 不要)。
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.skills import Frontmatter, Skill
from google.adk.tools.skill_toolset import SkillToolset

from ..knowledge import KNOWLEDGE
from ..model import make_generate_config, make_model
from ..tools import make_bq_tools, make_slack_tools
from .common import OPEN_MANDATE, PERSONA

NAME = "skills"


def _skill(key: str) -> Skill:
    k = KNOWLEDGE[key]
    return Skill(
        frontmatter=Frontmatter(name=k["name"], description=k["description"]),
        instructions=k["body"],
    )


def build() -> Agent:
    instruction = f"{PERSONA}\n\n{OPEN_MANDATE}"
    skillset = SkillToolset(skills=[_skill("sales-analytics"), _skill("slack-ops")])
    tools = [*make_bq_tools(rich=False), *make_slack_tools(rich=False), skillset]
    return Agent(
        name=NAME,
        model=make_model(),
        description="Online store data assistant (domain knowledge lives in Agent Skills).",
        instruction=instruction,
        tools=tools,
        generate_content_config=make_generate_config(),
    )
