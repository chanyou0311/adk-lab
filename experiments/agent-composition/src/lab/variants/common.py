"""バリアント共通の instruction 部品。

知識の *配置* を変える実験なので、instruction の共有骨格 (PERSONA / 役割指示) はここに 1 本化し、
各バリアントで同期させる。役割の与え方には 2 系統ある:
- OPEN_MANDATE (役割指示): 「ツールは取得、分析・予測は自分の仕事」と明示する。
- CLOSED_ENUMERATION: できることをツール用途の列挙で閉じる (役割指示なし)。
どちらを使うかと知識配置は別変数なので、fat_closed / fat_open で交絡を分離する。
"""

from __future__ import annotations

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

# 閉じた列挙。ツールの用途を並べるだけで、役割指示を意図的に持たない。
CLOSED_ENUMERATION = (
    "You can use the bq tools to look up sales and order data (totals and breakdowns), and "
    "the slack tools to read team communication (incident notices, support inquiries, "
    "release notes)."
)

# subagents バリアントの root に置くルーティング指針。
ROUTING_GUIDANCE = (
    "Use data_analyst for warehouse/sales questions, comms_analyst for Slack/incident "
    "questions; for cross-domain questions call both and synthesize yourself."
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
