"""Gemini モデルの構築。

gemini-3-flash-preview は Vertex の **global エンドポイント限定** (regional は 404) なので、
fumo-adk の ``_GlobalGemini`` (api_client の location を global に固定) をそのまま流用する。
全実験を temperature=0 で走らせ、バリアント間の差が知識配置だけに帰属するようにする。
"""

from __future__ import annotations

from functools import cached_property

from google.adk.models import Gemini
from google.genai import Client, types

# 実験全体で共有する単一のモデル id。gemini-3-flash-preview は明示 pin する
# (alias 経由だと世代跨ぎで thought signature 検証が 400 になりうるため)。
MODEL = "gemini-3-flash-preview"


class _GlobalGemini(Gemini):
    """モデル推論を Vertex の global エンドポイントに固定する Gemini。

    gemini-3-flash-preview は global 限定 (regional は 404) なので api_client の location を
    global に上書きする (ADK 公式の customize パターン)。project / credentials は env
    (GOOGLE_CLOUD_PROJECT + ADC) から、retry は self.retry_options から継承する。
    """

    @cached_property
    def api_client(self) -> Client:
        return Client(
            vertexai=True,
            location="global",
            http_options=types.HttpOptions(retry_options=self.retry_options),
        )


def make_model() -> _GlobalGemini:
    """global エンドポイント固定 + 一時的 5xx を 3 回リトライする Gemini を新規生成する。

    エージェントごとに fresh なインスタンスを返し、root と sub-agent を独立させる。
    """
    return _GlobalGemini(model=MODEL, retry_options=types.HttpRetryOptions(attempts=3))


def make_generate_config() -> types.GenerateContentConfig:
    """全 LlmAgent に与える生成設定。temperature=0 で決定性を最大化する。"""
    return types.GenerateContentConfig(temperature=0.0)
