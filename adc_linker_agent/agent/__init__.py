"""LangGraph agent orchestration — single and multi-agent systems.

Week 4: Single-agent ReAct loop with LangChain tools.
Week 5: Multi-agent supervisor + 3 specialists (Property/PH/Linker).

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
from adc_linker_agent.agent.state import AgentState, MultiAgentState
from adc_linker_agent.agent.tools import ALL_TOOLS

__all__ = [
    # State
    "AgentState",
    "MultiAgentState",
    # Tools
    "ALL_TOOLS",
    # Graphs
    "create_single_agent_graph",
    "create_multi_agent_graph",
    "get_agent",
]
