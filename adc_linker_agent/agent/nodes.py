"""
Agent 节点定义

LangGraph 中的每个 Node 都是一个纯函数: state → {update}
- 输入: 当前状态（完整对话历史）
- 输出: 需要追加到状态的键值对

ReAct 循环只有两个节点:
  1. chatbot: 调用 LLM（可能返回 tool_calls 或最终答案）
  2. tools: 执行 tool_calls，返回 ToolMessage

为什么不用三个节点（route + call_mcp_tools + synthesize）？
  因为 LangGraph 的 ToolNode 和 tools_condition 已经封装了工具调用和路由。
  我们只需两个节点 + 一个条件边。
"""

from typing import Any

from langchain_core.messages import SystemMessage

from adc_linker_agent.agent.model_factory import create_model
from adc_linker_agent.agent.state import AgentState
from adc_linker_agent.agent.tools import ALL_TOOLS

# ─── 系统提示 ───
# 这是 Agent 的"行为准则"，告诉它自己是谁、能做什么、怎么回答

SYSTEM_PROMPT = """You are an ADC (Antibody-Drug Conjugate) Linker Design Assistant.

Your expertise covers:
- Molecular property calculation (LogP, QED, SAS, TPSA, molecular weight, etc.)
- pH-dependent stability analysis across physiological conditions
- ADC linker scaffold knowledge (Val-Cit-PABC, hydrazone, disulfide, etc.)
- Drug-likeness evaluation via Lipinski's Rule of Five

Workflow when analyzing a molecule:
1. ALWAYS call validate_smiles first to verify the SMILES
2. Call calculate_properties for key descriptors
3. Call predict_ph_stability_all_phases to assess linker suitability
4. If the user asks about linker types, call search_linker_scaffolds

When reporting results:
- Explain what each number means (not just list values)
- Flag any concerning values (e.g., LogP too high, unstable at blood pH)
- Give actionable design suggestions
- Use Chinese if the user writes in Chinese

ADC linker design rule of thumb:
- Stable at pH 7.4 (blood) → MUST
- Labile at pH 5.0-5.5 (lysosome) → GOAL
- LogP 1-3, QED > 0.5, SAS < 4 are good target ranges
"""


def create_chatbot_node() -> Any:
    """
    创建一个绑定了工具集的 LLM 调用节点。

    使用方式:
        chatbot = create_chatbot_node()
        workflow.add_node("chatbot", chatbot)
    """
    model = create_model(temperature=0.2, tools=ALL_TOOLS)

    def chatbot_node(state: AgentState) -> dict:
        """
        chatbot 节点: 调用 LLM 处理当前对话。

        输入: state["messages"] — 完整对话历史
        输出: {"messages": [AIMessage]} — LLM 的回复
              如果 LLM 决定调用工具，AIMessage 会包含 tool_calls
              如果 LLM 给出最终答案，AIMessage.content 就是回复文本
        """
        # 首次调用时注入系统提示
        messages = state["messages"]
        if not messages or not any(
            isinstance(m, SystemMessage) for m in messages
        ):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)

        response = model.invoke(messages)
        return {"messages": [response]}

    return chatbot_node
