"""single_skills: ドメイン別ツールを SkillToolset でゲーティングする単一エージェント。

root は直接ツールを持たず、SkillToolset だけを持つ。各ドメイン (env に存在する bq/slack/billing/
oncall/portal) を 1 Skill とし、その Skill の frontmatter.metadata["adk_additional_tools"] に
そのドメインのツール名を列挙する。ツールの実体は SkillToolset の additional_tools に渡す。

ADK 2.4.0 のツールゲーティング挙動 (ソース検証済み: tools/skill_toolset.py):
- 初期状態で LLM に見えるのは skill メタツール (list_skills / load_skill / load_skill_resource /
  run_skill_script) のみ。ドメインツールの宣言は露出しない (get_tools は活性スキル 0 のとき
  additional_tools を返さない)。
- ListSkillsTool が在るため process_llm_request は skills XML を system instruction に注入しない
  → スキル名の発見にも list_skills 呼び出しが要る。
- load_skill(<domain>) が state に活性化を記録し、次の get_tools でそのドメインの
  adk_additional_tools が解決されて初めてツール宣言が露出する (_use_invocation_cache=False で
  同一 turn 内に反映)。

= 真のツールゲーティング。confusability は list_skills が見せる skill description のレベルに移る
(portal の description を gold と重ねて紛らわしくしてある)。
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.skills import Frontmatter, Skill
from google.adk.tools.skill_toolset import SkillToolset

from ..environments import make_domain_tools, ordered_domains
from ..model import make_generate_config, make_model
from .common import DOMAIN_DESCRIPTIONS, OPEN_MANDATE, PERSONA

NAME = "single_skills"


def _skill_for(domain: str, tools: list) -> Skill:
    tool_names = [t.__name__ for t in tools]
    return Skill(
        frontmatter=Frontmatter(
            name=domain,  # kebab/snake いずれも単語なので valid
            description=DOMAIN_DESCRIPTIONS[domain],
            metadata={"adk_additional_tools": tool_names},
        ),
        instructions=(
            f"このスキルは「{domain}」ドメインのツールを提供します。"
            f"利用可能なツール: {', '.join(tool_names)}。"
            "これらのツールでデータを取得し、ユーザーの質問に答えてください。"
        ),
    )


def build(env: str, seed: int | None = None) -> Agent:
    skills: list[Skill] = []
    additional_tools: list = []
    for domain in ordered_domains(env, seed):
        tools = make_domain_tools(domain)
        additional_tools.extend(tools)
        skills.append(_skill_for(domain, tools))
    skillset = SkillToolset(skills=skills, additional_tools=additional_tools)
    return Agent(
        name=NAME,
        model=make_model(),
        description="Online store data assistant (tools gated behind per-domain skills).",
        instruction=f"{PERSONA}\n\n{OPEN_MANDATE}",
        tools=[skillset],
        generate_content_config=make_generate_config(),
    )
