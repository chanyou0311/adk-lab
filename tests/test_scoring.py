"""採点ロジックのユニットテスト (Vertex 不要・決定的)。

E2 の免罪フレーズ拡充 (「内部」字面限定 → 社内 / 直接的な影響はありません 等) が
偽陰性を解消し、かつ INC-44 を顧客影響として提示する誤答は依然 fail にすることを固定する。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

from tasks import _e2_check, _f1_check, _f2_check  # noqa: E402

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
    # 「24時間」を 4時間 marker と誤検出しないこと (ID は揃っていても閾値 marker 無しで fail)。
    text = "basic は 24時間以内。違反 pro は TCK-0001, TCK-0008, TCK-0025 です。"
    assert not _f2_check(text, _GT)
