"""バリアント共通の instruction 部品と sub-agent ファクトリ。

役割文言 (PERSONA / OPEN_MANDATE) をここに 1 本化し、全バリアント・全 sub-agent で同期させる
(役割の与え方を統制する)。multi_* の sub-agent 構築も make_domain_subagent に 1 本化する。
"""

from __future__ import annotations

from google.adk.agents import Agent

from ..environments import make_domain_tools
from ..model import make_generate_config, make_model
from ..naming import subagent_name

# ~3 文。トーン・言語・データ接地の指針。全バリアント共通。
PERSONA = (
    "You are a data assistant for an online store team. Be concise and answer in the "
    "user's language (Japanese). Ground your answers in data you retrieve with your tools "
    "when the question concerns the store's business."
)

# 役割指示 (OPEN_MANDATE)。ツール=取得、分析/予測/比較はエージェント自身の仕事、と明示する。ツール用途の
# 列挙だけだと、モデルが列挙を能力の枠と解釈して分析・予測系の依頼を「対応する機能がない」と
# 過剰拒否することがあり、それを防ぐ。ドメイン非依存。
OPEN_MANDATE = (
    "Your tools FETCH data for you — for example sales and order records from the data "
    "warehouse, and messages from the team's Slack. Performing analysis, summarization, "
    "trend detection, comparison, and forward-looking estimates or forecasts ON the data "
    "you have is YOUR OWN job and needs no dedicated tool. When the user asks for any of "
    "these, reason over the available data and answer; do not claim a capability is missing "
    "just because no tool matches the task, and do not push the calculation back to the "
    "user. For estimates and forecasts, briefly state your method and key assumptions and "
    "label the result as an estimate, not a guarantee. If data is insufficient, state your "
    "assumptions and give a best-effort bounded estimate rather than refusing."
)

# subagents の各スペシャリストが持つ短いロール文 (呼び出し元=root に簡潔に答える)。
SUBAGENT_PERSONA = (
    "You are a specialist sub-agent for an online store team. Answer the caller's question "
    "concisely in Japanese, grounding every answer in data you fetch with your tools."
)

# multi_* (AgentTool / transfer) の root に置く汎用ルーティング指針。ドメイン別 sub-agent の
# description を頼りに委譲させる。ROUTING_GUIDANCE (data_analyst/comms_analyst 固有) と違い
# ドメイン非依存。
MULTI_ROUTING_GUIDANCE = (
    "You have specialist sub-agents, one per domain. Delegate each question to the sub-agent "
    "whose domain fits it. For cross-domain questions, consult multiple sub-agents and "
    "synthesize the answer yourself. Do not answer data questions without consulting the "
    "relevant specialist."
)

# ドメイン別の説明 (single_skills の Skill frontmatter description と multi_* の sub-agent
# description に共用)。single_skills では list_skills / load_skill の判断材料、multi_* では
# ルーティングの判断材料になる。portal は gold (bq/slack) と語彙を重ねて confusable にする
# — 「レポート集計」「カタログで列確認」は bq と、「メッセージ横断検索」「ダイジェスト」は
# slack と被せる (返すデータのスコープが違う罠は各ツールの docstring 側にある)。
DOMAIN_DESCRIPTIONS = {
    "bq": (
        "オンラインストアのデータウェアハウス (注文・売上・DAU などのテーブル) を SQL で照会する。"
        "売上集計・注文件数・カラム構成の確認に使う。"
    ),
    "slack": (
        "社内 Slack のメッセージを読む・横断検索する。#alerts の障害 (INC) 通知、#releases の"
        "リリース、#support の顧客苦情の確認に使う。"
    ),
    "billing": (
        "決済ドメイン (課金 charge・請求書 invoice・返金 refund) のデータを期間指定で照会する。"
    ),
    "oncall": (
        "オンコール当番表・日次シフト・インシデント対応担当を照会する。"
    ),
    "portal": (
        "社内ポータルの横断参照。月次レポートの集計、データカタログでの列確認、過去メッセージの"
        "アーカイブ検索、チャンネルのダイジェスト要約、グループ一覧をまとめて扱う。"
    ),
}


def make_domain_subagent(
    domain: str, mode: str | None = None, rerun_on_resume: bool = False
) -> Agent:
    """ドメイン別スペシャリスト sub-agent を構築する (multi_agenttool / multi_transfer /
    multi_taskmode / workflow_graph で共有)。

    name は naming.subagent_name(domain) を使い、採点側の DELEGATION_NAMES と機構的に一致させる
    (文字列規約の二重定義を避ける)。instruction は SUBAGENT_PERSONA + OPEN_MANDATE で役割文言を
    root と揃える (過剰拒否を抑える)。**素材 (persona/tools/model) はバリアント間で完全に同一で、
    委譲機構だけが差** = 統制。mode は task-mode 委譲用 (single_turn 等)、既定 None は
    AgentTool/transfer 用。rerun_on_resume は workflow_graph が ctx.run_node で **動的スケジュール**
    するノードに必須 (BaseNode の既定 False では context._run_node_internal が ValueError にする —
    動的ノードは interrupt/resume で親から再実行されうるため)。静的委譲では不要 (既定 False)。
    """
    return Agent(
        name=subagent_name(domain),
        model=make_model(),
        description=DOMAIN_DESCRIPTIONS[domain],
        instruction=f"{SUBAGENT_PERSONA}\n\n{OPEN_MANDATE}",
        tools=make_domain_tools(domain),
        mode=mode,
        rerun_on_resume=rerun_on_resume,
        generate_content_config=make_generate_config(),
    )
