"""
专长 Agent 定义（Week 5 Multi-Agent）

三个专长 Agent，每个只有完成任务所需的最小工具集：

  PropertyAgent:      分子性质计算（3 tools）
  PHAgent:            pH 稳定性分析（2 tools）
  LinkerDesignAgent:  连接子设计（6 tools，全工具集）

类比: 医院分诊
  - 全科医生(Supervisor) 问诊 → 决定挂哪个科
  - 心脏科(PropertyAgent) 只关心心电图/血压 → 不用看胃镜
  - 消化科(PHAgent) 只关心胃镜/pH → 不用看心电图
  - 药剂师(LinkerDesignAgent) 需要全部数据 → 综合配方

实现模式:
  每个专长 Agent 内部处理 tool_call 循环。
  调用 model → 有 tool_calls? → 执行工具 → 再次调用 model → 返回最终结果。
  这样 supervisor 拿到的是"完整答复"而非"工具请求"。
"""

from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from adc_linker_agent.agent.state import MultiAgentState
from adc_linker_agent.agent.tools import (
    ALL_TOOLS,
    calculate_properties,
    check_lipinski,
    predict_ph_stability,
    predict_ph_stability_all_phases,
    search_linker_scaffolds,
    validate_smiles,
)

# ─── 工具集分配（最小权限原则） ───

PROPERTY_TOOLS = [validate_smiles, calculate_properties, check_lipinski]
PH_TOOLS = [predict_ph_stability, predict_ph_stability_all_phases]
LINKER_TOOLS = ALL_TOOLS  # 连接子设计需要全部信息


# ─── 专长 Agent 系统提示 ───

PROPERTY_SYSTEM_PROMPT = """You are the Molecular Property Specialist.

Your ONLY job: calculate and interpret molecular properties.

You have access to:
- validate_smiles: verify SMILES validity
- calculate_properties: compute 8 key descriptors (LogP, QED, SAS, TPSA, etc.)
- check_lipinski: Lipinski's Rule of Five evaluation

Workflow:
1. ALWAYS validate the SMILES first
2. Calculate all properties
3. Check Lipinski rules
4. Report results with interpretation (not just numbers)

When reporting, explain what each value means for ADC linker design:
- LogP 1-3 ideal, >5 means too hydrophobic (aggregation risk)
- QED >0.5 drug-like, <0.3 needs optimization
- SAS <4 easy to synthesize, >6 complex/expensive
- TPSA 80-140 ideal for membrane permeability

Return a COMPLETE analysis. The supervisor needs your full output."""

PH_SYSTEM_PROMPT = """You are the pH Stability Specialist.

Your ONLY job: analyze pH-dependent stability of linker molecules.

You have access to:
- predict_ph_stability: check stability at a specific pH
- predict_ph_stability_all_phases: check all 6 physiological pH phases

Workflow:
1. Check stability at key pH points (7.4 blood, 5.0 lysosome)
2. Run the full physiological phase analysis
3. For each pH-sensitive group found, explain what it means

ADC linker design rule:
- MUST be stable at pH 7.4 (blood circulation)
- SHOULD cleave at pH 5.0-5.5 (lysosome)
- Partial instability at pH 6.5 (tumor microenv) is acceptable but needs monitoring

Flag any concerning patterns:
- Unstable at pH 7.4 → linker will release payload in bloodstream (toxic!)
- Stable at pH 5.0 → linker won't release payload (ineffective!)

Return a COMPLETE analysis. The supervisor needs your full output."""

LINKER_SYSTEM_PROMPT = """You are the ADC Linker Design Specialist.

Your ONLY job: help design and evaluate ADC linker candidates.

You have access to ALL tools:
- validate_smiles, calculate_properties, check_lipinski
- predict_ph_stability, predict_ph_stability_all_phases
- search_linker_scaffolds

Workflow for linker design:
1. Understand the user's requirements (pH trigger, payload type, stability needs)
2. Search known linker scaffolds for reference
3. Compute properties for candidate structures
4. Evaluate pH stability across all physiological phases
5. Provide design recommendations with property comparison

Workflow for linker evaluation:
1. Validate the SMILES
2. Calculate all properties
3. Assess pH stability
4. Compare against ideal ADC linker criteria

Return a COMPREHENSIVE analysis with actionable recommendations."""


