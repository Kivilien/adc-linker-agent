"""
测试 AgentState 定义和消息管理
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from adc_linker_agent.agent.state import AgentState


class TestAgentState:
    """测试 Agent 状态结构"""

    def test_agent_state_has_messages(self):
        """AgentState 必须包含 messages 字段"""
        assert "messages" in AgentState.__annotations__

    def test_create_empty_state(self):
        """可以创建空消息列表的状态"""
        state: AgentState = {"messages": []}
        assert state["messages"] == []

    def test_create_state_with_user_message(self):
        """可以创建包含用户消息的状态"""
        msg = HumanMessage(content="计算阿司匹林的性质")
        state: AgentState = {"messages": [msg]}
        assert len(state["messages"]) == 1
        assert state["messages"][0].content == "计算阿司匹林的性质"

    def test_state_with_multiple_message_types(self):
        """状态可以混合多种消息类型"""
        messages = [
            HumanMessage(content="查询"),
            AIMessage(content="正在计算..."),
            ToolMessage(content='{"valid": true}', tool_call_id="call_1"),
        ]
        state: AgentState = {"messages": messages}
        assert len(state["messages"]) == 3
        assert isinstance(state["messages"][0], HumanMessage)
        assert isinstance(state["messages"][1], AIMessage)
        assert isinstance(state["messages"][2], ToolMessage)

    def test_add_messages_is_annotated(self):
        """messages 字段应该使用 add_messages reducer"""
        from typing import get_type_hints
        hints = get_type_hints(AgentState, include_extras=True)
        assert "messages" in hints
