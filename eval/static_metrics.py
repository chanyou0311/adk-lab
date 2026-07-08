"""バリアント別の静的コスト計測 (実行前の instruction / tool 宣言のトークン量)。

各バリアントについて、モデルに毎リクエスト積まれる「固定コンテキスト」を測る:
- root instruction のトークン数
- sub-agent instruction 合計 (subagents バリアントのみ非ゼロ)
- tool declaration (name + description + schema) 合計トークン数

トークンは google-genai の count_tokens (Vertex, MODEL) で測り、失敗時は chars/4 の概算に
フォールバックする (どちらを使ったか記録)。全バリアントで同一の方法で測ることを担保する。

Usage:  GOOGLE_CLOUD_PROJECT=<proj> uv run python eval/static_metrics.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.adk.tools.agent_tool import AgentTool
from google.genai import Client, types

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
sys.path.insert(0, str(EVAL_DIR))

from lab.model import MODEL  # noqa: E402
from lab.variants import VARIANTS  # noqa: E402

load_dotenv()


class _Counter:
    """count_tokens が使えればそれを、失敗が続けば chars/4 概算を使う (方法を記録)。"""

    def __init__(self) -> None:
        self.method = "count_tokens"
        try:
            self._client: Client | None = Client(
                vertexai=True,
                location="global",
                http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=3)),
            )
        except Exception:  # noqa: BLE001
            self._client = None
            self.method = "approx(chars/4)"

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._client is not None:
            try:
                resp = self._client.models.count_tokens(model=MODEL, contents=text)
                return int(resp.total_tokens)
            except Exception:  # noqa: BLE001 - 以降は概算に切り替える
                self._client = None
                self.method = "approx(chars/4)"
        return max(1, round(len(text) / 4))


def _instruction_text(agent) -> str:
    ins = getattr(agent, "instruction", "")
    return ins if isinstance(ins, str) else str(ins)


async def _tool_declaration_text(agent) -> str:
    """agent の canonical tools を解決し、各宣言を JSON 直列化して連結した文字列。"""
    parts: list[str] = []
    for tool in await agent.canonical_tools():
        decl = tool._get_declaration()  # noqa: SLF001 - 宣言取得の canonical な方法
        if decl is not None:
            parts.append(decl.model_dump_json(exclude_none=True))
    return "\n".join(parts)


async def _measure(name: str, counter: _Counter) -> dict:
    agent = VARIANTS[name]()
    root_ins = _instruction_text(agent)

    sub_ins_parts: list[str] = []
    for tool in agent.tools:
        if isinstance(tool, AgentTool):
            sub_ins_parts.append(_instruction_text(tool.agent))
    sub_ins = "\n".join(sub_ins_parts)

    tool_decl = await _tool_declaration_text(agent)

    root_tokens = counter.count(root_ins)
    sub_tokens = counter.count(sub_ins) if sub_ins else 0
    decl_tokens = counter.count(tool_decl)
    return {
        "variant": name,
        "root_instruction_chars": len(root_ins),
        "root_instruction_tokens": root_tokens,
        "subagent_instruction_tokens": sub_tokens,
        "tool_declaration_tokens": decl_tokens,
        "total_fixed_context_tokens": root_tokens + sub_tokens + decl_tokens,
    }


def _render_markdown(rows: list[dict], method: str) -> str:
    lines = [
        "# 静的コスト計測 (固定コンテキストのトークン量)",
        "",
        f"- model: `{MODEL}`  ·  token count method: `{method}`",
        "- root instruction / sub-agent instruction / tool declaration に分けて、毎リクエスト積まれる固定コンテキストを測る。",
        "",
        "| variant | root instr (chars) | root instr (tok) | sub-agent instr (tok) | tool decl (tok) | 固定合計 (tok) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| `{r['variant']}` | {r['root_instruction_chars']} | {r['root_instruction_tokens']} | "
            f"{r['subagent_instruction_tokens']} | {r['tool_declaration_tokens']} | "
            f"{r['total_fixed_context_tokens']} |"
        )
    return "\n".join(lines) + "\n"


async def _main() -> None:
    counter = _Counter()
    rows = [await _measure(name, counter) for name in VARIANTS]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "static_metrics.json").write_text(
        json.dumps({"model": MODEL, "token_method": counter.method, "rows": rows},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md = _render_markdown(rows, counter.method)
    (RESULTS_DIR / "STATIC_METRICS.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    asyncio.run(_main())
