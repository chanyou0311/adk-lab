"""data warehouse を模した mock ツール群 (DuckDB in-memory バック)。

モジュールロード時に fixtures の CSV を ``orders`` / ``daily_active_users`` / ``support_tickets``
テーブルとして登録する。CSV 登録 (カラムスペック + read_csv、パスエスケープ込み) は
``warehouse_csv_source`` / ``register_warehouse`` として export し、eval の GT 計算 (tasks.py) と
fixture テスト (tests) が同じ登録ロジックを共有する (登録の重複と SQL パス非エスケープを解消)。
"""

from __future__ import annotations

import datetime
import threading
from decimal import Decimal
from pathlib import Path

import duckdb

_WAREHOUSE = Path(__file__).resolve().parent.parent / "fixtures" / "warehouse"

# in-memory DuckDB は接続ごとにテーブルを持つので単一接続を共有する。DuckDB 接続は
# スレッド安全でないため、クエリ実行は _LOCK で直列化する (eval は複数ジョブを並列に回す)。
_CON = duckdb.connect(":memory:")
_LOCK = threading.Lock()


def _q(path: Path) -> str:
    return str(path).replace("'", "''")


# 既存テーブルは列型を明示して従来挙動を保つ (orders/daily_active_users は不変)。
# それ以外の warehouse/*.csv は auto_detect で自動登録し、ユースケース追加で CSV を
# 足すだけでツールから引けるようにする。
_COLUMN_SPECS: dict[str, str] = {
    "orders": (
        "{'order_id':'VARCHAR','order_date':'DATE','amount':'BIGINT',"
        "'status':'VARCHAR','is_test':'BOOLEAN','channel':'VARCHAR'}"
    ),
    "daily_active_users": "{'date':'DATE','dau':'BIGINT'}",
}
_KNOWN_DESCRIPTIONS: dict[str, str] = {
    "orders": "個々の注文レコード。columns: order_id, order_date, amount, status, is_test, channel",
    "daily_active_users": "日次のアクティブユーザー数。columns: date, dau",
    "support_tickets": "サポートチケット。columns: ticket_id, opened_at, first_response_at, plan, subject",
}


def warehouse_csv_source(table: str) -> str:
    """warehouse テーブルの ``read_csv(...)`` SQL 断片 (パスエスケープ + カラムスペック込み)。

    既知テーブルは列型を明示、それ以外は auto_detect。GT 計算・テスト・ツール登録で共有する。
    """
    csv_path = _WAREHOUSE / f"{table}.csv"
    spec = _COLUMN_SPECS.get(table)
    if spec:
        return f"read_csv('{_q(csv_path)}', header=true, columns={spec})"
    return f"read_csv('{_q(csv_path)}', header=true, auto_detect=true)"


def register_warehouse(con: duckdb.DuckDBPyConnection, tables: list[str] | None = None) -> None:
    """呼び出し側が渡す DuckDB 接続に warehouse テーブルを登録する。

    tables 未指定なら CSV から自動発見した全テーブル。tasks._compute_gt / tests から使い、
    read_csv のパスエスケープと列型指定を bq_tools と 1 本化する。
    """
    names = tables if tables is not None else sorted(p.stem for p in _WAREHOUSE.glob("*.csv"))
    for name in names:
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM {warehouse_csv_source(name)}")


def _register_warehouse() -> dict[str, str]:
    summary: dict[str, str] = {}
    for csv_path in sorted(_WAREHOUSE.glob("*.csv")):
        name = csv_path.stem
        _CON.execute(f"CREATE TABLE {name} AS SELECT * FROM {warehouse_csv_source(name)}")
        # description 欠落は fail-fast にする — 無内容な説明でツールを公開すると、エージェントが
        # テーブルを選べない失敗が「知識配置の効果」に見えて eval を静かに交絡させる。
        if name not in _KNOWN_DESCRIPTIONS:
            raise RuntimeError(
                f"warehouse table {name!r} has no entry in _KNOWN_DESCRIPTIONS; "
                "add one so bq_list_tables stays informative"
            )
        summary[name] = _KNOWN_DESCRIPTIONS[name]
    return summary


_TABLE_SUMMARY = _register_warehouse()


def _jsonable(value):
    """DuckDB が返す date / Decimal / 独自型を JSON 直列化可能な形に落とす。

    ツールの戻り値は ADK が pydantic で JSON 直列化してモデルへ返すため、直列化できない型
    (DuckDBPyType 等) が混じると実行が落ちる。既知の型を変換し、それ以外は str に倒す。
    """
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def make_bq_tools() -> list:
    """data warehouse ツール 3 種 (list_tables / get_table_info / query) を返す。

    docstring は中立的な 1 行のみ (知識は載せない — 本実験の変数はエージェント構成と環境であって
    知識配置ではない)。
    """

    def bq_list_tables() -> dict:
        return {
            "status": "ok",
            "tables": [{"name": n, "description": d} for n, d in _TABLE_SUMMARY.items()],
        }

    def bq_get_table_info(table_name: str) -> dict:
        if table_name not in _TABLE_SUMMARY:
            return {
                "status": "error",
                "error_message": f"unknown table {table_name!r}; use bq_list_tables first",
            }
        with _LOCK:
            cur = _CON.execute(f"SELECT * FROM {table_name} LIMIT 3")
            cols = [(d[0], str(d[1])) for d in cur.description]  # 型は DuckDBPyType → str に
            sample = cur.fetchall()
        return {
            "status": "ok",
            "table": table_name,
            "columns": [{"name": c, "type": t} for c, t in cols],
            "sample_rows": [
                {c: _jsonable(v) for (c, _), v in zip(cols, row, strict=False)} for row in sample
            ],
        }

    def bq_query(sql: str) -> dict:
        stmt = sql.strip().rstrip(";").strip()
        low = stmt.lower()
        if not (low.startswith("select") or low.startswith("with")):
            return {
                "status": "error",
                "error_message": "Only read-only SELECT queries are allowed.",
            }
        # DuckDB の execute は「SELECT 1; DELETE ...」のような複文も実行するため、prefix
        # チェックだけでは read-only ガードを迂回できてしまう (共有 in-memory 接続なので
        # 以降の全 eval ジョブのデータが壊れる)。複文は一律拒否する。文字列リテラル内の
        # ";" も弾く過剰側の近似だが、本 fixture への読取クエリで必要になる場面はない。
        if ";" in stmt:
            return {
                "status": "error",
                "error_message": "Only a single SELECT statement is allowed (no ';').",
            }
        try:
            with _LOCK:
                cur = _CON.execute(stmt)
                cols = [d[0] for d in cur.description]
                rows = cur.fetchmany(200)
            data = [{c: _jsonable(v) for c, v in zip(cols, row, strict=False)} for row in rows]
            return {
                "status": "ok",
                "columns": cols,
                "row_count": len(data),
                "rows": data,
            }
        except Exception as e:  # noqa: BLE001 - ツールエラーはモデルへ返して自己修復させる
            return {"status": "error", "error_message": str(e)}

    bq_query.__doc__ = "Run a read-only SQL (SELECT) query against the data warehouse."
    bq_list_tables.__doc__ = "List the tables available in the data warehouse."
    bq_get_table_info.__doc__ = "Get columns, types and a few sample rows for a warehouse table."

    return [bq_list_tables, bq_get_table_info, bq_query]
