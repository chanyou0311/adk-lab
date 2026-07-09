"""multi_taskmode: Collaborative task-mode 委譲 (ADK 2.0 の新委譲機構、transfer の現代版)。

coordinator (LlmAgent, mode 既定) が ドメイン別 sub-agent を ``sub_agents=`` に持ち、各 sub-agent を
**mode='single_turn'** にする。ADK 2.4.0 は single_turn の sub-agent を ``_SingleTurnAgentTool``
(AgentTool サブクラス、tool.name == sub_agent.name) として coordinator のツールに追加する
(llm_agent.py 1116-1133)。coordinator は function-calling でこの委譲ツールを呼び、sub-agent が単発で
タスクを完了して結果を返す。

**mode='single_turn' を選ぶ理由 (mode='task' を避ける)**: 本 eval はバッチ実行でユーザー応答が無い。
mode='task' の sub-agent は multi-turn でユーザーへ途中確認 (chat) する可能性があり、応答が来ずに
**ハングする**リスクがある (workflow でも task-mode の静的ノードは同理由で禁止されている)。single_turn は
「ユーザーと会話せず単発でタスクを完了する」モード (llm_agent.py mode docstring) なのでバッチに適する。
input/output schema は既定 ({goal, background} → {result}) のまま。

素材 (persona/tools/model) は make_domain_subagent と同一で、**委譲機構だけが唯一の差** (multi_agenttool=
AgentTool / multi_transfer=transfer / multi_taskmode=single_turn task-mode) の統制を保つ。委譲ツール名は
いずれも `{domain}_assistant` なので trajectory 指標は naming.py で対称に扱われる (delegations に復元、
実ツール判定から除外)。
"""

from __future__ import annotations

from google.adk.agents import Agent

from ..environments import ordered_domains
from ..model import make_generate_config, make_model
from .common import MULTI_ROUTING_GUIDANCE, OPEN_MANDATE, PERSONA, make_domain_subagent

NAME = "multi_taskmode"


def build(env: str, seed: int | None = None) -> Agent:
    sub_agents = [make_domain_subagent(d, mode="single_turn") for d in ordered_domains(env, seed)]
    return Agent(
        name=NAME,
        model=make_model(),
        description="Online store coordinator delegating to per-domain specialists via task-mode (single_turn).",
        instruction=f"{PERSONA}\n\n{OPEN_MANDATE}\n\n{MULTI_ROUTING_GUIDANCE}",
        sub_agents=sub_agents,
        generate_content_config=make_generate_config(),
    )
