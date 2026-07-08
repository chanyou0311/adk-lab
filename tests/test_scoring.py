"""採点ロジックのユニットテスト (Vertex 不要・決定的)。

E2 の免罪フレーズ拡充 (「内部」字面限定 → 社内 / 直接的な影響はありません 等) が
偽陰性を解消し、かつ INC-44 を顧客影響として提示する誤答は依然 fail にすることを固定する。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

from tasks import _e2_check  # noqa: E402


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