# ─── 工具名 → 函数映射（用于 specialist 内部执行 tool_calls） ───

_TOOL_MAP = {
    "validate_smiles": validate_smiles,
    "calculate_properties": calculate_properties,
    "check_lipinski": check_lipinski,
    "predict_ph_stability": predict_ph_stability,
    "predict_ph_stability_all_phases": predict_ph_stability_all_phases,
    "search_linker_scaffolds": search_linker_scaffolds,
}


def _execute_tool_calls(ai_message: AIMessage) -> list[ToolMessage]:
    """
    执行 AIMessage 中的 tool_calls 并返回 ToolMessage 列表。

    这是 specialist 内部的工具执行循环的核心。
    从 tool_call 中提取函数名和参数 → 调用对应函数 → 包装为 ToolMessage。
    """
    tool_messages: list[ToolMessage] = []
    for tc in ai_message.tool_calls:
        tool_name = tc.get("name", "")
        tool_args = tc.get("args", {})
        call_id = tc.get("id", "unknown")

        func = _TOOL_MAP.get(tool_name)
        if func is None:
            content = f"Error: unknown tool '{tool_name}'"
        else:
            try:
                result = func.invoke(tool_args)
                import json

                content = json.dumps(result, ensure_ascii=False, indent=2)
            except Exception as e:
                content = f"Error executing {tool_name}: {e}"

        tool_messages.append(ToolMessage(content=content, tool_call_id=call_id))
    return tool_messages


# ─── 专长 Agent 工厂函数 ───


def create_specialist_node(
    name: str,
    system_prompt: str,
    tools: list[Any],
    model_name: str = "claude-fable-5",
) -> Any:
    """
    创建一个专长 Agent 节点。

    每个专长 Agent 内部处理完整的 tool_call 循环:
      model(system_prompt + messages) → tool_calls? → execute → model again → final response

    Args:
        name: Agent 名称（用于日志和路由）
        system_prompt: 专长 Agent 的系统提示
        tools: 该 Agent 可用的工具列表（最小权限分配）
        model_name: LLM 模型名

    Returns:
        可放入 StateGraph.add_node() 的节点函数
    """
    model = ChatAnthropic(
        model=model_name,
        temperature=0.2,
        max_tokens=4096,
    ).bind_tools(tools)

    def specialist_node(state: MultiAgentState) -> dict:
        """专长 Agent 节点: 处理分配的任务并返回完整结果。"""
        messages = list(state["messages"])

        # 注入系统提示（每次调用时注入，确保 LLM 知道自己的角色）
        system_msg = SystemMessage(content=system_prompt)

        # 构建请求消息: [system_prompt] + [history]
        request_messages = [system_msg] + messages

        # 内部循环: model → tool_calls? → execute → model
        max_iterations = 5  # 防止无限循环
        for _ in range(max_iterations):
            response = model.invoke(request_messages)

            # 如果有 tool_calls，执行它们并继续
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_messages = _execute_tool_calls(response)
                # 把 AIMessage (含 tool_calls) 和 ToolMessages 都加入上下文
                request_messages.append(response)
                request_messages.extend(tool_messages)
                continue

            # 没有 tool_calls → 最终回复
            return {"messages": [response]}

        # 到达最大迭代次数 → 强制返回最后一条消息
        return {
            "messages": [
                AIMessage(
                    content=(
                        f"[{name}] 达到最大工具调用次数。"
                        f"请 supervisor 根据以上工具结果综合结论。"
                    )
                )
            ]
        }

    # 附加元数据（方便调试）
    specialist_node.__name__ = name
    specialist_node.__doc__ = f"{name}: {system_prompt[:100]}..."

    return specialist_node


# ─── 三个专长 Agent ───

property_agent = create_specialist_node(
    name="property_agent",
    system_prompt=PROPERTY_SYSTEM_PROMPT,
    tools=PROPERTY_TOOLS,
)

ph_agent = create_specialist_node(
    name="ph_agent",
    system_prompt=PH_SYSTEM_PROMPT,
    tools=PH_TOOLS,
)

linker_agent = create_specialist_node(
    name="linker_agent",
    system_prompt=LINKER_SYSTEM_PROMPT,
    tools=LINKER_TOOLS,
)
