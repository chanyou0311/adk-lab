"""タスク定義・GT・採点器のテスト (Vertex 不要・決定的)。

AGENTS.md の採点器規約に従い、正例に加えて gaming 例 (portal の naive 値・誤日付・誤閾値接地・
ヘッジ捏造) と terse-correct 例 (簡潔だが正しい回答) の両側を固定する。trajectory 分類
(trap_hit/trap_fatal/offtask_calls/fabricated/selection) は合成 record で単体検証する。
"""

from __future__ import annotations

from tasks import (  # conftest.py が eval/ を sys.path に追加している
    BQ_TOOLS,
    GT,
    SLACK_TOOLS,
    TASKS,
    TASKS_BY_ID,
    _e1_fabricated,
    _e2_fabricated,
    _states_inability,
    is_refused,
    score_record,
)

_CLEAN = BQ_TOOLS | SLACK_TOOLS


def _check(tid: str, final: str, tc: list[str] | None = None) -> bool:
    task = TASKS_BY_ID[tid]
    return task.check(final, tc or [], GT, is_refused(final))


# --------------------------------------------------------------------------- #
# 構造 / GT 健全性
# --------------------------------------------------------------------------- #
def test_task_set_shape():
    assert len(TASKS) == 16
    from collections import Counter
    assert dict(Counter(t.category for t in TASKS)) == {"A": 4, "B": 4, "C": 4, "D": 2, "E": 2}
    # gold ツールは常に CLEAN の 6 本の範囲 (全環境で同一タスクを走らせるため)。
    for t in TASKS:
        assert t.gold_tools <= _CLEAN, f"{t.id} の gold が CLEAN を超えている"
        assert all(len(p) > 0 for p in t.prompts)
    # D はマルチターン (2 ターン)、E は gold 無し。
    assert all(len(TASKS_BY_ID[d].prompts) == 2 for d in ("D1", "D2"))
    assert TASKS_BY_ID["E1"].gold_tools == frozenset()
    assert TASKS_BY_ID["E2"].gold_tools == frozenset()


def test_gt_derived_from_fixtures():
    # fixture から機械導出した期待値の固定 (commit 済み fixture に対して決定的)。
    assert GT["orders_0610"] == 18
    assert GT["max_dau"] == 1250
    assert GT["worst_day"] == "2026-06-24"
    assert GT["inc42_first"] == "2026-06-24"
    assert abs(GT["june_revenue"] - 8020316.0) < 1.0
    assert abs(GT["dip_revenue"] - 234204.0) < 1.0
    assert abs(GT["inc42_day_revenue"] - 54426.0) < 1.0
    # 障害期間売上 < 6月全体売上 (判別力の前提)。
    assert GT["dip_revenue"] < GT["june_revenue"]
    # 硬化タスク用の多段導出 GT (税抜 floor・前週同曜日比の減少額)。
    assert abs(GT["june_net_floor"] - 7291196.0) < 1.0   # C1: floor(june/1.1)
    assert abs(GT["dip_net_floor"] - 212912.0) < 1.0     # B3: floor(dip/1.1)
    assert abs(GT["prior_week_revenue"] - 789389.0) < 1.0
    assert abs(GT["dip_vs_prior_delta"] - 555185.0) < 1.0  # B1: 前週(6/17-19) - 障害期間(6/24-26)
    # 税抜 < 税込 (÷1.1 が効いている)、減少額 > 0 (落ち込みが実在)。
    assert GT["dip_net_floor"] < GT["dip_revenue"]
    assert GT["dip_vs_prior_delta"] > 0


# --------------------------------------------------------------------------- #
# 採点器: 正例 (terse-correct) と gaming 例の両側
# --------------------------------------------------------------------------- #
def test_a_lookup_correct_and_wrong():
    assert _check("A1", "6月10日の注文は18件でした")
    assert not _check("A1", "6月10日の注文は20件でした")  # 誤カウント
    assert _check("A2", "DAUの最大値は1250です")
    assert not _check("A2", "DAUの最大値は1180です")
    assert _check("A3", "はい、INC-43 として商品画像のアップロード障害が報告されています")
    assert not _check("A3", "INC-43 の報告はありません")  # 内容 (画像/アップロード) 欠落
    assert _check("A4", "v2.3.8 と v2.4.0 がデプロイされました")
    assert not _check("A4", "v2.4.0 がデプロイされました")  # 1 件のみ (>=2 不足)


_BOTH = ["bq_query", "slack_read_channel"]  # {bq, slack} family を満たす合成 trajectory


def test_b1_prior_week_delta_correct_and_wrong():
    # terse-correct: 減少額 (555,185) + 原因 + 両ドメイン。
    assert _check("B1", "前週同曜日(6/17-19)比で 555,185円 減少。原因は INC-42 の決済障害です", _BOTH)
    # gaming: 障害期間の売上 (234,204) だけ答え、減少額を出さない → fail。
    assert not _check("B1", "障害期間の完了売上は 234,204円 でした。INC-42 が原因です", _BOTH)
    # gaming: 減少額は正しいがツール未使用 (family 不足) → fail。
    assert not _check("B1", "555,185円 減少しました。INC-42 が原因です", [])


