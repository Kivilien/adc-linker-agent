"""LangGraph agent orchestration — single and multi-agent systems.

架构 v2: 三阶段 Supervisor（Planner → Dispatcher → Synthesizer）
  + 双通道状态（messages + shared_context）

Quick start:
    from adc_linker_agent.agent.graph import get_agent
    from langchain_core.messages import HumanMessage

    graph, config = get_agent(mode="multi")
    result = graph.invoke(
        {"messages": [HumanMessage(content="设计 pH 5.5 裂解的连接子")]},
        config,
    )
"""

from adc_linker_agent.agent.graph import (
    create_multi_agent_graph,
    create_single_agent_graph,
    get_agent,
)
from adc_linker_agent.agent.state import AgentState, RoutableAgent, SpecialistName
from adc_linker_agent.agent.tools import ALL_TOOLS

# 向后兼容别名
MultiAgentState = AgentState

__all__ = [
    # State
    "AgentState",
    "MultiAgentState",  # deprecated, use AgentState
    "SpecialistName",
    "RoutableAgent",
    # Tools
    "ALL_TOOLS",
    # Graphs
    "create_single_agent_graph",
    "create_multi_agent_graph",
    "get_agent",
]
