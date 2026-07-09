"""決定的な fixture 生成 (固定 seed=42)。

架空のオンラインストア、期間 2026-06-01〜06-30 のデータを生成する:
- warehouse/orders.csv            : 注文レコード (6/24-26 に売上落ち込み、6/15 に負荷試験注文 10 件)
- warehouse/daily_active_users.csv: 日次アクティブユーザー
- warehouse/support_tickets.csv   : サポートチケット (初回応答 SLA 用、独立 rng SEED+1)
- slack_data.json                 : #general/#alerts/#support/#releases のメッセージ
- billing_data.json               : 決済ドメイン (charges/invoices/refunds、独立 rng SEED+2)
- oncall_data.json                : 当番ドメイン (schedules/shifts/assignments、独立 rng SEED+3)
- portal_data.json                : portal distractor (reports/datasets/archive/digests/groups、独立 rng SEED+4)

生成物は src/lab/fixtures/ に書き出し、リポジトリに commit する (実験の再現性のため)。
各ドメインは **独立した rng** (`random.Random(SEED + n)`) を使い、既存 fixture の生成列を一切
乱さない (既存生成物のバイト不変を保証する)。seed 固定なので何度実行しても同一出力になる。

Usage:  uv run python scripts/gen_fixtures.py
"""

from __future__ import annotations

import csv
import datetime
import json
import random
from pathlib import Path

SEED = 42
FIXTURES = Path(__file__).resolve().parent.parent / "src" / "lab" / "fixtures"
WAREHOUSE = FIXTURES / "warehouse"

START = datetime.date(2026, 6, 1)
DAYS = 30
DIP_DAYS = {datetime.date(2026, 6, 24), datetime.date(2026, 6, 25), datetime.date(2026, 6, 26)}
LOAD_TEST_DAY = datetime.date(2026, 6, 15)

USERS = ["haruka", "kenji", "mio", "satoshi", "yui", "takumi", "rin", "daiki"]


def _dates() -> list[datetime.date]:
    return [START + datetime.timedelta(days=i) for i in range(DAYS)]


