"""
Agent Graph 构建（Week 4 + Week 5）

Week 4: 单 Agent ReAct 循环
    START → chatbot ↔ tools → END

Week 5: 多 Agent 监督者模式
    START → supervisor → [property_agent / ph_agent / linker_agent] → supervisor → END

使用方式:
    # 单 Agent (Week 4)
    graph = create_single_agent_graph()

    # 多 Agent (Week 5)
    graph = create_multi_agent_graph()
"""

from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel

from adc_linker_agent.agent.model_factory import create_model
from adc_linker_agent.agent.nodes import create_chatbot_node
from adc_linker_agent.agent.specialists import (
    linker_agent,
    ph_agent,
    property_agent,
)
from adc_linker_agent.agent.state import AgentState, MultiAgentState, SpecialistName
from adc_linker_agent.agent.tools import ALL_TOOLS

# ═══════════════════════════════════════════════════════════════
# Week 4: 单 Agent ReAct 图
# ═══════════════════════════════════════════════════════════════


def create_single_agent_graph() -> Any:
    """
    构建单 Agent ReAct 图。

    架构:
        START → chatbot → tools_condition → tools → chatbot (循环)
                           ↓ (无 tool_calls)
                           END

    Returns:
        编译后的 LangGraph Runnable
    """
    workflow = StateGraph(AgentState)
    workflow.add_node("chatbot", create_chatbot_node())
    workflow.add_node("tools", ToolNode(ALL_TOOLS))
    workflow.add_edge(START, "chatbot")
    workflow.add_conditional_edges("chatbot", tools_condition)
    workflow.add_edge("tools", "chatbot")

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


# ═══════════════════════════════════════════════════════════════
# Week 5: 多 Agent 监督者模式
# ═══════════════════════════════════════════════════════════════


# ─── Supervisor 路由决策模型 ───


class SupervisorDecision(BaseModel):
    """
    Supervisor 的路由决策。

    next 字段决定下一个被调用的 Agent:
      - "property_agent": 需要分子性质计算
      - "ph_agent": 需要 pH 稳定性分析
      - "linker_agent": 需要连接子设计/搜索
      - "FINISH": 任务完成，给出最终答案
    """

    next: Literal["property_agent", "ph_agent", "linker_agent", "FINISH"]
    reasoning: str  # 为什么选择这个 Agent（方便调试和日志）


# ─── Supervisor 系统提示 ───

SUPERVISOR_SYSTEM_PROMPT = """You are the ADC Linker Design Supervisor.

Your role: analyze the user's request and route it to the right specialist.

Your team:
- property_agent: Calculates molecular properties (LogP, QED, SAS, TPSA, Lipinski).
  Route HERE when the user asks about molecular properties, drug-likeness, or
  needs property calculations for a SMILES.

- ph_agent: Analyzes pH-dependent stability across physiological conditions.
  Route HERE when the user asks about pH stability, cleavage conditions,
  or needs to check if a linker is stable in blood / labile in lysosome.

- linker_agent: Designs and searches ADC linker scaffolds.
  Route HERE when the user wants to design a new linker, search known scaffolds,
  or needs comprehensive linker evaluation. This agent has ALL tools.

Routing rules:
1. For "design a linker..." or "find linkers..." → linker_agent
2. For "calculate properties of..." or "what is LogP of..." → property_agent
3. For "is this stable at pH..." or "check pH..." → ph_agent
4. For complex requests spanning multiple domains:
   - Start with property_agent for SMILES validation and basic properties
   - Then route to ph_agent for stability analysis
   - Finally route to linker_agent for design recommendations
5. After a specialist returns its results, review them and decide:
   - If more analysis is needed from another specialist → route there
   - If the task is complete → FINISH and provide a final synthesis

When finishing:
- Summarize what each specialist found
- Highlight key findings (good/bad properties, stability concerns)
- Give actionable recommendations
- Use the same language as the user (Chinese if they wrote in Chinese)
"""