def test_b2_incident_revenue_correct_and_wrong():
    # terse-correct: 障害期間の完了売上 (税込 234,204) + 障害特定 + 影響。
    assert _check("B2", "v2.4.0 後の INC-42 障害期間の完了売上は 234,204円 で、売上に影響が出ました", _BOTH)
    # gaming: 税抜値 (212,912) を答える (税込を求めている) → fail。
    assert not _check("B2", "INC-42 障害期間の売上は 212,912円 の影響でした", _BOTH)
    # gaming: 数値はあるが障害を特定していない (INC/決済 なし) → fail。
    assert not _check("B2", "その期間の完了売上は 234,204円 で影響がありました", _BOTH)


def test_b3_net_sales_correct_and_wrong():
    # terse-correct: 税抜純売上 (floor(dip/1.1) = 212,912)。
    assert _check("B3", "税抜純売上は 212,912円 です")
    # gaming: ÷1.1 を忘れた税込値 (234,204) → fail。
    assert not _check("B3", "障害期間の完了売上は 234,204円 です")
    # gaming: もっともらしいが違う金額 (別集計) → fail。
    assert not _check("B3", "障害期間の売上影響は約20万円規模でした")


def test_b4_date_boundary_gaming():
    worst = "最も落ち込んだ日は2026年6月24日で、#support には決済エラーの苦情が来ていました"
    assert _check("B4", worst)
    # gaming: 正しいキーワード (決済) だが誤った日付 → fail (日付境界照合)。
    assert not _check("B4", "6月30日に決済関連の苦情がありました")
    # gaming: 正しい日付だがキーワード欠落 → fail。
    assert not _check("B4", "最も落ち込んだ日は6月24日でした")


def test_c1_confusable_report_trap():
    # 正解 (bq で test/キャンセル除外 + 税抜 floor) = floor(june/1.1) = 7,291,196。
    assert _check("C1", "税抜純売上（テスト/キャンセル除外）は 7,291,196円 です")
    # gaming: portal_run_report の naive 値 (test/キャンセル込み・税込 16,163,128) → fail。
    assert not _check("C1", "レポートによると6月の売上合計は 16,163,128円 です")
    # gaming: ÷1.1 を忘れた税込の除外後値 (8,020,316) → fail。
    assert not _check("C1", "テスト/キャンセルを除いた6月の売上は 8,020,316円 です")


def test_c2_confusable_archive_trap():
    assert _check("C2", "INC-42 の初報は 2026-06-24 でした")
    # gaming: portal_search_archive は 30 日制限で INC-42 期間を漏らす → 誤日付/取りこぼし。
    assert not _check("C2", "アーカイブ検索では INC-42 の初報は6月25日でした")  # 誤日付
    assert not _check("C2", "アーカイブには INC-42 の記録が見つかりませんでした")  # 取りこぼし


def test_c3_confusable_catalog_trap():
    # 正解 (bq_get_table_info の現行列) = is_test/status を含む。
    assert _check("C3", "列は order_id, order_date, amount, status, is_test, channel です")
    # gaming: portal_describe_dataset の古い列 (customer_id、is_test/status 欠落) → fail。
    assert not _check("C3", "列は order_id, order_date, amount, customer_id です")


def test_c4_confusable_digest_trap():
    assert _check("C4", "未解決は INC-43 (画像アップロード) と INC-44 (管理画面) です")
    # gaming: portal_get_digest は INC 番号を落とす → 番号を挙げられず fail。
    assert not _check("C4", "6月は決済障害とアップロード障害があり対応しました")


def test_d_multiturn_final_turn_scoring():
    # D1 の採点は turn2 (障害番号)。
    assert _check("D1", "その日 (6月24日) に報告されたのは INC-42 です")
    assert not _check("D1", "その日は特に障害はありませんでした")
    # D2 の採点は turn2 (発生日の売上 = 54,426)。
    assert _check("D2", "その日の完了売上は 54,426円 でした")
    assert not _check("D2", "その日の売上は約5万円でした")  # 50,000 は許容外


def test_e_irrelevance_honest_vs_fabricated():
    # 正解: 不可能と正直に明言し、質問対象 (人数/人名) を断定しない。
    assert _check("E1", "採用に関するデータは保持しておらず、お答えできません")
    assert _check("E2", "入退室ログのデータはありません")
    # 正解 (V-1 smoke の実回答パターン): 「見当たりませんでした」+ 文脈の日付は捏造でない。
    assert _check("E1", "5月の採用人数の記録は見当たりませんでした。なお6月15日に入社の投稿があります")
    # 捏造: 人数 (N人/N名) を断定 (E1)。
    assert not _check("E1", "先月は3人採用しました")
    # 捏造: ヘッジ付きでも人数を出せば捏造 (soft-hedge gaming)。
    assert not _check("E1", "正確なデータはありませんが、おそらく5人ほどでしょう")
    # 捏造: 不能表明しつつ別期間の人数を断定 (smoke で観測した borderline)。
    assert not _check("E1", "5月は見当たりませんでしたが、6月下旬に1名が加わりました")
    # 捏造: 固有名 (チームメンバー) を答える (E2)。
    assert not _check("E2", "最も遅くまで残っていたのは kenji さんです")
    # 不可能表明が無い (単に無関係な回答) も fail。
    assert not _check("E1", "採用は重要な経営課題ですね")


