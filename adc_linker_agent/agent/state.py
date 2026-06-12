"""
Agent 状态定义（LangGraph State）

这是 Agent 的"记忆"——在对话过程中持久化的状态。
每次 LLM 调用和工具执行都会读取和更新这个状态。

类比: 这是 Agent 的"工作台"：
  - messages 是工作台上的所有对话记录
  - 每个节点（chatbot, tools）在工作台上添新纸条
  - add_messages 确保新纸条不会覆盖旧纸条，而是追加

LangGraph 的 add_messages reducer:
  - 自动合并新旧消息列表
  - 正确处理 HumanMessage / AIMessage / ToolMessage
  - 支持消息替换（相同 tool_call_id 的 ToolMessage 替换占位）
"""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """
    ADC Linker Agent 的状态结构。

    Attributes:
        messages: 完整的对话历史。包括:
            - HumanMessage: 用户输入
            - AIMessage: LLM 的回复（可能包含 tool_calls）
            - ToolMessage: 工具执行的结果
            使用 add_messages reducer 自动追加而非覆盖。

    为什么只有 messages 一个字段？
        这是最小可行状态。Week 5 的多 Agent 系统会扩展为:
            AgentState:
                messages: ...     # 对话历史
                next_agent: str   # 监督者路由目标
                context: dict     # 跨 Agent 共享上下文
    """

    messages: Annotated[list[BaseMessage], add_messages]
