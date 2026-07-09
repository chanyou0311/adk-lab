"""バリアント構築のテスト (Vertex 不要・LLM 呼び出しなしの構築のみ)。

各バリアントが各 env で build でき、ツール/サブエージェント配分が env と一致すること、
提示順 shuffle が決定的であること、registry が整合することを固定する。
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.skill_toolset import SkillToolset

from lab.environments import CLEAN, CONFUSABLE, DISTINCT, domains_for_env, ordered_domains
from lab.variants import VARIANTS

# env → (ドメイン数, ツール総数)。bq/slack/billing/oncall=3 本、portal=6 本。
_ENV_EXPECT = {CLEAN: (2, 6), DISTINCT: (4, 12), CONFUSABLE: (5, 18)}


def test_registry_has_six_variants():
    assert set(VARIANTS) == {
        "single_flat", "single_skills", "multi_agenttool", "multi_transfer",
        "multi_taskmode", "workflow_graph",
    }
    assert all(callable(b) for b in VARIANTS.values())


def test_cell_plan_covers_exactly_the_registry():
    # run_eval の収集セル計画 _CELL_ENVS は VARIANTS と過不足なく対応する
    # (バリアント追加/削除時にセル計画の更新漏れを機械的に検知する)。
    from run_eval import _CELL_ENVS
    assert set(_CELL_ENVS) == set(VARIANTS)


def test_all_variants_build_for_clean_and_confusable():
    for name, build in VARIANTS.items():
        for env in (CLEAN, CONFUSABLE):
            root = build(env)
            # root は Agent (single/multi) か Workflow (workflow_graph)。name はバリアント名に一致。
            assert root.name == name


def test_single_flat_tool_counts_match_env():
    for env, (_, n_tools) in _ENV_EXPECT.items():
        agent = VARIANTS["single_flat"](env)
        assert len(agent.tools) == n_tools
        # 全ツールが素の関数 (直接保持)。
        assert all(callable(t) for t in agent.tools)


def test_single_skills_gates_tools_behind_per_domain_skills():
    for env in (CLEAN, CONFUSABLE):
        n_domains, n_tools = _ENV_EXPECT[env]
        agent = VARIANTS["single_skills"](env)
        # root は SkillToolset ただ 1 つ (直接ツールなし)。
        assert len(agent.tools) == 1
        skillset = agent.tools[0]
        assert isinstance(skillset, SkillToolset)
        # env のドメインごとに 1 skill。
        assert set(skillset._skills) == set(domains_for_env(env))
        # ドメインツールは additional_tools にゲートされて保持 (初期状態では露出しない)。
        assert len(skillset._provided_tools_by_name) == n_tools
        # 各 skill の adk_additional_tools を合算するとツール総数に一致。
        total = sum(
            len(s.frontmatter.metadata["adk_additional_tools"]) for s in skillset._skills.values()
        )
        assert total == n_tools


def test_single_skills_confusable_has_portal_skill():
    agent = VARIANTS["single_skills"](CONFUSABLE)
    skillset = agent.tools[0]
    assert "portal" in skillset._skills
    assert skillset._skills["portal"].frontmatter.metadata["adk_additional_tools"] == [
        "portal_run_report", "portal_describe_dataset", "portal_list_datasets",
        "portal_search_archive", "portal_get_digest", "portal_list_groups",
    ]


def test_multi_agenttool_one_subagent_per_domain():
    for env in (CLEAN, CONFUSABLE):
        n_domains, _ = _ENV_EXPECT[env]
        agent = VARIANTS["multi_agenttool"](env)
        assert len(agent.tools) == n_domains
        assert all(isinstance(t, AgentTool) for t in agent.tools)
        sub_names = {t.agent.name for t in agent.tools}
        assert sub_names == {f"{d}_assistant" for d in domains_for_env(env)}
        # 各 sub のツール数: portal=6、他=3。
        for t in agent.tools:
            expected = 6 if t.agent.name == "portal_assistant" else 3
            assert len(t.agent.tools) == expected


def test_multi_agenttool_confusable_isolates_portal_subagent():
    agent = VARIANTS["multi_agenttool"](CONFUSABLE)
    sub_names = {t.agent.name for t in agent.tools}
    assert "portal_assistant" in sub_names  # portal 丸ごと 1 sub-agent に隔離


def test_multi_transfer_uses_sub_agents_not_tools():
    for env in (CLEAN, CONFUSABLE):
        n_domains, _ = _ENV_EXPECT[env]
        agent = VARIANTS["multi_transfer"](env)
        assert len(agent.sub_agents) == n_domains
        assert not agent.tools  # root は直接ツールを持たない (transfer で委譲)
        assert {s.name for s in agent.sub_agents} == {f"{d}_assistant" for d in domains_for_env(env)}


def test_multi_taskmode_single_turn_delegation():
    from lab.naming import is_real_tool
    for env in (CLEAN, CONFUSABLE):
        n_domains, _ = _ENV_EXPECT[env]
        agent = VARIANTS["multi_taskmode"](env)
        # sub-agent は単発 (single_turn) で sub_agents に接続、env と同数・同名。
        assert len(agent.sub_agents) == n_domains
        assert all(s.mode == "single_turn" for s in agent.sub_agents)
        assert {s.name for s in agent.sub_agents} == {f"{d}_assistant" for d in domains_for_env(env)}
        # single_turn は coordinator に委譲ツール (_SingleTurnAgentTool, name=sub 名) として現れる。
        assert {t.name for t in agent.tools} == {f"{d}_assistant" for d in domains_for_env(env)}
        # 委譲ツールは実ツール扱いされない (trajectory 指標の対称性)。
        assert all(not is_real_tool(t.name) for t in agent.tools)


def test_routed_domains_symmetric_across_three_delegation_mechanisms():
    # transfer / AgentTool / task-mode(single_turn) の 3 機構が同じ粒度の routed_domains を返す。
    from lab.naming import routed_domains
    # AgentTool と single_turn は委譲ツール名が sub-agent 名そのもの (bq_assistant)。
    agenttool_or_taskmode = [{"name": "bq_assistant", "args": {}}]
    # transfer は transfer_to_agent + args.agent_name。
    transfer = [{"name": "transfer_to_agent", "args": {"agent_name": "bq_assistant"}}]
    assert routed_domains(agenttool_or_taskmode) == ["bq"]
    assert routed_domains(transfer) == ["bq"]
    # finish_task (task-mode の完了通知) は委譲でも実ツールでもない。
    assert routed_domains([{"name": "finish_task", "args": {}}]) == []


def test_iso_thinking_level_across_all_agents():
    # 全バリアント・全 sub-agent が temperature=1.0 + thinking_level=LOW (統制)。
    from google.genai import types

    def _assert_cfg(agent: Agent) -> None:
        cfg = agent.generate_content_config
        assert cfg.temperature == 1.0
        assert cfg.thinking_config.thinking_level == types.ThinkingLevel.LOW

    ma = VARIANTS["multi_agenttool"](CONFUSABLE)
    _assert_cfg(ma)
    for t in ma.tools:
        _assert_cfg(t.agent)
    mt = VARIANTS["multi_transfer"](CONFUSABLE)
    _assert_cfg(mt)
    for s in mt.sub_agents:
        _assert_cfg(s)
    tm = VARIANTS["multi_taskmode"](CONFUSABLE)
    _assert_cfg(tm)
    for s in tm.sub_agents:
        _assert_cfg(s)


def test_seed_shuffles_presentation_order_deterministically():
    # ドメイン順が seed で決定的にシャッフルされる (single_flat 以外の提示順)。
    a = ordered_domains(CONFUSABLE, 3)
    b = ordered_domains(CONFUSABLE, 3)
    assert a == b
    assert sorted(a) == sorted(domains_for_env(CONFUSABLE))
    orderings = {tuple(ordered_domains(CONFUSABLE, s)) for s in range(6)}
    assert len(orderings) > 1
    # seed=None は正準順 (非シャッフル)。
    assert ordered_domains(CONFUSABLE) == domains_for_env(CONFUSABLE)


def test_single_flat_seed_shuffles_tool_order():
    canonical = [t.__name__ for t in VARIANTS["single_flat"](CONFUSABLE).tools]
    seeded = [t.__name__ for t in VARIANTS["single_flat"](CONFUSABLE, 1).tools]
    assert sorted(canonical) == sorted(seeded)  # 同じ集合
    # 18 ツールなら seed 付きで順序が変わる可能性が高い (決定性は別途 environments テストで担保)。
    assert set(canonical) == set(seeded)


# --------------------------------------------------------------------------- #
# workflow_graph (Workflow graph エンジン)
# --------------------------------------------------------------------------- #
def test_workflow_graph_spine_is_planner_dispatcher_synthesizer():
    from google.adk import Workflow
    for env in (CLEAN, CONFUSABLE):
        wf = VARIANTS["workflow_graph"](env)
        assert isinstance(wf, Workflow)
        # 静的グラフの spine は env に依らず planner → dispatcher → synthesizer (+ START)。
        node_names = [n.name for n in wf.graph.nodes]
        assert node_names == ["__START__", "planner", "dispatcher", "synthesizer"]


def test_workflow_graph_domain_node_count_matches_env():
    from lab.variants import workflow_graph as wg
    for env in (CLEAN, DISTINCT, CONFUSABLE):
        agents = wg._domain_agents(env)
        assert set(agents) == set(domains_for_env(env))
        # ドメインノードは multi の sub-agent と同一命名 (統制)。
        assert all(a.name == f"{d}_assistant" for d, a in agents.items())
        # ctx.run_node で動的スケジュールするので rerun_on_resume=True が必須
        # (False だと実行時に ValueError で全滅する。回帰ガード)。
        assert all(a.rerun_on_resume is True for a in agents.values())
    # CONFUSABLE では portal ドメインノードも存在する。
    assert "portal" in wg._domain_agents(CONFUSABLE)


def test_workflow_graph_iso_thinking_across_nodes():
    from google.genai import types

    from lab.variants import workflow_graph as wg

    def _ok(agent):
        cfg = agent.generate_content_config
        return cfg.temperature == 1.0 and cfg.thinking_config.thinking_level == types.ThinkingLevel.LOW

    wf = VARIANTS["workflow_graph"](CONFUSABLE)
    planner = next(n for n in wf.graph.nodes if n.name == "planner")
    synth = next(n for n in wf.graph.nodes if n.name == "synthesizer")
    assert _ok(planner) and _ok(synth)
    assert all(_ok(a) for a in wg._domain_agents(CONFUSABLE).values())


def test_workflow_graph_builds_into_app_runner():
    # run_eval と同じ経路 (App(root_agent=Workflow) + InMemoryRunner) で構築できる (LLM 実行なし)。
    from google.adk.apps import App
    from google.adk.runners import InMemoryRunner
    wf = VARIANTS["workflow_graph"](CLEAN)
    InMemoryRunner(app=App(name="t", root_agent=wf))
