"""workflow_graph: ADK 2.4.0 の Workflow (graph) エンジンでドメイン分割を写像する。

トポロジ: planner → dispatcher → synthesizer の線形 spine (Workflow.edges)。
- planner (LlmAgent, output_schema=_Plan): 質問と各ドメインの description を見て、必要なドメイン集合を
  構造化出力する。question を echo し、どのドメインでも答えられない (irrelevance) なら domains は空。
- dispatcher (FunctionNode): planner の plan を受け、選ばれたドメインの専門ノードを ``ctx.run_node``
  で動的に実行して回答を集める。synthesizer 用のテキストを返す。
- synthesizer (LlmAgent, ツールなし): 各ドメインの回答を統合して最終回答を作る (terminal → workflow 出力)。
- ドメインノード: make_domain_subagent(domain) を流用 (multi の sub-agent と同一文言 = 委譲機構だけが
  差、の統制を graph にも拡張)。全ノードが make_model()/make_generate_config() 経由 (iso-thinking-level)。

**API 調整の理由 (ソース検証済み)**: 当初の「planner → 条件エッジ → ドメインノード群 → JoinNode」構成は
ADK 2.4.0 では成立しない — JoinNode は _requires_all_predecessors=True で **全**静的前任者の COMPLETED を
待つ (_workflow.py _buffer_downstream_triggers)。条件ルーティングで選ばれなかったドメインノードは
起動されず COMPLETED に到達しないため join が **deadlock** する。よって条件選択を dispatcher
(ctx.run_node による動的ディスパッチ; _validate_no_task_mode_graph_nodes の docstring が推奨する方式) に
移し、線形 spine で fan-in の deadlock を回避した。トポロジ (planner→domain 群→統合) は保持している。

計測: MetricsPlugin は同一 Runner 内で動くドメインノードにも発火する (追加配線不要)。record の
``delegations`` は graph では空になる (AgentTool/transfer 呼び出しが無いため) — ルーティングは実ツール
呼び出しのドメイン (bq_query 等) で観測する。
"""

from __future__ import annotations

from google.adk import Workflow
from google.adk.agents import Agent
from google.adk.workflow import START, Edge, FunctionNode
from pydantic import BaseModel

from ..environments import ordered_domains
from ..model import make_generate_config, make_model
from .common import DOMAIN_DESCRIPTIONS, OPEN_MANDATE, PERSONA, make_domain_subagent

NAME = "workflow_graph"


class _Plan(BaseModel):
    """planner の構造化出力。"""

    question: str  # ユーザーの質問をそのまま echo (下流ノードが参照する)
    domains: list[str]  # 回答に必要なドメイン集合 (空 = irrelevance)


def _domain_agents(env: str, seed: int | None = None) -> dict:
    """env に存在するドメインの専門ノードを構築する (multi の sub-agent と同一構成)。"""
    return {d: make_domain_subagent(d) for d in ordered_domains(env, seed)}


def _planner(available: str) -> Agent:
    instruction = (
        f"{PERSONA}\n\n"
        "あなたはルーティング担当です。ユーザーの質問に答えるために必要なドメインを判断してください。\n"
        f"利用可能なドメイン:\n{available}\n\n"
        "question にはユーザーの質問をそのまま入れてください。domains には回答に必要なドメイン名だけを"
        "列挙してください (複数可)。どのドメインのデータでも答えられない質問なら domains は空リストに"
        "してください。"
    )
    return Agent(
        name="planner",
        model=make_model(),
        description="Routing planner: selects the domains needed to answer the question.",
        instruction=instruction,
        output_schema=_Plan,
        generate_content_config=make_generate_config(),
    )


def _synthesizer() -> Agent:
    instruction = (
        f"{PERSONA}\n\n{OPEN_MANDATE}\n\n"
        "各ドメイン専門ノードの回答が与えられます。それらを統合してユーザーの質問への最終回答を"
        "簡潔に作ってください。ドメインからの情報が無い/不足している場合は、その旨を正直に述べ、"
        "データが無いことを数値や固有名で捏造しないでください。"
    )
    return Agent(
        name="synthesizer",
        model=make_model(),
        description="Synthesizer: merges domain answers into the final response.",
        instruction=instruction,
        generate_content_config=make_generate_config(),
    )


def build(env: str, seed: int | None = None) -> Workflow:
    agents = _domain_agents(env, seed)
    available = "\n".join(f"- {d}: {DOMAIN_DESCRIPTIONS[d]}" for d in agents)

    async def _dispatch(ctx, node_input):
        """plan に従い選ばれたドメインノードを動的実行し、synthesizer 用テキストを返す。"""
        if isinstance(node_input, _Plan):
            question, wanted = node_input.question, node_input.domains
        elif isinstance(node_input, dict):
            question, wanted = node_input.get("question", ""), node_input.get("domains", [])
        else:
            question, wanted = str(node_input), []
        selected = [d for d in wanted if d in agents]  # 幻覚した不在ドメインは除外
        parts = []
        for d in selected:
            answer = await ctx.run_node(agents[d], node_input=question)
            parts.append(f"[{d}]\n{answer}")
        body = "\n\n".join(parts) if parts else "(利用可能なドメインからは該当する情報が得られませんでした)"
        return f"ユーザーの質問:\n{question}\n\n各ドメイン専門ノードの回答:\n{body}"

    dispatcher = FunctionNode(func=_dispatch, name="dispatcher")
    planner, synthesizer = _planner(available), _synthesizer()
    return Workflow(
        name=NAME,
        edges=[
            Edge(from_node=START, to_node=planner),
            Edge(from_node=planner, to_node=dispatcher),
            Edge(from_node=dispatcher, to_node=synthesizer),
        ],
    )
