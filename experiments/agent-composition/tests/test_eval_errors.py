"""run_eval のエラー処理・キャップ (max_llm_calls) のテスト (Vertex 不要・合成例外)。

- 部分メトリクス保全: キャップ超過等で _run_once が落ちても消費済みトークンを記録に残す
- max_llm_calls が RunConfig に配線される
- LlmCallsLimitExceeded が non-transient (リトライで課金だけ増えるのを防ぐ)
"""

from __future__ import annotations

import asyncio

import run_eval  # conftest.py が eval/ を sys.path に追加している
from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from run_eval import (
    _eval_one,
    _is_cap_exceeded,
    _is_transient,
    _JobError,
    _make_run_config,
    _zero_metrics,
)
from tasks import TASKS_BY_ID


def test_cap_exceeded_is_not_transient():
    cap = LlmCallsLimitExceededError("Max number of llm calls limit of `120` exceeded")
    assert _is_cap_exceeded(cap) is True
    # transient マーカーには当たらない (429/503 等でない) → リトライされない。
    assert _is_transient(cap) is False
    # リトライ判定式 (transient かつ 非キャップ) は False。
    assert not (_is_transient(cap) and not _is_cap_exceeded(cap))
    # 通常の一時エラーは transient。
    assert _is_transient(RuntimeError("503 unavailable")) is True
    assert _is_cap_exceeded(RuntimeError("503 unavailable")) is False


def test_make_run_config_wiring():
    assert _make_run_config(None) is None
    rc = _make_run_config(120)
    assert rc is not None and rc.max_llm_calls == 120


def test_partial_metrics_preserved_on_job_error(monkeypatch):
    # _run_once が _JobError (部分メトリクス付き) を投げたら、_eval_one はそのトークン等を保全し、
    # error を付し passed=False にする (キャップ超過のコストを記録から失わない)。
    partial = {**_zero_metrics(), "final": "途中まで",
               "tool_names": ["bq_query", "bq_query"], "n_tool_calls": 2,
               "llm_calls": 120, "tokens": 1_300_000}
    cap = LlmCallsLimitExceededError("Max number of llm calls limit of `120` exceeded")

    async def _fake_run_once(*a, **k):
        raise _JobError(cap, partial)

    monkeypatch.setattr(run_eval, "_run_once", _fake_run_once)
    sem = asyncio.Semaphore(1)
    rec = asyncio.run(_eval_one("multi_taskmode", "confusable", TASKS_BY_ID["E1"], 0, sem, 120))

    # 消費済みメトリクスが保全されている (0 埋めされていない)。
    assert rec["llm_calls"] == 120
    assert rec["tokens"] == 1_300_000
    assert rec["n_tool_calls"] == 2
    # error が付き、採点は passed=False。
    assert "LlmCallsLimitExceededError" in rec["error"]
    assert rec["passed"] is False
    # cell/task メタも付与される。
    assert rec["cell"] == "multi_taskmode@confusable" and rec["task_id"] == "E1"


def test_transient_job_error_retries_then_falls_back(monkeypatch):
    # transient かつ 非キャップなら _MAX_ATTEMPTS までリトライし、最後は部分メトリクスで確定する。
    calls = {"n": 0}
    partial = {**_zero_metrics(), "llm_calls": 3, "tokens": 500}

    async def _flaky(*a, **k):
        calls["n"] += 1
        raise _JobError(RuntimeError("503 unavailable temporarily"), partial)

    async def _no_sleep(*_a, **_k):  # backoff を即時化 (実 sleep を呼ばない = 再帰回避)
        return None

    monkeypatch.setattr(run_eval, "_run_once", _flaky)
    monkeypatch.setattr(run_eval.asyncio, "sleep", _no_sleep)
    sem = asyncio.Semaphore(1)
    rec = asyncio.run(_eval_one("single_flat", "clean", TASKS_BY_ID["A1"], 0, sem))
    assert calls["n"] == run_eval._MAX_ATTEMPTS  # transient は上限までリトライ
    assert rec["tokens"] == 500 and rec["passed"] is False


def test_job_timeout_produces_error_record(monkeypatch):
    """ハングしたジョブは _JOB_TIMEOUT_S で打ち切られ、error record として先へ進む。"""
    import asyncio

    import run_eval

    async def _hang(*args, **kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr(run_eval, "_run_once", _hang)
    monkeypatch.setattr(run_eval, "_JOB_TIMEOUT_S", 0.05)
    task = TASKS_BY_ID["A1"]

    async def _run():
        sem = asyncio.Semaphore(1)
        return await run_eval._eval_one("single_flat", "clean", task, 0, sem)

    rec = asyncio.run(_run())
    assert "JobTimeout" in rec["error"]
    assert rec["passed"] is False
