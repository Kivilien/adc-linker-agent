"""
Agent Graph 构建（架构重写 v2 — Three-Phase Supervisor）

三阶段 Supervisor:
  Phase 1 (Planner):   分析用户请求 → 创建执行计划
  Phase 2 (Dispatcher): 纯 Python 路由，不调用 LLM
  Phase 3 (Synthesizer): 综合所有专长 Agent 结果 → FINISH

架构:
  START → supervisor (Planner)
    → [Dispatcher → Specialist → supervisor] 循环
    → supervisor (Synthesizer) → FINISH

相比旧版（纯路由器 SupervisorDecision）的关键修复:
  - Supervisor 现在能生成用户可读的综合输出
  - shared_context 保证文献等结构化数据在 LLM 失败后仍然存活
  - 模板降级作为 LLM 综合失败的安全网
"""

from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field

from adc_linker_agent.agent.model_factory import create_model
from adc_linker_agent.agent.nodes import create_chatbot_node
from adc_linker_agent.agent.specialists import (
    linker_agent,
    literature_agent,
    ph_agent,
    property_agent,
)
from adc_linker_agent.agent.state import AgentState, make_shared_context
from adc_linker_agent.agent.synthesizer import (
    build_synthesis_prompt,
    template_synthesize,
)
from adc_linker_agent.agent.tools import ALL_TOOLS

# ═══════════════════════════════════════════════════════════════
# Planner: Pydantic 结构化输出模型
# ═══════════════════════════════════════════════════════════════


class PlanStep(BaseModel):
    """单个执行步骤"""

    agent: Literal[
        "property_agent", "ph_agent", "linker_agent", "literature_agent"
    ]
    reason: str = Field(description="为什么需要这个步骤")


class PlanOutput(BaseModel):
    """Planner 的输出: 有序步骤列表"""

    steps: list[PlanStep] = Field(
        description="按顺序执行的专业 Agent 列表"
    )
    reasoning: str = Field(description="为什么选择这个计划")


# ═══════════════════════════════════════════════════════════════
# Prompts
# ═══════════════════════════════════════════════════════════════

PLANNER_PROMPT = """You are the ADC Linker Design Supervisor (Planner).

Analyze the user's request and create an execution plan using available specialists.

Available specialists:
- property_agent: Molecular properties (LogP, QED, SAS, TPSA, Lipinski, toxicity)
- ph_agent: pH stability across 6 physiological conditions (blood to lysosome)
- linker_agent: ADC linker design, scaffold search, comprehensive evaluation
- literature_agent: Scientific literature (PubMed/Europe PMC) to verify claims

Planning rules:
1. "calculate properties of X" or "what is LogP of X" → [property_agent]
2. "check pH stability of X" or "is X stable in blood" → [ph_agent]
3. "design a linker for X" or "find linkers for X" → [linker_agent]
4. "search literature about X" or "find papers on X" → [literature_agent]
5. Complex requests: order by dependency
   - property_agent FIRST (validate SMILES, baseline properties)
   - ph_agent SECOND (stability assessment)
   - linker_agent THIRD (design if needed)
   - literature_agent LAST (verify claims with published evidence)
6. Keep plans MINIMAL — don't add unnecessary steps
7. Use the same number of steps as the domains the user asked about

Output a valid JSON plan."""

SYNTHESIZER_PROMPT = """You are the ADC Linker Design Supervisor (Synthesizer).

Your job: synthesize specialist results into a clear, useful answer.

CRITICAL RULES:
1. Use the SAME LANGUAGE as the user (Chinese → Chinese, English → English)
2. Present COMPUTED DATA first, then LITERATURE EVIDENCE, then RECOMMENDATIONS
3. When citing papers: include title, journal, year, and DOI link
4. If data is incomplete or missing, honestly say so — do NOT fabricate
5. Output style: no ## markdown headings, no decorative emoji
   - Tables ONLY for comparing 3+ candidates
   - Single entities: indented lists, not tables
   - Be concise but complete

Data sources you receive:
- 📊 Tool-computed: RDKit properties, PhSimulator predictions, design scores
- 📚 Literature: REAL papers found by literature_agent (cite with DOI!)
- 💡 Your synthesis: recommendations based on both above"""


# ═══════════════════════════════════════════════════════════════
# Dispatcher (pure Python, zero LLM calls)
# ═══════════════════════════════════════════════════════════════


def _dispatch_next(plan: list[dict], index: int) -> str:
    """
    从计划中获取下一个要执行的 Agent。

    纯逻辑路由，不调用 LLM:
      - index 在范围内 → 返回 plan[index]["agent"]
      - index 越界 → 返回 "__synthesize__" 触发综合阶段
    """
    if index >= len(plan):
        return "__synthesize__"
    step = plan[index]
    return step.get("agent", "__synthesize__")


