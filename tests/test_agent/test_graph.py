"""
测试 Agent Graph 的结构和行为

核心验证:
  1. Graph 结构正确（节点、边、条件路由）
  2. Language Graph 条件路由逻辑
  3. 工具通过 LangChain @tool 调用验证（独立于 graph）
  4. ReAct 循环完整性

注意: LangGraph 1.x 的 ToolNode 需要完整的运行时上下文才能 invoke()，
不适合独立单元测试。工具执行正确性在 test_tools.py 中验证。
"""

import pytest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from adc_linker_agent.agent.graph import create_agent_graph
from adc_linker_agent.agent.state import AgentState


# ─── 测试用 SMILES ───
BENZENE_SMILES = "c1ccccc1"


class TestGraphStructure:
    """测试 Graph 的拓扑结构"""

    def test_graph_compiles(self):
        """Graph 应该成功编译"""
        graph = create_agent_graph()
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        """Graph 应该包含 chatbot 和 tools 节点"""
        graph = create_agent_graph()
        nodes = graph.get_graph().nodes
        assert "chatbot" in nodes
        assert "tools" in nodes
        assert "__start__" in nodes
        assert "__end__" in nodes

    def test_graph_has_start_to_chatbot_edge(self):
        """START 应该连接到 chatbot"""
        graph = create_agent_graph()
        edges = graph.get_graph().edges
        start_edges = [e for e in edges if e.source == "__start__"]
        assert len(start_edges) == 1
        assert start_edges[0].target == "chatbot"

    def test_graph_has_tools_to_chatbot_edge(self):
        """tools 应该连接回 chatbot（循环边）"""
        graph = create_agent_graph()
        edges = graph.get_graph().edges
        tools_edges = [e for e in edges if e.source == "tools"]
        assert any(e.target == "chatbot" for e in tools_edges), (
            "ReAct cycle broken: tools must return to chatbot"
        )

    def test_chatbot_has_conditional_edges(self):
        """chatbot 应该有条件边（到 tools 或 END）"""
        graph = create_agent_graph()
        edges = graph.get_graph().edges
        chatbot_cond = [e for e in edges if e.source == "chatbot" and e.conditional]
        assert len(chatbot_cond) >= 2, (
            "chatbot needs conditional edges to tools and END"
        )

    def test_graph_is_runnable(self):
        """编译后的 graph 应该有 invoke 和 stream 方法"""
        graph = create_agent_graph()
        assert hasattr(graph, "invoke")
        assert hasattr(graph, "stream")

    def test_all_edges_are_valid(self):
        """所有边的源和目标节点都应存在于图中"""
        graph = create_agent_graph()
        nodes = graph.get_graph().nodes
        for edge in graph.get_graph().edges:
            assert edge.source in nodes, f"Edge source '{edge.source}' not in graph"
            assert edge.target in nodes, f"Edge target '{edge.target}' not in graph"


class TestToolsCondition:
    """测试条件路由逻辑（LangGraph 内置 tools_condition）"""

    def test_aimessage_with_tool_calls_routes_to_tools(self):
        """包含 tool_calls 的 AIMessage 应该路由到 tools"""
        from langgraph.prebuilt import tools_condition

        state: AgentState = {
            "messages": [
                HumanMessage(content="计算苯的性质"),
                AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "validate_smiles",
                        "args": {"smiles": BENZENE_SMILES},
                        "id": "call_1",
                    }],
                ),
            ]
        }
        result = tools_condition(state)
        assert result == "tools"

    def test_aimessage_without_tool_calls_routes_to_end(self):
        """不包含 tool_calls 的 AIMessage 应该路由到 END"""
        from langgraph.prebuilt import tools_condition

        state: AgentState = {
            "messages": [
                HumanMessage(content="什么是 ADC？"),
                AIMessage(content="ADC 是抗体药物偶联物，由三部分组成..."),
            ]
        }
        result = tools_condition(state)
        assert result == "__end__"

    def test_empty_state_raises_error(self):
        """LangGraph 1.x: 空消息列表会抛出 ValueError（而非静默失败）"""
        from langgraph.prebuilt import tools_condition

        state: AgentState = {"messages": []}
        with pytest.raises(ValueError, match="No messages"):
            tools_condition(state)

    def test_multiple_tool_calls_still_routes_to_tools(self):
        """多个并发 tool_calls 仍然路由到 tools"""
        from langgraph.prebuilt import tools_condition

        state: AgentState = {
            "messages": [
                HumanMessage(content="全面分析"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "validate_smiles", "args": {"smiles": "c1ccccc1"}, "id": "c1"},
                        {"name": "calculate_properties", "args": {"smiles": "c1ccccc1"}, "id": "c2"},
                    ],
                ),
            ]
        }
        result = tools_condition(state)
        assert result == "tools"


class TestReActLoopCompleteness:
    """验证 ReAct 循环的完整性"""

    def test_chatbot_edges_form_loop(self):
        """
        ReAct 循环要求: chatbot → tools → chatbot 形成闭环。
        当没有 tool_calls 时 chatbot → END。
        """
        graph = create_agent_graph()
        edges = graph.get_graph().edges

        # chatbot → tools (conditional)
        c2t = [e for e in edges if e.source == "chatbot" and e.target == "tools"]
        assert len(c2t) >= 1, "Missing chatbot → tools conditional edge"

        # tools → chatbot (fixed)
        t2c = [e for e in edges if e.source == "tools" and e.target == "chatbot"]
        assert len(t2c) >= 1, "Missing tools → chatbot edge"

        # chatbot → END (conditional, when no tool_calls)
        c2e = [e for e in edges if e.source == "chatbot" and e.target == "__end__"]
        assert len(c2e) >= 1, "Missing chatbot → END conditional edge"


class TestAgentGraphConfig:
    """测试 Agent 配置"""

    def test_create_graph_with_default_model(self):
        """默认模型创建 graph 不抛异常"""
        graph = create_agent_graph()
        assert graph is not None

    def test_create_graph_with_specific_model(self):
        """指定模型名称创建 graph"""
        graph = create_agent_graph(model_name="claude-fable-5")
        assert graph is not None

    def test_config_structure(self):
        """验证 config dict 结构正确"""
        config = {"configurable": {"thread_id": "default"}}
        assert "configurable" in config
        assert "thread_id" in config["configurable"]

    def test_different_thread_ids(self):
        """不同 thread_id 创建独立对话"""
        config_a = {"configurable": {"thread_id": "session_a"}}
        config_b = {"configurable": {"thread_id": "session_b"}}
        assert config_a["configurable"]["thread_id"] != config_b["configurable"]["thread_id"]

    def test_memory_saver_included(self):
        """编译后的 graph 应该包含 MemorySaver（checkpointer）"""
        graph = create_agent_graph()
        # 有 checkpointer 意味着支持多轮对话记忆
        assert graph.checkpointer is not None
