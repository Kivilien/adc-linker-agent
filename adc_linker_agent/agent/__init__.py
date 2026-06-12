"""LangGraph agent orchestration — single and multi-agent systems.

Week 4: Single-agent ReAct loop with MCP tools.
Week 5: Multi-agent supervisor + specialists.

Quick start:
    from adc_linker_agent.agent.graph import get_agent
    graph, config = get_agent()
    result = graph.invoke({"messages": [HumanMessage(content="...")]}, config)
"""

from adc_linker_agent.agent.state import AgentState
from adc_linker_agent.agent.tools import ALL_TOOLS
from adc_linker_agent.agent.graph import create_agent_graph, get_agent

__all__ = [
    "AgentState",
    "ALL_TOOLS",
    "create_agent_graph",
    "get_agent",
]
