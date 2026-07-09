"""採点ヘルパーの回帰テスト (Vertex 不要・決定的)。

scaffold 時点では汎用の判定ヘルパー (数値/日付/拒否/ツール family) のみを固定する。
タスク固有の採点器はタスク設計時に tasks.py へ追加し、その回帰テストもここに足す。
"""

from __future__ import annotations

from tasks import (  # conftest.py が eval/ を sys.path に追加している
    _has_number,
    answer_contains_date,
    answer_contains_number,
    called_families,
    family_of,
    is_refused,
)


# --- 数値照合 (万/千/億・カンマ・相対誤差) ---
def test_number_units_and_noise():
    # 「千」「千万」単位。
    assert answer_contains_number("売上は6千万円です", 60_000_000)
    assert answer_contains_number("売上は約802万円です", 8_020_316)
    # カンマ区切りと相対誤差 1% 以内の一致。
    assert answer_contains_number("合計は 1,234,567 円です", 1_234_000, rel_tol=0.01)
    # 2000-2099 の正当な金額が年扱いで消えない。年表記は依然除去される。
    assert _has_number("推定売上は約2050万円です")
    assert not _has_number("2026年時点では INC-42 が発生していました (sev1, v2.4.0, K7)")
    # 全角の年も NFKC 正規化後に除去される。
    assert not _has_number("２０２６年時点の見込みです")


def test_number_zero_matching():
    # value=0 は絶対誤差で判定する (相対誤差だと 0 に一致できない)。
    assert answer_contains_number("差分は 0 件でした", 0.0)


# --- 日付照合 (表記ゆらぎ・数字境界) ---
def test_date_no_substring_false_positive():
    # "6/3" が "6/30" に部分一致しない。
    assert not answer_contains_date("最大の売上日は 6/30 です", "2026-06-03")
    assert answer_contains_date("最大の売上日は 6月3日 です", "2026-06-03")
    assert answer_contains_date("最大の売上日は 2026-06-03 です", "2026-06-03")


# --- 拒否検出 (文単位 + 逆接ヘッジ) ---
def test_is_refused_ignores_hedged_estimates():
    # 逆接で見積もりに続くヘッジは拒否でない。
    assert not is_refused("正確には算出できませんが、概算では約800万円と見込まれます。")
    assert not is_refused("専用の予測する機能はありませんが、データから概算すると約800万円です。")
    # 純粋な能力否定は依然として拒否。
    assert is_refused("予測することはできません。")
    assert is_refused("そのようなデータを持ち合わせておりません。")


# --- ツール family 判定 ---
def test_family_of_prefix_and_skill_tools():
    assert family_of("bq_query") == "bq"
    assert family_of("slack_read_channel") == "slack"
    # skill 系ツールは routing 判定で無視する (None を返す)。
    assert family_of("list_skills") is None
    assert family_of("load_skill") is None
    # 未知の名前も None。
    assert family_of("some_other_tool") is None


def test_called_families_dedup():
    fams = called_families(["bq_list_tables", "bq_query", "slack_search_messages", "list_skills"])
    assert fams == frozenset({"bq", "slack"})
    assert called_families([]) == frozenset()