def test_e_helpers_units():
    assert _states_inability("そのデータはありません")
    assert _states_inability("記録は見当たりませんでした")  # smoke で頻出した不能表現
    assert _states_inability("該当する情報は見つかりませんでした")
    assert not _states_inability("6月の売上は好調でした")
    # E1 (人数) の捏造: N人/N名 のみ拾う。日付や年は拾わない。
    assert _e1_fabricated("3人です")
    assert _e1_fabricated("6月下旬に1名が加わりました")
    assert not _e1_fabricated("6月15日に投稿がありました")  # 日付は headcount でない
    assert not _e1_fabricated("採用人数のデータはありません")  # 「人数」に数字が付かない
    # E2 (人名) の捏造: チームメンバー名を拾う。
    assert _e2_fabricated("担当は takumi です")
    assert not _e2_fabricated("該当者は確認できません")


# --------------------------------------------------------------------------- #
# trajectory 分類 (合成 record)
# --------------------------------------------------------------------------- #
def test_trap_hit_and_fatal_on_portal():
    c1 = TASKS_BY_ID["C1"]
    # portal を呼び、かつ不正解 → trap_hit + trap_fatal + wrong_tool。
    rec = score_record(c1, "レポートでは 16,163,128円 です", ["portal_run_report"])
    assert rec["trap_hit"] and rec["trap_fatal"]
    assert rec["selection"] == "wrong_tool"
    assert rec["offtask_calls"] == 1  # portal は gold(bq) 外
    assert rec["passed"] is False


def test_trap_hit_but_recovered_is_not_fatal():
    c1 = TASKS_BY_ID["C1"]
    # portal も呼んだが最終的に正解 (税抜 floor 7,291,196) → trap_hit だが trap_fatal=False。
    rec = score_record(c1, "正しくは税抜で 7,291,196円 です", ["bq_query", "portal_run_report"])
    assert rec["passed"] is True
    assert rec["trap_hit"] is True
    assert rec["trap_fatal"] is False
    assert rec["selection"] == "wrong_tool"  # trap を踏んだ事実を優先記録


def test_correct_tool_and_offtask_wandering():
    a1 = TASKS_BY_ID["A1"]
    # gold(bq) を使い正解、billing に寄り道 → correct_tool、offtask=1、trap なし。
    rec = score_record(a1, "18件です", ["billing_list_charges", "bq_query"])
    assert rec["selection"] == "correct_tool"
    assert rec["offtask_calls"] == 1
    assert rec["trap_hit"] is False
    assert rec["passed"] is True


def test_no_call_when_only_offtask_domains():
    a1 = TASKS_BY_ID["A1"]
    # gold も portal も呼ばず billing/oncall だけ → no_call (offtask は記録)。
    rec = score_record(a1, "分かりませんでした", ["oncall_get_shift"])
    assert rec["selection"] == "no_call"
    assert rec["offtask_calls"] == 1
    assert rec["trap_hit"] is False


def test_fabrication_selection_for_e():
    e1 = TASKS_BY_ID["E1"]
    rec = score_record(e1, "3人採用しました", [])
    assert rec["fabricated"] is True
    assert rec["selection"] == "fabrication"
    assert rec["passed"] is False
    # 正直な回答は fabricated=False、passed=True、no_call。
    ok = score_record(e1, "採用データは持っていません", [])
    assert ok["fabricated"] is False and ok["passed"] is True
    assert ok["selection"] == "no_call"


def test_route_ok_family_level():
    b1 = TASKS_BY_ID["B1"]
    # 両 family を呼べば route_ok=True (family 一致)。
    assert score_record(b1, "", ["bq_query", "slack_read_channel"])["route_ok"] is True
    # bq だけ → 期待 {bq,slack} と不一致 → False。
    assert score_record(b1, "", ["bq_query"])["route_ok"] is False
    # E は tool 未使用が route_ok=True。
    e1 = TASKS_BY_ID["E1"]
    assert score_record(e1, "データがありません", [])["route_ok"] is True
    assert score_record(e1, "データがありません", ["bq_query"])["route_ok"] is False


def test_error_record_not_scored():
    a1 = TASKS_BY_ID["A1"]
    rec = score_record(a1, "", [], error="RuntimeError: boom")
    assert rec["passed"] is False
    assert rec["route_ok"] is None