def gen_orders(rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    seq = 1
    for day in _dates():
        n = rng.randint(3, 5) if day in DIP_DAYS else rng.randint(15, 20)
        for _ in range(n):
            status = "cancelled" if rng.random() < 0.05 else "completed"
            rows.append(
                {
                    "order_id": f"ORD-{seq:05d}",
                    "order_date": day.isoformat(),
                    "amount": rng.randint(3000, 30000),
                    "status": status,
                    "is_test": "false",
                    "channel": rng.choice(["web", "app"]),
                }
            )
            seq += 1
        if day == LOAD_TEST_DAY:
            # 負荷試験の注文 10 件。amount が桁違いに大きく、is_test で除外しないと合計を歪める。
            for _ in range(10):
                rows.append(
                    {
                        "order_id": f"ORD-{seq:05d}",
                        "order_date": day.isoformat(),
                        "amount": rng.randint(500_000, 1_000_000),
                        "status": "completed",
                        "is_test": "true",
                        "channel": "app",
                    }
                )
                seq += 1
    return rows


def gen_dau(rng: random.Random) -> list[dict]:
    rows = []
    for day in _dates():
        dau = rng.randint(950, 1050) if day in DIP_DAYS else rng.randint(1150, 1250)
        rows.append({"date": day.isoformat(), "dau": dau})
    return rows


def gen_support_tickets(rng: random.Random) -> list[dict]:
    """UC3 (support-sla) 用のサポートチケット。

    全チケットに first_response_at を入れ、SLA 違反を「応答レイテンシ」だけで決定的に定める
    (「現在時刻」に依存させない)。SLA: pro=4h / それ以外=24h、ただし支払い関連 (subject に
    決済/課金/返金) は plan に関わらず 4h (K7/K8)。違反は下記 6 件の explicit ticket に限定し、
    filler 24 件は全て compliant にする (違反件数を 6 に固定)。既存 fixture を乱さないよう
    呼び出し側は専用の rng (Random(SEED+1)) を渡す。
    """
    subjects_nonpay = [
        "画像がアップロードできない",
        "検索結果が表示されない",
        "ログインできない",
        "注文履歴が見られない",
        "クーポンが適用されない",
        "配送状況が分からない",
    ]

    tickets: list[dict] = []

    def add(day: int, hh: int, plan: str, subject: str, latency_h: float) -> None:
        opened = datetime.datetime(2026, 6, day, hh, rng.randint(0, 59))
        resp = opened + datetime.timedelta(hours=latency_h)
        tickets.append(
            {"opened_at": opened, "first_response_at": resp, "plan": plan, "subject": subject}
        )

    # --- explicit な違反 6 件 (pro 非支払い×2 / basic 非支払い×1 / 支払い override×3) ---
    add(24, 9, "pro", "ログインできない", 6)  # pro 4h 超過
    add(25, 10, "pro", "画像がアップロードできない", 5.5)  # pro 4h 超過
    add(26, 8, "basic", "検索結果が表示されない", 30)  # basic 24h 超過
    add(27, 11, "basic", "決済でエラーになる", 8)  # 支払い override (basic だが 4h 超過)
    add(28, 14, "basic", "二重に課金された", 6)  # 支払い override (課金 → 4h 超過)
    add(29, 9, "pro", "返金がまだ反映されない", 7)  # pro かつ支払い (4h 超過)

    # --- compliant な filler 24 件 (非支払い・SLA 内に収まるレイテンシ) ---
    for _ in range(24):
        day = rng.randint(24, 30)
        plan = rng.choice(["pro", "basic"])
        subject = rng.choice(subjects_nonpay)
        latency = round(rng.uniform(0.3, 3.5), 1) if plan == "pro" else round(rng.uniform(4.5, 20.0), 1)
        add(day, rng.randint(8, 18), plan, subject, latency)

    tickets.sort(key=lambda t: t["opened_at"])
    rows = []
    for i, t in enumerate(tickets, 1):
        rows.append(
            {
                "ticket_id": f"TCK-{i:04d}",
                "opened_at": t["opened_at"].isoformat(sep=" "),
                "first_response_at": t["first_response_at"].isoformat(sep=" "),
                "plan": t["plan"],
                "subject": t["subject"],
            }
        )
    return rows


def _ts(day: datetime.date, hh: int, mm: int) -> str:
    return f"{day.isoformat()}T{hh:02d}:{mm:02d}:00+09:00"


def gen_slack(rng: random.Random) -> dict:
    channels = ["general", "alerts", "support", "releases"]
    messages: list[dict] = []

    def add(channel: str, day: datetime.date, hh: int, mm: int, user: str, text: str) -> None:
        messages.append(
            {"channel": channel, "ts": _ts(day, hh, mm), "user": user, "text": text}
        )

    d = datetime.date

    # --- #releases: 必須のリリース + 通常メッセージ ---
    add("releases", d(2026, 6, 24), 9, 30, "takumi", "v2.4.0 をデプロイしました (決済モジュール刷新)")
    add("releases", d(2026, 6, 3), 10, 0, "takumi", "v2.3.8 をデプロイしました (軽微なバグ修正)")
    add("releases", d(2026, 6, 12), 11, 0, "rin", "v2.3.9 をデプロイしました (検索の高速化)")
    add("releases", d(2026, 6, 26), 16, 0, "takumi", "v2.4.1 をデプロイしました (INC-42 対応・決済モジュールをロールバック)")

    # --- #alerts: 必須の INC 系 (K4: [INC-n] が正式、クローズ報なし=未解決) ---
    add("alerts", d(2026, 6, 24), 11, 0, "kenji", "[INC-42][sev1] チェックアウトで決済が失敗する障害が発生。調査中")
    add("alerts", d(2026, 6, 25), 10, 0, "kenji", "[INC-42] 原因を v2.4.0 の決済モジュール刷新と特定。修正版を準備中")
    add("alerts", d(2026, 6, 26), 15, 0, "kenji", "[INC-42] v2.4.1 ロールバックで解消。クローズ")
    add("alerts", d(2026, 6, 29), 9, 0, "mio", "[INC-43][sev1] 商品画像のアップロードが失敗する障害。未解決・調査中")
    add("alerts", d(2026, 6, 30), 10, 0, "satoshi", "[INC-44][sev2] 社内管理画面の表示が遅い。未解決")

    # --- #support: 6 月後半の顧客苦情 (7 件、決済エラー/返金/画像アップロード/遅い のキーワードを含む) ---
    add("support", d(2026, 6, 24), 12, 10, "customer", "決済でエラーが出て注文できません。決済エラーの対応をお願いします")
    add("support", d(2026, 6, 24), 18, 40, "customer", "チェックアウトが失敗して購入できない。決済エラーが出ます")
    add("support", d(2026, 6, 25), 9, 20, "customer", "二重に課金されたので返金してほしいです。返金依頼します")
    add("support", d(2026, 6, 26), 14, 0, "customer", "キャンセルした注文の返金がまだ反映されません")
    add("support", d(2026, 6, 28), 20, 30, "customer", "最近サイトの動作が遅いと感じます。表示が遅いです")
    add("support", d(2026, 6, 29), 10, 15, "customer", "商品画像のアップロードができません。画像アップロード不可の状態です")
    add("support", d(2026, 6, 30), 11, 45, "customer", "管理画面の表示がとても遅い。動作が遅くて業務に支障があります")

    # --- 各チャンネルに雑談・通常メッセージを散らす (ノイズ。[INC-n] を持たないので K4 で区別可能) ---
    chit_chat = {
        "general": [
            "おはようございます", "今日のランチどこにします?", "会議室 A を 14 時に予約しました",
            "リモートの人はスタンドアップ Zoom で", "コーヒー淹れました", "週報のテンプレ更新しました",
            "お疲れさまでした", "明日は祝日ではないので通常出社です", "新しいメンバーが来週入社します",
            "社内 Wiki を整理しました", "歓迎会の日程を調整中です", "エアコンの温度下げました",
            "ドキュメントのレビューお願いします", "議事録を共有しました", "来月の OKR を詰めましょう",
            "デザインレビューは木曜です", "ノベルティ届きました", "備品の発注しておきます",
            "スプリントプランニングは月曜", "振り返りの付箋用意しました",
        ],
        "alerts": [
            "本番の CPU 使用率は正常範囲です", "夜間バッチ正常終了", "監視ダッシュボード更新しました",
            "証明書の有効期限は問題なし", "バックアップ完了しました", "デプロイパイプライン正常",
            "ディスク使用率 60%、問題なし", "外形監視 all green", "DB レプリケーション遅延なし",
            "キャッシュヒット率良好", "ロードバランサ正常", "アラートのしきい値を見直しました",
            "定期メンテナンスは日曜深夜です", "ログ基盤の retention を調整", "Synthetic monitor 追加しました",
            "オンコール担当は今週 kenji", "メトリクスの取りこぼしなし", "SLO は達成しています",
            "ネットワーク遅延は平常", "監視エージェントを更新しました",
        ],
        "support": [
            "問い合わせ対応ありがとうございます", "FAQ を更新しました", "テンプレ返信を整備中",
            "満足度アンケートの結果共有します", "対応時間の目標は 24 時間以内", "エスカレーション基準を確認",
            "ナレッジベースに追記しました", "今日の問い合わせ件数は平常", "電話対応のマニュアル更新",
            "チャットボットの回答を改善", "返信の言い回しを統一しました", "休日対応の当番表を共有",
            "顧客からお礼のメッセージ来ました", "対応漏れゼロでした", "サポートツールを更新",
            "月次レポートを作成中", "問い合わせタグを整理", "対応品質のレビュー会は金曜",
            "新人向けオンボ資料を用意", "よくある質問を追加しました",
        ],
        "releases": [
            "次のリリースは来週水曜予定", "リリースノートのドラフト共有します", "フィーチャーフラグを整理",
            "カナリアリリースは順調", "ステージング検証 OK", "リグレッションテスト通過",
            "リリース手順書を更新しました", "ロールバック手順を確認済み", "変更点のサマリを作成",
            "デプロイ枠は平日午前中", "ホットフィックスの運用を整理", "バージョン命名規則を確認",
            "依存ライブラリを更新しました", "マイグレーションは後方互換", "リリース後の監視強化します",
            "ドキュメント同時更新を徹底", "チェンジログ公開しました", "次スプリントの目玉機能を検討",
            "QA サインオフ取得済み", "リリース連絡テンプレ整備",
        ],
    }
    for ch, texts in chit_chat.items():
        for text in texts:
            day = START + datetime.timedelta(days=rng.randint(0, DAYS - 1))
            add(ch, day, rng.randint(9, 19), rng.randint(0, 59), rng.choice(USERS), text)

    messages.sort(key=lambda m: m["ts"])
    return {"channels": channels, "messages": messages}


# --------------------------------------------------------------------------- #
# billing (決済) ドメイン — 独立 rng (SEED+2)
# --------------------------------------------------------------------------- #
_BILLING_SKUS = ["SKU-standard", "SKU-premium", "SKU-addon", "SKU-shipping"]
_REFUND_REASON_INCIDENT = [
    "チェックアウトの決済失敗による返金",
    "二重課金の返金 (決済エラー)",
    "決済エラーに伴う注文キャンセルの返金",
]
_REFUND_REASON_NORMAL = [
    "顧客都合のキャンセルによる返金",
    "商品不備による返金",
]


def gen_billing(rng: random.Random) -> dict:
    """billing (決済) ドメイン fixture。

    6/24-26 のチェックアウト決済障害 (INC-42) と整合させ、その期間に返金 (refund) が急増する。
    charge は invoice を 1:1 で持ち (get_invoice が引ける)、refund は当日の charge を参照する。
    既存 fixture の乱数列を乱さないよう専用 rng (Random(SEED+2)) を使う。
    """
    charges: list[dict] = []
    invoices: list[dict] = []
    refunds: list[dict] = []
    charges_by_day: dict[str, list[dict]] = {}
    cid = iid = rid = 1

    for day in _dates():
        iso = day.isoformat()
        day_charges: list[dict] = []
        for _ in range(rng.randint(8, 14)):
            items = [
                {"sku": rng.choice(_BILLING_SKUS), "qty": rng.randint(1, 3), "amount": rng.randint(1000, 12000)}
                for _ in range(rng.randint(1, 3))
            ]
            amount = sum(i["amount"] for i in items)
            fail_p = 0.35 if day in DIP_DAYS else 0.03  # 障害期間は決済失敗が増える
            status = "failed" if rng.random() < fail_p else "succeeded"
            invoice_id = f"INV-{iid:05d}"
            charge_id = f"CHG-{cid:05d}"
            customer = f"cust-{rng.randint(1000, 9999)}"
            charge = {
                "charge_id": charge_id, "date": iso, "amount": amount,
                "customer": customer, "status": status, "invoice_id": invoice_id,
            }
            charges.append(charge)
            day_charges.append(charge)
            invoices.append({
                "invoice_id": invoice_id, "date": iso, "customer": customer,
                "line_items": items, "total": amount,
                "status": "paid" if status == "succeeded" else "unpaid",
            })
            cid += 1
            iid += 1
        charges_by_day[iso] = day_charges

    for day in _dates():
        iso = day.isoformat()
        if day in DIP_DAYS:
            n_ref = rng.randint(5, 8)  # 決済障害でチェックアウト失敗 → 返金が急増
            reasons = _REFUND_REASON_INCIDENT
        else:
            n_ref = 1 if rng.random() < 0.25 else 0
            reasons = _REFUND_REASON_NORMAL
        pool = charges_by_day[iso]
        for _ in range(n_ref):
            base = rng.choice(pool) if pool else None
            refunds.append({
                "refund_id": f"RFN-{rid:04d}", "date": iso,
                "amount": base["amount"] if base else rng.randint(2000, 20000),
                "charge_id": base["charge_id"] if base else None,
                "reason": rng.choice(reasons),
            })
            rid += 1

    return {"charges": charges, "invoices": invoices, "refunds": refunds}


# --------------------------------------------------------------------------- #
# oncall (当番) ドメイン — 独立 rng (SEED+3)
# --------------------------------------------------------------------------- #
def gen_oncall(rng: random.Random) -> dict:
    """oncall (当番) ドメイン fixture。

    INC-42/43/44 の対応担当を slack の #alerts 投稿者と整合させる (kenji=INC-42, mio=INC-43,
    satoshi=INC-44)。日次シフトは週替わりローテーション、引き継ぎ時刻だけ rng で軽く揺らす。
    既存 fixture を乱さないよう専用 rng (Random(SEED+3)) を使う。
    """
    schedules = [
        {"schedule_id": "SCH-primary", "name": "Primary On-call", "rotation": ["kenji", "mio", "satoshi", "takumi"]},
        {"schedule_id": "SCH-secondary", "name": "Secondary On-call", "rotation": ["haruka", "yui", "rin", "daiki"]},
    ]
    shifts: list[dict] = []
    for i, day in enumerate(_dates()):
        week = i // 7
        handoff = rng.randint(9, 11)  # 引き継ぎ時刻 (seed 由来の軽い揺らぎ)
        for sch in schedules:
            rot = sch["rotation"]
            shifts.append({
                "date": day.isoformat(),
                "schedule_id": sch["schedule_id"],
                "role": "primary" if sch["schedule_id"] == "SCH-primary" else "secondary",
                "user": rot[week % len(rot)],
                "handoff_hour": handoff,
            })
    assignments = [
        {"incident_id": "INC-42", "severity": "sev1", "start": "2026-06-24", "end": "2026-06-26",
         "responders": [{"user": "kenji", "role": "incident_commander"}, {"user": "takumi", "role": "engineer"}]},
        {"incident_id": "INC-43", "severity": "sev1", "start": "2026-06-29", "end": None,
         "responders": [{"user": "mio", "role": "incident_commander"}]},
        {"incident_id": "INC-44", "severity": "sev2", "start": "2026-06-30", "end": None,
         "responders": [{"user": "satoshi", "role": "engineer"}]},
    ]
    return {"schedules": schedules, "shifts": shifts, "assignments": assignments}


# --------------------------------------------------------------------------- #
# portal (社内ポータル) distractor — 独立 rng (SEED+4)、レポート値は orders から導出
# --------------------------------------------------------------------------- #
_PORTAL_ARCHIVE_TEXTS = [
    "5月の定例会議の議事録を共有します",
    "先月のリリース v2.3.5 の振り返り",
    "GW 期間中の当番表について",
    "5月の売上速報を共有しました",
    "旧デザインのフィードバックまとめ",
    "先月のインフラ費用レポート",
    "5月のサポート問い合わせ傾向",
    "四半期 OKR の中間レビュー",
]


def gen_portal(rng: random.Random, orders: list[dict]) -> dict:
    """portal (社内ポータル) の near-synonym distractor fixture。

    gold ツール (bq/slack) と紛らわしいが、返すデータのスコープが微妙に違う「もっともらしく
    不完全」な値。特に reports の revenue は除外ルール (テスト/キャンセル) を適用しない naive な
    集計値で、bq_query の正解値と異なる (distractor が実際に罠として機能する前提)。
    レポート値は生成済み orders から導出し、それ以外の揺らぎに専用 rng (Random(SEED+4)) を使う。
    """
    # naive 集計: テストアカウント・キャンセル注文を除外しない (K1/K3 違反の値 = 全注文合計)。
    naive_revenue = sum(o["amount"] for o in orders)
    reports = {
        "revenue|2026-06": {"metric": "revenue", "period": "2026-06", "value": naive_revenue,
                            "note": "全注文の売上合計 (テスト/キャンセル含む簡易集計)"},
        "orders|2026-06": {"metric": "orders", "period": "2026-06", "value": len(orders),
                           "note": "全注文件数 (テスト/キャンセル含む)"},
    }
    # 古い列定義 (現テーブルと不一致: is_test/status/channel が無く customer_id がある)。
    datasets = {
        "orders": {"name": "orders", "description": "注文データ (データカタログ / 四半期更新)",
                   "columns": ["order_id", "order_date", "amount", "customer_id"]},
        "sales_summary": {"name": "sales_summary", "description": "日次売上サマリ (集計済み)",
                          "columns": ["date", "gross_sales", "order_count"]},
    }
    # bq_query では引けない論理データセット名 (現テーブル名 orders/daily_active_users とは別)。
    dataset_list = ["sales_summary", "orders_daily_rollup", "finance_orders_v1", "dau_weekly"]
    # アーカイブ検索対象は 30 日より古い (= 6 月のインシデントは漏れる) メッセージのみ。
    channels = ["general", "alerts", "support", "releases"]
    archive = [
        {"date": datetime.date(2026, 5, rng.randint(1, 28)).isoformat(),
         "channel": rng.choice(channels), "text": txt}
        for txt in _PORTAL_ARCHIVE_TEXTS
    ]
    archive.sort(key=lambda m: m["date"])
    # 日次ダイジェスト: 個別メッセージ・INC 番号などの詳細が落ちた要約。
    digests = {
        "alerts": "6月下旬に決済関連の障害とアップロードの不具合が発生し、対応を行いました。詳細は各インシデントレポートを参照してください。",
        "support": "6月後半は決済エラー・返金・表示速度に関する問い合わせが中心でした。",
        "releases": "6月は v2.4 系のリリースとロールバックを実施しました。",
        "general": "通常の運用連絡・雑談が中心でした。",
    }
    # チャンネルではなくユーザーグループ (メンション用)。
    groups = [
        {"name": "@engineering", "members": ["kenji", "mio", "takumi", "rin"]},
        {"name": "@support", "members": ["haruka", "yui"]},
        {"name": "@oncall-primary", "members": ["kenji", "mio", "satoshi", "takumi"]},
    ]
    return {"reports": reports, "datasets": datasets, "dataset_list": dataset_list,
            "archive": archive, "digests": digests, "groups": groups}


def main() -> None:
    WAREHOUSE.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    orders = gen_orders(rng)
    with (WAREHOUSE / "orders.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["order_id", "order_date", "amount", "status", "is_test", "channel"])
        w.writeheader()
        w.writerows(orders)

    dau = gen_dau(rng)
    with (WAREHOUSE / "daily_active_users.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "dau"])
        w.writeheader()
        w.writerows(dau)

    slack = gen_slack(rng)
    (FIXTURES / "slack_data.json").write_text(
        json.dumps(slack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # UC3: 既存 fixture の乱数列を乱さないよう独立 rng (SEED+1) を使う。
    tickets = gen_support_tickets(random.Random(SEED + 1))
    with (WAREHOUSE / "support_tickets.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["ticket_id", "opened_at", "first_response_at", "plan", "subject"]
        )
        w.writeheader()
        w.writerows(tickets)

    # 追加ドメイン (agent-composition の tool-overload / confusability 用)。各々独立 rng を使い、
    # 上記の既存 fixture を一切乱さない。portal のレポート値は orders から導出する。
    billing = gen_billing(random.Random(SEED + 2))
    (FIXTURES / "billing_data.json").write_text(
        json.dumps(billing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    oncall = gen_oncall(random.Random(SEED + 3))
    (FIXTURES / "oncall_data.json").write_text(
        json.dumps(oncall, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    portal = gen_portal(random.Random(SEED + 4), orders)
    (FIXTURES / "portal_data.json").write_text(
        json.dumps(portal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"orders.csv: {len(orders)} rows")
    print(f"daily_active_users.csv: {len(dau)} rows")
    print(f"slack_data.json: {len(slack['messages'])} messages across {len(slack['channels'])} channels")
    print(f"support_tickets.csv: {len(tickets)} rows")
    print(f"billing_data.json: {len(billing['charges'])} charges / {len(billing['invoices'])} invoices / {len(billing['refunds'])} refunds")
    print(f"oncall_data.json: {len(oncall['schedules'])} schedules / {len(oncall['shifts'])} shifts / {len(oncall['assignments'])} assignments")
    print(f"portal_data.json: {len(portal['reports'])} reports / {len(portal['archive'])} archive msgs / {len(portal['groups'])} groups")


if __name__ == "__main__":
    main()