# ═══════════════════════════════════════════════════════════════
# Supervisor Node Factory
# ═══════════════════════════════════════════════════════════════


def _create_supervisor_node() -> Any:
    """
    创建三阶段 Supervisor 节点。

    阶段检测逻辑（通过 shared_context 状态机）:
      1. plan 为空 → PLANNER（分析请求、制定计划）
      2. plan_index < len(plan) → DISPATCHER（纯路由到下一个 Agent）
      3. plan_index >= len(plan) → SYNTHESIZER（综合所有结果 → FINISH）

    关键设计:
      - shared_context 使用 _merge_context reducer 合并更新（不替换）
      - 模板降级 (template_synthesize) 作为 LLM 综合失败的安全网
      - Planner 失败时通过 _fallback_route 关键词匹配降级
    """
    planner_model = create_model(
        temperature=0.3,
        max_tokens=1024,
        output_schema=PlanOutput,
    )
    synthesizer_model = create_model(temperature=0.3, max_tokens=2048)

    def supervisor_node(state: AgentState) -> dict:
        """Supervisor 节点: 根据计划状态检测阶段并执行。"""
        ctx = state.get("shared_context", make_shared_context())
        plan = ctx.get("plan", [])

        # ── Phase 1: PLANNER（首次调用，plan 为空）──
        if not plan:
            return _run_planner(state, ctx, planner_model)

        # Phase 2/3 检测
        idx = ctx.get("plan_index", 0)

        # ── Phase 2: DISPATCHER（仍有未执行的计划步骤）──
        if idx < len(plan):
            return _run_dispatcher(ctx, idx)

        # ── Phase 3: SYNTHESIZER（所有步骤已完成）──
        return _run_synthesizer(state, ctx, synthesizer_model)

    return supervisor_node


def _run_planner(
    state: AgentState, current_ctx: dict, planner_model: Any
) -> dict:
    """Phase 1: 分析请求，创建执行计划。"""
    # 构建 planner 消息
    planner_messages = [SystemMessage(content=PLANNER_PROMPT)]
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            planner_messages.append(msg)
            break

    try:
        plan_output: PlanOutput = planner_model.invoke(planner_messages)

        new_plan = [
            {"agent": step.agent, "reason": step.reason}
            for step in plan_output.steps
        ]

        if not new_plan:
            return _fallback_route(state, current_ctx)

        first_agent = _dispatch_next(new_plan, 0)

        return {
            "shared_context": {
                **current_ctx,
                "plan": new_plan,
                "plan_index": 1,
                "execution_log": current_ctx.get("execution_log", [])
                + [f"Planner: {plan_output.reasoning}"],
            },
            "next": first_agent,
        }
    except Exception as e:
        current_ctx["errors"] = current_ctx.get("errors", []) + [
            {"agent": "planner", "phase": "planning", "error": str(e)}
        ]
        return _fallback_route(state, current_ctx)


def _run_dispatcher(ctx: dict, idx: int) -> dict:
    """Phase 2: 纯路由 — 从计划中取下一个 Agent。"""
    plan = ctx.get("plan", [])
    next_agent = _dispatch_next(plan, idx)

    log_msg = (
        f"Dispatcher → {next_agent}"
        if next_agent != "__synthesize__"
        else "Dispatcher: all steps complete, entering synthesis"
    )

    return {
        "shared_context": {
            **ctx,
            "plan_index": idx + 1,
            "execution_log": ctx.get("execution_log", []) + [log_msg],
        },
        "next": next_agent,
    }


def _run_synthesizer(
    state: AgentState, ctx: dict, model: Any
) -> dict:
    """Phase 3: 综合所有专长 Agent 的结果，生成最终用户输出。"""
    try:
        prompt = build_synthesis_prompt(ctx)
        synth_messages = [SystemMessage(content=SYNTHESIZER_PROMPT)]

        # 添加用户原始问题作为上下文
        for msg in state.get("messages", []):
            if isinstance(msg, HumanMessage):
                synth_messages.append(msg)
                break

        synth_messages.append(HumanMessage(content=prompt))

        response = model.invoke(synth_messages)
        synthesis = (
            response.content
            if hasattr(response, "content")
            else str(response)
        )

        return {
            "messages": [AIMessage(content=synthesis)],
            "shared_context": {
                **ctx,
                "execution_log": ctx.get("execution_log", [])
                + ["Synthesizer: complete"],
            },
            "next": "FINISH",
        }
    except Exception as e:
        # LLM 综合失败 → 使用模板降级（关键安全网）
        synthesis = template_synthesize(ctx)
        return {
            "messages": [AIMessage(content=synthesis)],
            "shared_context": {
                **ctx,
                "execution_log": ctx.get("execution_log", [])
                + ["Synthesizer: template fallback (LLM failed)"],
                "errors": ctx.get("errors", []) + [
                    {"agent": "synthesizer", "phase": "synthesis", "error": str(e)}
                ],
            },
            "next": "FINISH",
        }


