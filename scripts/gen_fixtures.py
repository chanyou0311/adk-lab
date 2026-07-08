"""決定的な fixture 生成 (固定 seed=42)。

架空のオンラインストア、期間 2026-06-01〜06-30 のデータを生成する:
- warehouse/orders.csv            : 注文レコード (6/24-26 に売上落ち込み、6/15 に負荷試験注文 10 件)
- warehouse/daily_active_users.csv: 日次アクティブユーザー
- slack_data.json                 : #general/#alerts/#support/#releases のメッセージ

生成物は src/lab/fixtures/ に書き出し、リポジトリに commit する (再現性・ブログ引用のため)。
seed 固定なので何度実行しても同一出力になる。

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

    print(f"orders.csv: {len(orders)} rows")
    print(f"daily_active_users.csv: {len(dau)} rows")
    print(f"slack_data.json: {len(slack['messages'])} messages across {len(slack['channels'])} channels")


if __name__ == "__main__":
    main()
