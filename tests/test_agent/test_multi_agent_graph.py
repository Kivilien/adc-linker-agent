"""
测试 Multi-Agent Graph (架构 v2 — Three-Phase Supervisor)

验证:
  1. Graph 拓扑结构（supervisor + 4 specialists + 循环）
  2. Planner 输出模型 (PlanStep / PlanOutput)
  3. Dispatcher 路由函数 (_dispatch_next)
  4. 条件路由函数 (_route_supervisor)
  5. AgentState 结构
  6. 单 Agent 图向后兼容
"""

import pytest
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from adc_linker_agent.agent.graph import (
    PlanOutput,
    PlanStep,
    _dispatch_next,
    _route_supervisor,
    create_multi_agent_graph,
    create_single_agent_graph,
)
from adc_linker_agent.agent.state import AgentState


class TestMultiAgentGraphStructure:
    """测试 Multi-Agent Graph 拓扑"""

    def test_graph_compiles(self):
        """Multi-agent graph 应该成功编译"""
        graph = create_multi_agent_graph()
        assert graph is not None

    def test_graph_has_supervisor(self):
        """Graph 必须包含 supervisor 节点"""
        graph = create_multi_agent_graph()
        nodes = graph.get_graph().nodes
        assert "supervisor" in nodes

    def test_graph_has_all_specialists(self):
        """Graph 必须包含四个专长 Agent"""
        graph = create_multi_agent_graph()
        nodes = graph.get_graph().nodes
        assert "property_agent" in nodes
        assert "ph_agent" in nodes
        assert "linker_agent" in nodes
        assert "literature_agent" in nodes

    def test_start_goes_to_supervisor(self):
        """START 应该连接到 supervisor"""
        graph = create_multi_agent_graph()
        edges = graph.get_graph().edges
        start_edges = [e for e in edges if e.source == "__start__"]
        assert len(start_edges) == 1
        assert start_edges[0].target == "supervisor"

    def test_supervisor_has_conditional_edges_to_all_specialists(self):
        """supervisor 应该有条件边连接到所有四个专长 Agent"""
        graph = create_multi_agent_graph()
        edges = graph.get_graph().edges
        sup_edges = [e for e in edges if e.source == "supervisor" and e.conditional]
        targets = {e.target for e in sup_edges}
        assert "property_agent" in targets
        assert "ph_agent" in targets
        assert "linker_agent" in targets
        assert "literature_agent" in targets

    def test_supervisor_has_edge_to_end(self):
        """supervisor 应该有条件边到 END"""
        graph = create_multi_agent_graph()
        edges = graph.get_graph().edges
        end_edges = [
            e for e in edges
            if e.source == "supervisor" and e.target == "__end__"
        ]
        assert len(end_edges) >= 1

    def test_supervisor_loops_to_self_for_synthesize(self):
        """supervisor 应该有条件边到自身（__synthesize__ → 综合阶段）"""
        graph = create_multi_agent_graph()
        edges = graph.get_graph().edges
        self_edges = [
            e for e in edges
            if e.source == "supervisor" and e.target == "supervisor"
        ]
        assert len(self_edges) >= 1

    def test_all_specialists_return_to_supervisor(self):
        """所有专长 Agent 完成后应返回 supervisor"""
        graph = create_multi_agent_graph()
        edges = graph.get_graph().edges
        for agent in [
            "property_agent", "ph_agent", "linker_agent", "literature_agent",
        ]:
            return_edges = [
                e for e in edges
                if e.source == agent and e.target == "supervisor"
            ]
            assert len(return_edges) >= 1, f"{agent} should return to supervisor"

    def test_no_direct_edge_between_specialists(self):
        """专长 Agent 之间不应有直接的边（必须通过 supervisor）"""
        graph = create_multi_agent_graph()
        edges = graph.get_graph().edges
        specialists = {
            "property_agent", "ph_agent", "linker_agent", "literature_agent",
        }
        for e in edges:
            if e.source in specialists and e.target in specialists:
                pytest.fail(
                    f"Specialists should not connect directly: "
                    f"{e.source} -> {e.target}"
                )

    def test_graph_is_runnable(self):
        """编译后的 graph 应该有 invoke 和 stream 方法"""
        graph = create_multi_agent_graph()
        assert hasattr(graph, "invoke")
        assert hasattr(graph, "stream")


class TestPlanOutputModel:
    """测试 Planner 输出 Pydantic 模型 (PlanStep / PlanOutput)"""

    def test_valid_agents_accepted(self):
        """所有合法 Agent 目标应该被 PlanStep 接受"""
        for target in [
            "property_agent", "ph_agent", "linker_agent", "literature_agent",
        ]:
            step = PlanStep(agent=target, reason="test")
            assert step.agent == target

    def test_invalid_agent_rejected(self):
        """非法 Agent 应该被 PlanStep 拒绝"""
        with pytest.raises(ValidationError):
            PlanStep(agent="invalid_agent", reason="test")  # type: ignore[arg-type]

    def test_reason_field_required(self):
        """reason 字段是必需的"""
        with pytest.raises(ValidationError):
            PlanStep(agent="property_agent")  # type: ignore[call-arg]

    def test_plan_output_has_steps_and_reasoning(self):
        """PlanOutput 包含 steps 列表和 reasoning 字符串"""
        plan = PlanOutput(
            steps=[
                PlanStep(agent="property_agent", reason="check properties"),
                PlanStep(agent="ph_agent", reason="check ph stability"),
            ],
            reasoning="User wants comprehensive analysis",
        )
        assert len(plan.steps) == 2
        assert plan.steps[0].agent == "property_agent"
        assert plan.steps[1].agent == "ph_agent"
        assert "comprehensive" in plan.reasoning

    def test_plan_output_serializable(self):
        """PlanOutput 应该可以序列化为 JSON"""
        plan = PlanOutput(
            steps=[PlanStep(agent="property_agent", reason="test")],
            reasoning="basic check",
        )
        json_str = plan.model_dump_json()
        assert "property_agent" in json_str
        assert "basic check" in json_str

    def test_empty_steps_allowed(self):
        """空的 steps 列表在 Pydantic 层面允许（运行时会被 fallback 处理）"""
        plan = PlanOutput(steps=[], reasoning="no steps needed")
        assert plan.steps == []


