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


class _DomainQuery(BaseModel):
    """ドメインへの委譲 1 件 (対象ドメイン + そのドメインだけで完結するサブクエリ)。"""

    domain: str
    subquery: str


class _Plan(BaseModel):
    """planner の構造化出力。

    queries のサブクエリは**そのドメインの道具だけで答えられる自己完結の依頼文**にする。
    質問全文を各ノードへ配ると、隔離ノードが質問の越境部分に反応して他ドメインのツールを
    幻覚し、ADK の `Tool '...' not found` ハードクラッシュを踏む (graph ジョブの 19% が
    クロスドメインタスクで系統的にクラッシュした _main2 初回収集で実証)。multi 系の
    coordinator が会話的に「狭い依頼文」を作るのと同じ役割を、graph では planner が担う。
    """

    question: str  # ユーザーの質問をそのまま echo (synthesizer が参照する)
    queries: list[_DomainQuery]  # 回答に必要なドメインへの委譲 (空 = irrelevance)


def _domain_agents(env: str, seed: int | None = None) -> dict:
    """env に存在するドメインの専門ノードを構築する (multi の sub-agent と完全に同一構成)。

    rerun_on_resume は不要 (multi と同素材)。ctx.run_node の検査は **呼び出し元 (dispatcher) の
    Context** に対して行われるため、rerun_on_resume=True が必要なのは dispatcher 側 (build 参照)。
    """
    return {d: make_domain_subagent(d) for d in ordered_domains(env, seed)}


def _planner(available: str) -> Agent:
    instruction = (
        f"{PERSONA}\n\n"
        "あなたはルーティング担当です。ユーザーの質問に答えるために必要なドメインを判断し、"
        "各ドメインへの依頼文 (サブクエリ) に分解してください。\n"
        f"利用可能なドメイン:\n{available}\n\n"
        "question にはユーザーの質問をそのまま入れてください。queries には回答に必要なドメインごとに "
        "{domain, subquery} を列挙してください (複数可)。**subquery はそのドメインのデータだけで"
        "答えられる自己完結の依頼文にすること** — 他ドメインに属する部分を混ぜないでください "
        "(例: 売上の集計は bq へ、障害報告の検索は slack へ、と分けて依頼する)。"
        "どのドメインのデータでも答えられない質問なら queries は空リストにしてください。"
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
        """plan に従い選ばれたドメインノードへサブクエリを動的実行し、synthesizer 用テキストを返す。

        各ノードには質問全文でなく **そのドメイン向けサブクエリだけ** を渡す — 全文を配ると隔離
        ノードが越境部分に反応して他ドメインのツールを幻覚し、ADK のハードクラッシュを踏む
        (_Plan docstring 参照)。subquery が空の場合のみ質問全文にフォールバックする。
        """
        if isinstance(node_input, _Plan):
            question, queries = node_input.question, node_input.queries
        elif isinstance(node_input, dict):
            question = node_input.get("question", "")
            # planner の崩れた出力 (想定外キー/型) で workflow ごと落とさない — 欠損キー耐性で
            # 読める要素だけ拾う (domain 空は下の not in agents で除外される)。
            queries = [q if isinstance(q, _DomainQuery)
                       else _DomainQuery(domain=str(q.get("domain", "")),
                                         subquery=str(q.get("subquery", "")))
                       for q in node_input.get("queries", [])
                       if isinstance(q, (dict, _DomainQuery))]
        else:
            question, queries = str(node_input), []
        parts = []
        for q in queries:
            if q.domain not in agents:  # 幻覚した不在ドメインは除外
                continue
            answer = await ctx.run_node(agents[q.domain], node_input=q.subquery or question)
            parts.append(f"[{q.domain}]\n{answer}")
        body = "\n\n".join(parts) if parts else "(利用可能なドメインからは該当する情報が得られませんでした)"
        return f"ユーザーの質問:\n{question}\n\n各ドメイン専門ノードの回答:\n{body}"

    # dispatcher は ctx.run_node で子ノードを動的スケジュールする。context._run_node_internal は
    # **呼び出し元 (= dispatcher) の Context の rerun_on_resume** を検査する (context.py 207/503:
    # self._node_rerun_on_resume は「その Context を所有するノード」= dispatcher の値)。子が interrupt
    # されると親 (dispatcher) が再実行されて子の応答を回収するため、dispatcher が rerun_on_resume=True
    # でないと ValueError になる (FunctionNode の既定は False)。
    dispatcher = FunctionNode(func=_dispatch, name="dispatcher", rerun_on_resume=True)
    planner, synthesizer = _planner(available), _synthesizer()
    return Workflow(
        name=NAME,
        edges=[
            Edge(from_node=START, to_node=planner),
            Edge(from_node=planner, to_node=dispatcher),
            Edge(from_node=dispatcher, to_node=synthesizer),
        ],
    )
