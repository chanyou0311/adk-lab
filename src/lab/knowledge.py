"""ドメイン知識の単一定義。

全バリアントはこの ``KNOWLEDGE`` から知識を引く。配置場所 (root instruction / tool docstring /
sub-agent instruction / SKILL 本文) だけを変え、知識の *中身* は 1 箇所で管理して統制する。
"""

from __future__ import annotations

KNOWLEDGE: dict[str, dict[str, str]] = {
    "sales-analytics": {
        "name": "sales-analytics",
        "description": "売上・注文データ (data warehouse) を正しく集計するための社内ルール",
        "body": """\
K1: 売上 (revenue) の集計では is_test = true の行を必ず除外する。負荷試験の注文が
    混在しており、除外しないと合計が大きく歪む。
K2: amount は税込 JPY。「純売上」(net sales) を求められたら amount / 1.1 で税抜換算する
    (消費税 10%)。
K3: status = 'cancelled' の注文は売上に含めない (completed のみを売上として数える)。""",
    },
    "slack-ops": {
        "name": "slack-ops",
        "description": "社内 Slack の運用規約 (障害・リリース・顧客の声の在り処と読み方)",
        "body": """\
K4: 障害の正式な情報源は #alerts チャンネルの [INC-n] プレフィックス付きメッセージ。
    クローズ報 (解消・ロールバック等) が無い INC は未解決とみなす。
K5: severity の解釈: sev1 = 顧客影響あり (即対応要)、sev2 = 内部影響のみ。
K6: リリース情報は #releases、顧客の生の声・苦情は #support にある。""",
    },
}


def knowledge_block() -> str:
    """fat バリアントが root instruction に埋め込む、2 ブロック全文のテキスト。"""
    parts = []
    for k in KNOWLEDGE.values():
        parts.append(f"## {k['name']} — {k['description']}\n{k['body']}")
    return "\n\n".join(parts)
