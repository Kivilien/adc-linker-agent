"""
测试 Multi-Agent Graph (Week 5)

验证:
  1. Graph 拓扑结构（supervisor + 3 specialists + 循环）
  2. Supervisor 路由决策模型
  3. 路由函数正确性
  4. 单 Agent 图仍然可用
"""

import pytest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from adc_linker_agent.agent.graph import (
    SupervisorDecision,
    create_multi_agent_graph,
    create_single_agent_graph,
    _route_supervisor_decision,
)
from adc_linker_agent.agent.state import MultiAgentState


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
        """Graph 必须包含三个专长 Agent"""
        graph = create_multi_agent_graph()
        nodes = graph.get_graph().nodes
        assert "property_agent" in nodes
        assert "ph_agent" in nodes
        assert "linker_agent" in nodes

    def test_start_goes_to_supervisor(self):
        """START 应该连接到 supervisor"""
        graph = create_multi_agent_graph()
        edges = graph.get_graph().edges
        start_edges = [e for e in edges if e.source == "__start__"]
        assert len(start_edges) == 1
        assert start_edges[0].target == "supervisor"

    def test_supervisor_has_conditional_edges_to_all_specialists(self):
        """supervisor 应该有条件边连接到所有三个专长 Agent"""
        graph = create_multi_agent_graph()
        edges = graph.get_graph().edges
        sup_edges = [e for e in edges if e.source == "supervisor" and e.conditional]
        targets = {e.target for e in sup_edges}
        assert "property_agent" in targets
        assert "ph_agent" in targets
        assert "linker_agent" in targets

    def test_supervisor_has_edge_to_end(self):
        """supervisor 应该有条件边到 END"""
        graph = create_multi_agent_graph()
        edges = graph.get_graph().edges
        end_edges = [e for e in edges if e.source == "supervisor"
                      and e.target == "__end__"]
        assert len(end_edges) >= 1

    def test_all_specialists_return_to_supervisor(self):
        """所有专长 Agent 完成后应返回 supervisor"""
        graph = create_multi_agent_graph()
        edges = graph.get_graph().edges
        for agent in ["property_agent", "ph_agent", "linker_agent"]:
            return_edges = [e for e in edges
                            if e.source == agent and e.target == "supervisor"]
            assert len(return_edges) >= 1, f"{agent} should return to supervisor"

    def test_no_direct_edge_between_specialists(self):
        """专长 Agent 之间不应有直接的边（必须通过 supervisor）"""
        graph = create_multi_agent_graph()
        edges = graph.get_graph().edges
        specialists = {"property_agent", "ph_agent", "linker_agent"}
        for e in edges:
            if e.source in specialists and e.target in specialists:
                pytest.fail(
                    f"Specialists should not connect directly: "
                    f"{e.source} → {e.target}"
                )

    def test_graph_is_runnable(self):
        """编译后的 graph 应该有 invoke 和 stream 方法"""
        graph = create_multi_agent_graph()
        assert hasattr(graph, "invoke")
        assert hasattr(graph, "stream")


class TestSupervisorDecisionModel:
    """测试 Supervisor 决策 Pydantic 模型"""

    def test_valid_decisions_accepted(self):
        """所有合法路由目标应该被接受"""
        for target in ["property_agent", "ph_agent", "linker_agent", "FINISH"]:
            decision = SupervisorDecision(next=target, reasoning="test")
            assert decision.next == target

    def test_invalid_decision_rejected(self):
        """非法路由目标应该被拒绝"""
        with pytest.raises(Exception):  # Pydantic validation error
            SupervisorDecision(next="invalid_agent", reasoning="test")  # type: ignore[arg-type]

    def test_reasoning_field_required(self):
        """reasoning 字段是必需的"""
        with pytest.raises(Exception):
            SupervisorDecision(next="FINISH")  # type: ignore[call-arg]

    def test_decision_is_serializable(self):
        """决策应该可以序列化为 JSON"""
        decision = SupervisorDecision(
            next="property_agent",
            reasoning="User asked about molecular properties",
        )
        json_str = decision.model_dump_json()
        assert "property_agent" in json_str
        assert "molecular properties" in json_str


class TestRouterFunction:
    """测试路由函数 _route_supervisor_decision"""

    def test_routes_to_property_agent(self):
        """next='property_agent' 应该路由到 property_agent"""
        state: MultiAgentState = {
            "messages": [HumanMessage(content="test")],
            "next": "property_agent",
        }
        result = _route_supervisor_decision(state)
        assert result == "property_agent"

    def test_routes_to_ph_agent(self):
        """next='ph_agent' 应该路由到 ph_agent"""
        state: MultiAgentState = {
            "messages": [],
            "next": "ph_agent",
        }
        result = _route_supervisor_decision(state)
        assert result == "ph_agent"

    def test_routes_to_linker_agent(self):
        """next='linker_agent' 应该路由到 linker_agent"""
        state: MultiAgentState = {
            "messages": [],
            "next": "linker_agent",
        }
        result = _route_supervisor_decision(state)
        assert result == "linker_agent"

    def test_routes_to_finish(self):
        """next='FINISH' 应该路由到 FINISH"""
        state: MultiAgentState = {
            "messages": [],
            "next": "FINISH",
        }
        result = _route_supervisor_decision(state)
        assert result == "FINISH"

    def test_unknown_next_defaults_to_finish(self):
        """未知的 next 值应该安全回退到 FINISH"""
        state: MultiAgentState = {
            "messages": [],
            "next": "quantum_agent",
        }
        result = _route_supervisor_decision(state)
        assert result == "FINISH"

    def test_missing_next_defaults_to_finish(self):
        """缺少 next 字段时应该默认 FINISH"""
        state: MultiAgentState = {
            "messages": [],
        }
        # 使用 .get("next", "FINISH") 的默认值逻辑在路由函数中
        result = _route_supervisor_decision(state)
        assert result == "FINISH"


class TestMultiAgentState:
    """测试 MultiAgentState 结构"""

    def test_state_has_next_field(self):
        """MultiAgentState 必须包含 next 字段"""
        assert "next" in MultiAgentState.__annotations__

    def test_state_has_messages_field(self):
        """MultiAgentState 必须包含 messages 字段"""
        assert "messages" in MultiAgentState.__annotations__

    def test_create_state_with_next(self):
        """可以创建带有 next 字段的状态"""
        state: MultiAgentState = {
            "messages": [HumanMessage(content="设计连接子")],
            "next": "linker_agent",
        }
        assert state["next"] == "linker_agent"


class TestBackwardCompatibility:
    """Week 4 单 Agent 图仍然正常工作"""

    def test_single_agent_graph_still_compiles(self):
        graph = create_single_agent_graph()
        nodes = graph.get_graph().nodes
        assert "chatbot" in nodes
        assert "tools" in nodes
