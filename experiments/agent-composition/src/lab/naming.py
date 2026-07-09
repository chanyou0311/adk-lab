"""ドメイン名・ツール名・委譲名の単一ソース (ADK 非依存)。

採点 (tasks.py, オフライン) と環境/バリアント構築 (environments.py / variants) の両方がここから
引く。rescore がオフラインで動くよう ADK を import しない (duckdb/genai も持たない)。

trajectory 指標 (trap_hit / route_ok / offtask_calls / selection) をバリアント間で対称にするため、
「実ツール呼び出し」と「委譲呼び出し (AgentTool の *_assistant / transfer_to_agent)」「skill メタ
ツール」を明確に区別する。scoring は実ツール呼び出しだけを見る。委譲は routed_domains で別集計する。
"""

from __future__ import annotations

# 正準ドメイン順 (gold → 別ドメイン → distractor)。environments はここから ENV 構成を作る。
DOMAINS = ["bq", "slack", "billing", "oncall", "portal"]
GOLD_DOMAINS = ("bq", "slack")
# distractor (near-synonym の罠) ドメイン。trap_hit はここから導出する。
DISTRACTOR_DOMAINS = frozenset({"portal"})

# multi バリアントの委譲呼び出し名。AgentTool は subagent_name(domain)、transfer は
# "transfer_to_agent" (対象は args.agent_name)。これらは「実ツール」ではないので scoring から除外する。
_SUBAGENT_SUFFIX = "_assistant"
_TRANSFER_TOOL = "transfer_to_agent"


def subagent_name(domain: str) -> str:
    """ドメイン別 sub-agent の名前 (multi バリアントの Agent.name と一致させる単一ソース)。"""
    return f"{domain}{_SUBAGENT_SUFFIX}"


# ドメイン ⇔ sub-agent 名の対応。DELEGATION_NAMES / routed 復元はここから機構的に導く
# (命名規約を文字列操作で二重定義しない)。
_SUBAGENT_TO_DOMAIN = {subagent_name(d): d for d in DOMAINS}
DELEGATION_NAMES = frozenset(_SUBAGENT_TO_DOMAIN) | {_TRANSFER_TOOL}

# single_skills の skill メタツール (ルーティング判定で無視する)。
SKILL_TOOLS = frozenset({
    "list_skills",
    "load_skill",
    "load_skill_resource",
    "run_skill_script",
    "search_skills",
})


def is_real_tool(tool_name: str) -> bool:
    """委譲呼び出し・skill メタを除いた実ツール呼び出しか。"""
    return tool_name not in DELEGATION_NAMES and tool_name not in SKILL_TOOLS


def domain_of(tool_name: str) -> str | None:
    """実ツール名をドメインに写す (bq_/slack_/billing_/oncall_/portal_ prefix)。

    委譲呼び出し (*_assistant / transfer_to_agent) と skill メタツールは実ツールでないので None。
    """
    if not is_real_tool(tool_name):
        return None
    for d in DOMAINS:
        if tool_name.startswith(f"{d}_"):
            return d
    return None


def real_tool_names(tool_names: list[str]) -> list[str]:
    """trajectory から実ツール呼び出しだけを順序保持で取り出す。"""
    return [n for n in tool_names if is_real_tool(n)]


def called_domains(tool_names: list[str]) -> frozenset[str]:
    """呼ばれた実ツールのドメイン集合 (委譲/skill は無視)。"""
    return frozenset(d for n in tool_names if (d := domain_of(n)) is not None)


def has_distractor_call(tool_names: list[str]) -> bool:
    """distractor ドメイン (portal) の実ツールを 1 回でも呼んだか (= trap_hit)。"""
    return any(domain_of(n) in DISTRACTOR_DOMAINS for n in tool_names)


def _routed_domain_of(name: str) -> str | None:
    """委譲名 (subagent_name の逆写像) からドメインを復元 (それ以外は None)。"""
    return _SUBAGENT_TO_DOMAIN.get(name)


def routed_domains(tool_calls: list[dict]) -> list[str]:
    """委譲呼び出しから「どのドメインに委譲したか」を順序保持で復元する。

    AgentTool は呼び出し名 f"{domain}_assistant" から、transfer_to_agent は args.agent_name から
    ドメインを取り出し、両 multi バリアントで同じ粒度の routed_domains を導出する。
    """
    out: list[str] = []
    for call in tool_calls or []:
        name = call.get("name", "")
        direct = _routed_domain_of(name)
        if direct is not None:
            out.append(direct)
        elif name == _TRANSFER_TOOL:
            target = (call.get("args") or {}).get("agent_name", "")
            via_args = _routed_domain_of(str(target))
            if via_args is not None:
                out.append(via_args)
    return out
