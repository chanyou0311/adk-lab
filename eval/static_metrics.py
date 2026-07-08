"""バリアント別の静的コスト計測 (実行前の instruction / tool 宣言のトークン量)。

各バリアントについて、モデルに毎リクエスト積まれる「固定コンテキスト」を層別に測る:
- root instruction
- sub-agent instruction 合計 + sub-agent 側 tool 宣言合計 (subagents バリアントのみ非ゼロ。
  sub-agent の LLM リクエストに毎回積まれるため、instruction と同様に固定層として数える)
- root の tool declaration (name + description + schema)
- skill boilerplate: ADK 2.4.0 の SkillToolset が process_llm_request で毎リクエスト注入する
  定型 system instruction。**<available_skills> XML (L1) は list_skills ツールが存在する限り
  system instruction には注入されない** (ADK 実装で確認) — L1 XML は list_skills 呼び出し時の
  ツール応答として返るオンデマンドコストなので、固定合計には含めず別掲する。

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
from google.adk.skills import prompt as skill_prompt
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.skill_toolset import DEFAULT_SKILL_SYSTEM_INSTRUCTION, SkillToolset
from google.genai import Client

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
sys.path.insert(0, str(EVAL_DIR))

from lab.model import MODEL, make_global_client  # noqa: E402
from lab.variants import VARIANTS  # noqa: E402

load_dotenv()


class _Counter:
    """count_tokens が使えればそれを、失敗が続けば chars/4 概算を使う (方法を記録)。"""

    def __init__(self) -> None:
        self.method = "count_tokens"
        try:
            self._client: Client | None = make_global_client()
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
    sub_decl_parts: list[str] = []
    skill_boilerplate = ""
    skill_l1_xml = ""
    for tool in agent.tools:
        if isinstance(tool, AgentTool):
            sub_ins_parts.append(_instruction_text(tool.agent))
            # sub-agent の LLM リクエストには sub 側ツールの宣言も毎回積まれる。
            # instruction だけ数えて宣言を落とすとバリアント間の層の数え方が非対称になる。
            sub_decl_parts.append(await _tool_declaration_text(tool.agent))
            # 層ウォークは root+1 階層前提。入れ子 (sub-agent がさらに SkillToolset /
            # AgentTool を持つ配置) は無言で取りこぼすと過小計測が実験結論に化けるため、
            # fail-fast にする (対応するときはここを再帰化する)。
            for sub_tool in tool.agent.tools:
                if isinstance(sub_tool, (AgentTool, SkillToolset)):
                    raise NotImplementedError(
                        f"nested {type(sub_tool).__name__} under sub-agent "
                        f"{tool.agent.name!r} is not measured; extend _measure first"
                    )
        elif isinstance(tool, SkillToolset):
            # 毎リクエスト注入されるのは定型 system instruction (boilerplate) のみ。
            # L1 XML は list_skills のツール応答としてオンデマンドに返る (固定合計外・別掲)。
            skill_boilerplate = DEFAULT_SKILL_SYSTEM_INSTRUCTION
            skill_l1_xml = skill_prompt.format_skills_as_xml(tool.skills)
    sub_ins = "\n".join(sub_ins_parts)
    sub_decl = "\n".join(sub_decl_parts)

    tool_decl = await _tool_declaration_text(agent)

    root_tokens = counter.count(root_ins)
    sub_ins_tokens = counter.count(sub_ins)
    sub_decl_tokens = counter.count(sub_decl)
    decl_tokens = counter.count(tool_decl)
    boilerplate_tokens = counter.count(skill_boilerplate)
    l1_xml_tokens = counter.count(skill_l1_xml)
    return {
        "variant": name,
        "root_instruction_chars": len(root_ins),
        "root_instruction_tokens": root_tokens,
        "subagent_instruction_tokens": sub_ins_tokens,
        "subagent_tool_declaration_tokens": sub_decl_tokens,
        "tool_declaration_tokens": decl_tokens,
        "skill_boilerplate_tokens": boilerplate_tokens,
        "total_fixed_context_tokens": (
            root_tokens + sub_ins_tokens + sub_decl_tokens + decl_tokens + boilerplate_tokens
        ),
        # オンデマンド (list_skills 応答)。固定合計には含めない。
        "skill_l1_xml_tokens_on_demand": l1_xml_tokens,
    }


def _render_markdown(rows: list[dict], method: str) -> str:
    lines = [
        "# 静的コスト計測 (固定コンテキストのトークン量)",
        "",
        f"- model: `{MODEL}`  ·  token count method: `{method}`",
        "- 「固定」= 毎 LLM リクエストに積まれる層: root instruction / sub-agent instruction+tool 宣言 (sub 側リクエスト) / root tool 宣言 / skill boilerplate (SkillToolset の定型 system instruction)。",
        "- skill L1 XML (<available_skills>) は system instruction には注入されず list_skills のツール応答として返るため、固定合計外の **オンデマンド** 列として別掲する。",
        "",
        "| variant | root instr (tok) | sub instr (tok) | sub tool decl (tok) | tool decl (tok) | skill boilerplate (tok) | **固定合計 (tok)** | (参考) skill L1 XML on-demand |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| `{r['variant']}` | {r['root_instruction_tokens']} | {r['subagent_instruction_tokens']} | "
            f"{r['subagent_tool_declaration_tokens']} | {r['tool_declaration_tokens']} | "
            f"{r['skill_boilerplate_tokens']} | **{r['total_fixed_context_tokens']}** | "
            f"{r['skill_l1_xml_tokens_on_demand']} |"
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
