"""
Agent Graph 构建

这是 ADC Linker Agent 的核心编排逻辑。
用 LangGraph StateGraph 构建 ReAct 循环:

    START → chatbot ←→ tools
              ↓ (no tool_calls)
             END

user: "计算阿司匹林的所有性质" →
  chatbot: AIMessage(tool_calls=[validate_smiles("CC(=O)Oc1ccccc1C(=O)O")]) →
  tools:   ToolMessage(result={valid: true, formula: C9H8O4, ...}) →
  chatbot: AIMessage(tool_calls=[calculate_properties("...")]) →
  tools:   ToolMessage(result={logp: 1.31, qed: 0.78, ...}) →
  chatbot: AIMessage(content="阿司匹林的分子性质如下：...")

Week 5 扩展: 这个简单图会升级为 Supervisor + 3 Specialists 的多 Agent 图。
"""

from typing import Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from adc_linker_agent.agent.nodes import create_chatbot_node
from adc_linker_agent.agent.state import AgentState
from adc_linker_agent.agent.tools import ALL_TOOLS


def create_agent_graph(model_name: str = "claude-fable-5") -> StateGraph:
    """
    构建单 Agent ReAct 图。

    架构:
        START → chatbot → tools_condition → tools → chatbot (循环)
                           ↓ (无 tool_calls)
                           END

    学习点:
        - StateGraph(AgentState): 图的"骨架"，定义状态结构
        - add_node(): 添加处理节点（函数/可调用对象）
        - add_edge(START, "chatbot"): 入口边
        - add_conditional_edges(): 条件路由，根据 LLM 回复决定去向
        - compile(): 编译为可执行的 Runnable

    Args:
        model_name: Anthropic 模型名称

    Returns:
        编译后的 LangGraph Runnable，可通过 .invoke(state) 或 .stream(state) 执行
    """
    # ─── 1. 创建图 ───
    workflow = StateGraph(AgentState)

    # ─── 2. 添加节点 ───
    # chatbot: LLM 调用节点（bind_tools 后 LLM 能自主决定是否调用工具）
    workflow.add_node("chatbot", create_chatbot_node(model_name))

    # tools: 工具执行节点（LangGraph 内置 ToolNode）
    # ToolNode 自动:
    #   1. 读取 AIMessage 中的 tool_calls
    #   2. 调用对应的 Python 函数
    #   3. 返回 ToolMessage 结果
    workflow.add_node("tools", ToolNode(ALL_TOOLS))

    # ─── 3. 添加边 ───
    # 入口: 用户消息直接进入 chatbot
    workflow.add_edge(START, "chatbot")

    # 条件路由: chatbot 的输出决定下一步
    # tools_condition 的逻辑:
    #   if AIMessage has tool_calls → route to "tools"
    #   else → route to END
    workflow.add_conditional_edges(
        "chatbot",
        tools_condition,
        # tools_condition 返回 "tools" 或 "__end__"
    )

    # 循环: tools 执行完后总是回到 chatbot，让 LLM 看到结果后决定下一步
    workflow.add_edge("tools", "chatbot")

    # ─── 4. 编译（带内存检查点） ───
    # MemorySaver 提供会话内记忆（同一次对话中的多轮交互）
    # Week 6 会替换为持久化存储
    memory = MemorySaver()
    graph = workflow.compile(checkpointer=memory)

    return graph


# ─── 便捷函数 ───


def get_agent(
    model_name: str = "claude-fable-5",
    thread_id: str = "default",
) -> tuple[StateGraph, dict]:
    """
    获取 Agent 图和运行配置。

    Args:
        model_name: 模型名称
        thread_id: 对话线程 ID（同一线程共享记忆）

    Returns:
        (graph, config) — 直接传给 graph.invoke(state, config)

    使用方式:
        graph, config = get_agent()
        result = graph.invoke(
            {"messages": [HumanMessage(content="计算苯的性质")]},
            config,
        )
    """
    graph = create_agent_graph(model_name)
    config = {"configurable": {"thread_id": thread_id}}
    return graph, config