class TestDispatchNext:
    """测试 Dispatcher 路由函数 _dispatch_next"""

    def test_returns_first_agent(self):
        """index=0 返回第一个 Agent"""
        plan = [{"agent": "property_agent"}, {"agent": "ph_agent"}]
        assert _dispatch_next(plan, 0) == "property_agent"

    def test_returns_second_agent(self):
        """index=1 返回第二个 Agent"""
        plan = [{"agent": "property_agent"}, {"agent": "ph_agent"}]
        assert _dispatch_next(plan, 1) == "ph_agent"

    def test_out_of_range_returns_synthesize(self):
        """越界返回 __synthesize__"""
        plan = [{"agent": "property_agent"}]
        assert _dispatch_next(plan, 1) == "__synthesize__"
        assert _dispatch_next(plan, 5) == "__synthesize__"

    def test_empty_plan_returns_synthesize(self):
        """空计划直接返回 __synthesize__"""
        assert _dispatch_next([], 0) == "__synthesize__"

    def test_missing_agent_key_returns_synthesize(self):
        """缺少 agent 键时返回 __synthesize__ 安全降级"""
        result = _dispatch_next([{"reason": "no agent key"}], 0)
        assert result == "__synthesize__"


class TestRouteSupervisor:
    """测试条件路由函数 _route_supervisor"""

    def test_routes_to_property_agent(self):
        """next='property_agent' 应该路由到 property_agent"""
        state: AgentState = {
            "messages": [HumanMessage(content="test")],
            "next": "property_agent",
            "shared_context": {},
        }
        assert _route_supervisor(state) == "property_agent"

    def test_routes_to_ph_agent(self):
        """next='ph_agent' 应该路由到 ph_agent"""
        state: AgentState = {
            "messages": [],
            "next": "ph_agent",
            "shared_context": {},
        }
        assert _route_supervisor(state) == "ph_agent"

    def test_routes_to_linker_agent(self):
        """next='linker_agent' 应该路由到 linker_agent"""
        state: AgentState = {
            "messages": [],
            "next": "linker_agent",
            "shared_context": {},
        }
        assert _route_supervisor(state) == "linker_agent"

    def test_routes_to_literature_agent(self):
        """next='literature_agent' 应该路由到 literature_agent"""
        state: AgentState = {
            "messages": [],
            "next": "literature_agent",
            "shared_context": {},
        }
        assert _route_supervisor(state) == "literature_agent"

    def test_routes_to_finish(self):
        """next='FINISH' 应该路由到 FINISH"""
        state: AgentState = {
            "messages": [],
            "next": "FINISH",
            "shared_context": {},
        }
        assert _route_supervisor(state) == "FINISH"

    def test_routes_to_synthesize(self):
        """next='__synthesize__' 应路由到自身触发综合阶段"""
        state: AgentState = {
            "messages": [],
            "next": "__synthesize__",
            "shared_context": {},
        }
        assert _route_supervisor(state) == "__synthesize__"

    def test_invalid_next_falls_back_to_finish(self):
        """非法的 next 值应该安全回退到 FINISH"""
        state: AgentState = {
            "messages": [],
            "next": "quantum_agent",
            "shared_context": {},
        }
        assert _route_supervisor(state) == "FINISH"

    def test_missing_next_defaults_to_finish(self):
        """缺少 next 字段时默认 FINISH"""
        state: AgentState = {
            "messages": [],
            "shared_context": {},
        }
        assert _route_supervisor(state) == "FINISH"


class TestAgentState:
    """测试 AgentState 结构"""

    def test_state_has_next_field(self):
        """AgentState 必须包含 next 字段"""
        assert "next" in AgentState.__annotations__

    def test_state_has_messages_field(self):
        """AgentState 必须包含 messages 字段"""
        assert "messages" in AgentState.__annotations__

    def test_state_has_shared_context_field(self):
        """AgentState 必须包含 shared_context 字段"""
        assert "shared_context" in AgentState.__annotations__

    def test_create_state_with_all_fields(self):
        """可以创建包含所有字段的状态"""
        state: AgentState = {
            "messages": [HumanMessage(content="设计连接子")],
            "next": "linker_agent",
            "shared_context": {
                "plan": [{"agent": "linker_agent", "reason": "design task"}],
                "plan_index": 0,
            },
        }
        assert state["next"] == "linker_agent"
        assert state["shared_context"]["plan_index"] == 0

    def test_create_minimal_state(self):
        """可以创建最小字段的状态"""
        state: AgentState = {
            "messages": [],
            "shared_context": {},
        }
        assert state["messages"] == []
        assert state["shared_context"] == {}


class TestBackwardCompatibility:
    """Week 4 单 Agent 图仍然正常工作"""

    def test_single_agent_graph_still_compiles(self):
        graph = create_single_agent_graph()
        nodes = graph.get_graph().nodes
        assert "chatbot" in nodes
        assert "tools" in nodes
