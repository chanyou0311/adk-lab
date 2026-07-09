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
    _e_fabricated,
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


def test_b3_revenue_terse_correct_and_wrong():
    # terse-correct: 正解値のみ簡潔に。
    assert _check("B3", "234,204円です")
    # gaming/wrong: もっともらしいが違う金額 (naive 全期間や別集計)。
    assert not _check("B3", "障害期間の売上影響は約20万円規模でした")


def test_b4_date_boundary_gaming():
    worst = "最も落ち込んだ日は2026年6月24日で、#support には決済エラーの苦情が来ていました"
    assert _check("B4", worst)
    # gaming: 正しいキーワード (決済) だが誤った日付 → fail (日付境界照合)。
    assert not _check("B4", "6月30日に決済関連の苦情がありました")
    # gaming: 正しい日付だがキーワード欠落 → fail。
    assert not _check("B4", "最も落ち込んだ日は6月24日でした")


def test_c1_confusable_report_trap():
    # 正解 (bq で test 除外) = 8,020,316。
    assert _check("C1", "テストを除いた6月の完了売上は 8,020,316円 です")
    # gaming: portal_run_report の naive 値 (test/キャンセル込み 16,163,128) → fail。
    assert not _check("C1", "レポートによると6月の売上合計は 16,163,128円 です")


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
    # 正解: 不可能と正直に明言、数値/固有名を出さない。
    assert _check("E1", "採用に関するデータは保持しておらず、お答えできません")
    assert _check("E2", "入退室ログのデータはありません")
    # 捏造: 数値を答える (E1)。
    assert not _check("E1", "先月は3人採用しました")
    # 捏造: ヘッジ付きでも数値を出せば捏造 (soft-hedge gaming)。
    assert not _check("E1", "正確なデータはありませんが、おそらく5人ほどでしょう")
    # 捏造: 固有名 (チームメンバー) を答える (E2)。
    assert not _check("E2", "最も遅くまで残っていたのは kenji さんです")
    # 不可能表明が無い (単に無関係な回答) も fail。
    assert not _check("E1", "採用は重要な経営課題ですね")


def test_e_helpers_units():
    assert _states_inability("そのデータはありません")
    assert not _states_inability("6月の売上は好調でした")
    assert _e_fabricated("3人です")  # 数値
    assert _e_fabricated("担当は takumi です")  # 固有名
    assert not _e_fabricated("データがないためお答えできません")


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
    # portal も呼んだが最終的に正解 → trap_hit だが trap_fatal=False。誤選択信号は wrong_tool。
    rec = score_record(c1, "正しくは 8,020,316円 です", ["bq_query", "portal_run_report"])
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
