"""portal (社内ポータル) の near-synonym distractor ツール群 (portal_data.json バック)。

各ツールは gold ツール (bq/slack) と語彙が重なる説明を持つが、返すデータのスコープが微妙に違う
「もっともらしく不完全」な実データを返す (エラーや空で誤魔化さない)。使うと最終回答が決定的採点で
不正解になりうる:

- portal_run_report   ⇔ bq_query            : テスト/キャンセル込みの naive 集計値 (除外ルール違反)
- portal_describe_dataset ⇔ bq_get_table_info: 古い列定義 (現テーブルと不一致)
- portal_list_datasets ⇔ bq_list_tables     : bq_query で引けない論理データセット名
- portal_search_archive ⇔ slack_search_messages: 30 日より古いメッセージのみ (6/24-26 が漏れる)
- portal_get_digest   ⇔ slack_read_channel  : INC 番号などの詳細が落ちた要約
- portal_list_groups  ⇔ slack_list_channels : チャンネルでなくユーザーグループ

制約は各 docstring の末尾に正直に (小さく) 明記する — 読めば分かるが読み飛ばすと踏む realistic な罠。
fixture はモジュールロード時に読み込む (欠落/破損なら import 時に fail-fast)。
"""

from __future__ import annotations

from ._fixtures import load_fixture

_DATA = load_fixture("portal_data")
_REPORTS: dict[str, dict] = _DATA["reports"]
_DATASETS: dict[str, dict] = _DATA["datasets"]
_DATASET_LIST: list[str] = _DATA["dataset_list"]
_ARCHIVE: list[dict] = _DATA["archive"]
_DIGESTS: dict[str, str] = _DATA["digests"]
_GROUPS: list[dict] = _DATA["groups"]


def make_portal_tools() -> list:
    """portal の distractor ツール 6 種を返す (gold ツールと語彙が重なる説明を持つ)。"""

    def portal_run_report(metric: str, period: str) -> dict:
        """指定した指標 (metric) と期間 (period) の月次レポートを集計して返す。売上・注文などの数値を素早く確認できる。

        ※ 集計はテストアカウント・キャンセル分を含む簡易レポートです。
        """
        rep = _REPORTS.get(f"{metric}|{period}")
        if rep is None:
            return {"status": "error", "error_message": f"no report for {metric!r}/{period!r}",
                    "available": sorted(_REPORTS)}
        return {"status": "ok", **rep}

    def portal_describe_dataset(name: str) -> dict:
        """データセットの列定義・説明をデータカタログから返す。テーブルの構造を確認するのに使う。

        ※ カタログは四半期更新のため、最新テーブルと列が一致しないことがあります。
        """
        ds = _DATASETS.get(name)
        if ds is None:
            return {"status": "error", "error_message": f"unknown dataset {name!r}",
                    "available": sorted(_DATASETS)}
        return {"status": "ok", "dataset": ds}

    def portal_list_datasets() -> dict:
        """利用可能なデータセットの一覧を返す。

        ※ データカタログ上の論理データセット名で、SQL クエリのテーブル名とは一致しないことがあります。
        """
        return {"status": "ok", "datasets": _DATASET_LIST}

    def portal_search_archive(query: str) -> dict:
        """社内のメッセージ・会話をアーカイブから横断検索する。

        ※ アーカイブ対象は 30 日より前のメッセージのみです (直近のものは含まれません)。
        """
        q = query.lower()
        hits = [m for m in _ARCHIVE if q in m["text"].lower()]
        return {"status": "ok", "query": query, "match_count": len(hits), "messages": hits}

    def portal_get_digest(channel: str) -> dict:
        """チャンネルの日次ダイジェスト (要約) を返す。何が起きたか概要を素早く把握できる。

        ※ 要約のため、個別メッセージやインシデント番号などの詳細は含まれません。
        """
        ch = channel.lstrip("#")
        digest = _DIGESTS.get(ch)
        if digest is None:
            return {"status": "error", "error_message": f"no digest for {channel!r}",
                    "available": sorted(_DIGESTS)}
        return {"status": "ok", "channel": ch, "digest": digest}

    def portal_list_groups() -> dict:
        """社内のグループ一覧を返す。

        ※ これはチャンネルではなくユーザーグループ (メンション用のグループ) の一覧です。
        """
        return {"status": "ok", "groups": _GROUPS}

    return [portal_run_report, portal_describe_dataset, portal_list_datasets,
            portal_search_archive, portal_get_digest, portal_list_groups]
