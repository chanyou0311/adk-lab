"""Gemini モデルの構築。

gemini-3-flash-preview は Vertex の **global エンドポイント限定** (regional は 404) なので、
``_GlobalGemini`` で api_client の location を global に固定する (ADK 公式の customize パターン)。
全実験を temperature=0 で走らせ、バリアント間の差が知識配置だけに帰属するようにする。
"""

from __future__ import annotations

from functools import cached_property

from google.adk.models import Gemini
from google.genai import Client, types

# 実験全体で共有する単一のモデル id。gemini-3-flash-preview は明示 pin する
# (alias 経由だと世代跨ぎで thought signature 検証が 400 になりうるため)。
MODEL = "gemini-3-flash-preview"

_SHARED_CLIENT: Client | None = None


def make_global_client() -> Client:
    """global エンドポイント固定・一時的 5xx を 3 回リトライする共有 genai Client (lazy singleton)。

    genai Client は並行リクエストに安全なので、eval の全ジョブ・全エージェントで 1 個を
    共有する — ジョブごとに新規 Client を作ると TLS ハンドシェイク+トークン取得が毎回
    発生しコネクションプールが再利用されない。global 固定の理由は _GlobalGemini 参照。
    """
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None:
        _SHARED_CLIENT = Client(
            vertexai=True,
            location="global",
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=3)),
        )
    return _SHARED_CLIENT


class _GlobalGemini(Gemini):
    """モデル推論を Vertex の global エンドポイントに固定する Gemini。

    gemini-3-flash-preview は global 限定 (regional は 404) なので api_client の location を
    global に上書きする (ADK 公式の customize パターン)。project / credentials は env
    (GOOGLE_CLOUD_PROJECT + ADC) から。retry は共有 Client 側の設定 (attempts=3) に一元化。
    """

    @cached_property
    def api_client(self) -> Client:
        return make_global_client()


def make_model() -> _GlobalGemini:
    """global エンドポイント固定 + 一時的 5xx を 3 回リトライする Gemini を新規生成する。

    エージェントごとに fresh なインスタンスを返し、root と sub-agent を独立させる。
    """
    return _GlobalGemini(model=MODEL, retry_options=types.HttpRetryOptions(attempts=3))


def make_generate_config() -> types.GenerateContentConfig:
    """全 LlmAgent に与える生成設定。temperature=0 で決定性を最大化する。"""
    return types.GenerateContentConfig(temperature=0.0)
