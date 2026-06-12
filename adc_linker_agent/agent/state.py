"""
Agent 状态定义（LangGraph State）

这是 Agent 的"记忆"——在对话过程中持久化的状态。

Week 4: 单 Agent State (AgentState) — 只有 messages
Week 5: 多 Agent State (MultiAgentState) — 增加路由字段

类比:
  单 Agent = 一个人干活，工作台上只有一张纸
  多 Agent = 一个团队干活，工作台上需要便签告诉 supervisor 该派谁
"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """
    单 Agent 状态（Week 4 兼容）。

    Attributes:
        messages: 完整对话历史，使用 add_messages reducer 自动追加。
    """

    messages: Annotated[list[BaseMessage], add_messages]


# ─── 多 Agent 路由类型 ───

# 专长 Agent 名称
SpecialistName = Literal["property_agent", "ph_agent", "linker_agent", "FINISH"]


class MultiAgentState(TypedDict):
    """
    多 Agent 状态（Week 5）。

    扩展示例:
        state = {
            "messages": [HumanMessage("设计 pH 5.5 裂解的连接子")],
            "next": "linker_agent",   # supervisor 决定下一步找谁
        }

    Attributes:
        messages: 完整对话历史
        next: 监督者路由目标。可以是:
            - "property_agent": 分子性质计算专长
            - "ph_agent": pH 稳定性分析专长
            - "linker_agent": 连接子设计/骨架搜索专长
            - "FINISH": 任务完成，结束对话
    """

    messages: Annotated[list[BaseMessage], add_messages]
    next: str  # 监督者路由决策