def _create_supervisor_node() -> Any:
    """
    创建 Supervisor 节点。

    Supervisor 使用 structured output 确保路由决策格式正确。
    不绑定任何工具——Supervisor 只做路由，不执行工具。
    """
    from langchain_core.messages import SystemMessage

    model = create_model(
        temperature=0.3,
        max_tokens=1024,
        output_schema=SupervisorDecision,
    )

    def supervisor_node(state: MultiAgentState) -> dict:
        """Supervisor: 分析对话历史，决定下一步路由。"""
        messages = list(state["messages"])

        # 第一次调用时注入系统提示
        if not messages or not any(
            isinstance(m, SystemMessage) and "ADC Linker Design Supervisor" in str(m.content)
            for m in messages
        ):
            messages = [SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT)] + messages

        try:
            decision: SupervisorDecision = model.invoke(messages)
        except Exception:
            # 如果 structured output 失败，回退到 FINISH
            return {"next": "FINISH"}

        return {"next": decision.next}

    return supervisor_node


def _route_supervisor_decision(state: MultiAgentState) -> SpecialistName:
    """
    路由函数：从 state["next"] 读取 supervisor 的决策。

    这是 add_conditional_edges 的回调函数。
    返回下一个要执行的节点名称。
    """
    next_agent = state.get("next", "FINISH")
    if next_agent not in ("property_agent", "ph_agent", "linker_agent", "FINISH"):
        return "FINISH"
    return next_agent  # type: ignore[return-value]


def create_multi_agent_graph() -> Any:
    """
    构建多 Agent 监督者图。

    架构:
                     ┌──────────────┐
              START →│  supervisor  │ ←──────────┐
                     └──┬───┬───┬──┘             │
                        │   │   │                 │
               ┌────────┘   │   └────────┐        │
               ▼            ▼            ▼        │
        property_agent  ph_agent  linker_agent    │
               │            │            │        │
               └────────────┴────────────┘────────┘
                              │
                           FINISH

    模型由 .env 中的 LLM_PROVIDER 决定（deepseek / anthropic）。

    Returns:
        编译后的 LangGraph Runnable
    """
    # ─── 1. 创建图 ───
    workflow = StateGraph(MultiAgentState)

    # ─── 2. 添加节点 ───
    # supervisor: 路由决策节点
    workflow.add_node("supervisor", _create_supervisor_node())

    # 三个专长 Agent
    workflow.add_node("property_agent", property_agent)
    workflow.add_node("ph_agent", ph_agent)
    workflow.add_node("linker_agent", linker_agent)

    # ─── 3. 添加边 ───
    # 入口: 用户消息进入 supervisor
    workflow.add_edge(START, "supervisor")

    # 条件路由: supervisor 根据 next 字段决定下一步
    workflow.add_conditional_edges(
        "supervisor",
        _route_supervisor_decision,
        {
            "property_agent": "property_agent",
            "ph_agent": "ph_agent",
            "linker_agent": "linker_agent",
            "FINISH": END,
        },
    )

    # 所有专长 Agent 完成后返回 supervisor（循环）
    workflow.add_edge("property_agent", "supervisor")
    workflow.add_edge("ph_agent", "supervisor")
    workflow.add_edge("linker_agent", "supervisor")

    # ─── 4. 编译 ───
    memory = MemorySaver()
    graph = workflow.compile(checkpointer=memory)

    return graph


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def get_agent(
    thread_id: str = "default",
    mode: Literal["single", "multi"] = "multi",
) -> tuple[Any, dict]:
    """
    获取 Agent 图和运行配置。

    LLM 提供商和模型由 .env 中的配置决定（LLM_PROVIDER, LLM_MODEL）。

    Args:
        thread_id: 对话线程 ID
        mode: "single" (Week 4) 或 "multi" (Week 5, 默认)

    Returns:
        (graph, config) — 直接传给 graph.invoke(state, config)

    使用方式:
        from langchain_core.messages import HumanMessage

        graph, config = get_agent(mode="multi")
        state = {"messages": [HumanMessage(content="设计 pH 5.5 裂解的连接子")]}
        result = graph.invoke(state, config)
    """
    graph = create_single_agent_graph() if mode == "single" else create_multi_agent_graph()

    config = {"configurable": {"thread_id": thread_id}}
    return graph, config