def _fallback_route(
    state: AgentState, current_ctx: dict | None = None
) -> dict:
    """
    Planner 失败时的降级路由。

    使用关键词匹配用户最新消息，直接路由到最相关的 Agent。
    同时也在计划为空时被调用。
    """
    ctx = current_ctx if current_ctx is not None else make_shared_context()
    messages = state.get("messages", [])
    user_text = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_text = str(msg.content).lower()
            break

    # 关键词路由
    if any(
        kw in user_text
        for kw in ["文献", "literature", "paper", "search", "搜索"]
    ):
        agent = "literature_agent"
    elif any(
        kw in user_text
        for kw in ["设计", "design", "linker", "连接子"]
    ):
        agent = "linker_agent"
    elif any(
        kw in user_text
        for kw in ["ph", "稳定性", "stable", "溶酶体", "血液"]
    ):
        agent = "ph_agent"
    elif any(
        kw in user_text
        for kw in ["性质", "property", "logp", "qed", "计算", "毒"]
    ):
        agent = "property_agent"
    else:
        # 默认: 先从 property check 开始（最安全）
        agent = "property_agent"

    return {
        "shared_context": {
            **ctx,
            "plan": [
                {
                    "agent": agent,
                    "reason": "Fallback routing (Planner failed or empty plan)",
                }
            ],
            "plan_index": 1,
            "execution_log": ctx.get("execution_log", [])
            + [f"Planner: FAILED, fallback keyword routing → {agent}"],
        },
        "next": agent,
    }


# ═══════════════════════════════════════════════════════════════
# Routing
# ═══════════════════════════════════════════════════════════════


def _route_supervisor(state: AgentState) -> str:
    """
    条件路由函数: 从 state['next'] 读取 supervisor 的决策。

    返回值对应的路由目标:
      - "property_agent" / "ph_agent" / "linker_agent" / "literature_agent"
        → 对应专长节点
      - "__synthesize__" → supervisor 节点（进入综合阶段）
      - "FINISH" / 非法值 → END
    """
    next_val = state.get("next", "FINISH")

    valid_routes = (
        "property_agent",
        "ph_agent",
        "linker_agent",
        "literature_agent",
        "__synthesize__",
        "FINISH",
    )
    return next_val if next_val in valid_routes else "FINISH"


# ═══════════════════════════════════════════════════════════════
# Graph Construction
# ═══════════════════════════════════════════════════════════════


def create_multi_agent_graph() -> Any:
    """
    构建三阶段 Supervisor 多 Agent 图。

    架构:
        START → supervisor (Planner)
          → [Dispatcher → Specialist → supervisor] 循环
          → supervisor (Synthesizer)
          → FINISH

    注意: "__synthesize__" 路由回 supervisor 节点，
    触发 SYNTHESIZER 阶段而非再次 PLANNER。

    Returns:
        编译后的 LangGraph Runnable
    """
    workflow = StateGraph(AgentState)

    # ── 节点 ──
    workflow.add_node("supervisor", _create_supervisor_node())
    workflow.add_node("property_agent", property_agent)
    workflow.add_node("ph_agent", ph_agent)
    workflow.add_node("linker_agent", linker_agent)
    workflow.add_node("literature_agent", literature_agent)

    # ── 边 ──
    workflow.add_edge(START, "supervisor")

    # Supervisor 条件路由
    workflow.add_conditional_edges(
        "supervisor",
        _route_supervisor,
        {
            "property_agent": "property_agent",
            "ph_agent": "ph_agent",
            "linker_agent": "linker_agent",
            "literature_agent": "literature_agent",
            "__synthesize__": "supervisor",
            "FINISH": END,
        },
    )

    # 所有专长 Agent 完成后返回 supervisor
    for name in [
        "property_agent",
        "ph_agent",
        "linker_agent",
        "literature_agent",
    ]:
        workflow.add_edge(name, "supervisor")

    # ── 编译 ──
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


# ═══════════════════════════════════════════════════════════════
# Single Agent (backward compatibility)
# ═══════════════════════════════════════════════════════════════


def create_single_agent_graph() -> Any:
    """
    构建单 Agent ReAct 图，保持向后兼容。

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
# Convenience
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
        mode: "single" (ReAct) 或 "multi" (Three-Phase Supervisor, 默认)

    Returns:
        (graph, config) — 直接传给 graph.invoke(state, config)
    """
    graph = (
        create_single_agent_graph()
        if mode == "single"
        else create_multi_agent_graph()
    )

    config = {"configurable": {"thread_id": thread_id}}
    return graph, config
