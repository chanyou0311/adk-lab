"""採点ロジックのユニットテスト (Vertex 不要・決定的)。

E2 の免罪フレーズ拡充 (「内部」字面限定 → 社内 / 直接的な影響はありません 等) が
偽陰性を解消し、かつ INC-44 を顧客影響として提示する誤答は依然 fail にすることを固定する。
"""

from __future__ import annotations

from tasks import (  # conftest.py が eval/ を sys.path に追加している
    _e2_check,
    _f1_check,
    _f2_check,
    _has_number,
    answer_contains_date,
    answer_contains_number,
    is_refused,
)

# 実データ (results_uc3.json) の GT。
_GT = {"sla_violations": 6, "pro_violation_ids": ["TCK-0001", "TCK-0008", "TCK-0025"]}


def test_e2_passes_when_only_inc43_is_customer_impact():
    assert _e2_check("顧客影響が出ている未解決の障害は INC-43 の1件です。")


def test_e2_passes_when_inc44_excluded_by_shanai_phrase():
    # 旧実装 (「内部」字面限定) では偽陰性だった実データ相当のパターン。
    text = (
        "顧客影響が出ている未解決の障害は INC-43 (sev1) の1件です。"
        "社内管理画面の表示遅延 (INC-44, sev2) もありますが、顧客への直接的な影響はありません。"
    )
    assert _e2_check(text)


def test_e2_still_fails_when_inc44_presented_as_customer_impact():
    # INC-44 を顧客影響として列挙し、免罪フレーズが無ければ fail のまま。
    text = "顧客影響のある未解決障害は INC-43 と INC-44 の2件です。"
    assert not _e2_check(text)


def test_e2_fails_without_inc43():
    assert not _e2_check("現在、未解決の障害はありません。")


# --- F1: 件数抽出 ---
def test_f1_passes_on_correct_count_with_threshold():
    text = "初回応答SLAに違反したサポートチケットは 6件 です。判定基準は Pro/支払いは4時間、その他は24時間。"
    assert _f1_check(text, _GT)


def test_f1_fails_on_thin_none_real_answer():
    # thin_none の実回答: 見つけた「24時間」定義で集計し「1件」、総数「全30件」。GT=6 を含まない。
    text = (
        "初回応答SLA（目標24時間以内）に違反したサポートチケットは 1件 です。"
        "全30件のチケットを調査した結果、TCK-0013 が30時間で超過していました。"
    )
    assert not _f1_check(text, _GT)


# --- F2: ID 包含 + 4時間 marker ---
def test_f2_passes_with_ids_and_four_hour_marker():
    text = "pro プランのうち SLA（初回応答 4 時間以内）違反は TCK-0001, TCK-0008, TCK-0025 の3件です。"
    assert _f2_check(text, _GT)


def test_f2_fails_on_fabricated_threshold_even_if_ids_present():
    # thin_none の実回答: 捏造した「pro=3時間」で真の 3 件をたまたま包含。4時間 marker が無い。
    text = (
        "proプランのSLAは初回返信まで3時間以内です。3時間以上かかった pro チケットは "
        "TCK-0025 (約7.0時間), TCK-0001 (約6.0時間), TCK-0008 (約5.5時間) の3件です。"
    )
    assert not _f2_check(text, _GT)


def test_f2_four_hour_marker_not_matched_by_24_hours():
    # 「24時間」を 4時間 marker と誤検出しないこと (basic 閾値のみに接地 = 誤閾値 → fail)。
    text = "basic は 24時間以内。違反 pro は TCK-0001, TCK-0008, TCK-0025 です。"
    assert not _f2_check(text, _GT)


# --- b'' (誤閾値のみ排除): terse-correct を通し、誤閾値のみ弾く ---
def test_f2_passes_terse_correct_ids_only():
    # 知識ありバリアントの実回答: 正解 ID を列挙、閾値 (時間) の明記なし → 正答として通す。
    text = "SLA違反となっている pro プランのチケットIDは以下の通りです。 TCK-0001, TCK-0008, TCK-0025"
    assert _f2_check(text, _GT)


def test_f2_fails_on_wrong_threshold_grounding():
    # 誤った pro 閾値 (2 時間) に接地して正解集合を包含 → 4時間 marker が無いので fail。
    text = "pro の SLA は 2 時間以内です。超過している pro は TCK-0001, TCK-0008, TCK-0025 の3件。"
    assert not _f2_check(text, _GT)


def test_f2_accepts_decimal_four_hours():
    # 「4.0時間」表記の正しい閾値言及を誤閾値扱いしない (レビュー A3 の回帰テスト)。
    text = "pro の SLA は初回応答 4.0時間以内です。違反は TCK-0001, TCK-0008, TCK-0025 です。"
    assert _f2_check(text, _GT)


def test_f1_scopes_counts_to_violation_sentences():
    # 「違反は3件」+ 別文脈の「6件」→ 違反文の {3} で判定し誤 pass しない (レビュー A5)。
    text = "SLA違反は3件です。なお6月の苦情は6件ありました。"
    assert not _f1_check(text, _GT)


def test_e2_exoneration_must_be_near_inc44():
    # 免罪フレーズが INC-44 と無関係な文にあるだけでは pass しない (レビュー A6)。
    text = "顧客影響のある未解決障害は INC-43 と INC-44 です。社内で対応中です。"
    assert not _e2_check(text)


def test_e2_exoneration_in_next_sentence_passes():
    # INC-44 言及の直後の文で除外を述べる正答は pass (実データに存在するパターン)。
    text = (
        "未解決の顧客影響障害は INC-43 です。その他 INC-44 も発生しています。"
        "こちらは社内向けで顧客影響はありません。"
    )
    assert _e2_check(text)


# --- 数値・日付・拒否ヘルパーの回帰テスト ---
def test_date_no_substring_false_positive():
    # "6/3" が "6/30" に部分一致しない (レビュー A1/D1)。
    assert not answer_contains_date("最大の売上日は 6/30 です", "2026-06-03")
    assert answer_contains_date("最大の売上日は 6月3日 です", "2026-06-03")
    assert answer_contains_date("最大の売上日は 2026-06-03 です", "2026-06-03")


def test_is_refused_ignores_hedged_estimates():
    # 逆接で見積もりに続くヘッジは拒否でない (レビュー A2/D2)。
    assert not is_refused("正確には算出できませんが、概算では約800万円と見込まれます。")
    assert not is_refused("専用の予測する機能はありませんが、データから概算すると約800万円です。")
    # 純粋な能力否定は依然として拒否。
    assert is_refused("予測することはできません。")
    assert is_refused("そのようなデータを持ち合わせておりません。")


def test_number_units_and_noise():
    # 「千」「千万」単位 (レビュー A4)。
    assert answer_contains_number("売上は6千万円です", 60_000_000)
    assert answer_contains_number("売上は約802万円です", 8_020_316)
    # 2000-2099 の正当な金額が年扱いで消えない (レビュー A7)。年表記は依然除去される。
    assert _has_number("推定売上は約2050万円です")
    assert not _has_number("2026年時点では INC-42 が発生していました (sev1, v2.4.0, K7)")
    # 全角の年も NFKC 正規化後に除去される (レビュー D3)。
    assert not _has_number("２０２６年時点の見込みです")
