"""
专长 Agent 定义（架构重写 v2）

每个专长 Agent 现在写入双通道：
  1. messages: AIMessage（供 LLM 对话上下文）
  2. shared_context.<domain>_data: 结构化数据（供 UI 渲染 + 综合器读取）

容错机制（保留）:
  - LLM 调用重试：指数退避，最多 3 次
  - 工具执行重试：区分瞬时错误和永久错误
  - 上下文裁剪：token 超过 100k 时保留 system + 最后 8 条消息
"""

import json
import time
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from adc_linker_agent.agent.model_factory import create_model
from adc_linker_agent.agent.state import AgentState
from adc_linker_agent.agent.tools import (
    ALL_TOOLS,
    calculate_properties,
    check_lipinski,
    check_toxicity,
    design_linker,
    predict_ph_stability,
    predict_ph_stability_all_phases,
    search_linker_scaffolds,
    search_literature,
    validate_smiles,
)

# ─── 工具集分配（最小权限原则） ───

PROPERTY_TOOLS = [
    validate_smiles,
    calculate_properties,
    check_lipinski,
    check_toxicity,
]
PH_TOOLS = [predict_ph_stability, predict_ph_stability_all_phases]
LINKER_TOOLS = ALL_TOOLS
LITERATURE_TOOLS = [search_literature]


# ─── 专长 Agent 系统提示 ───

PROPERTY_SYSTEM_PROMPT = """You are the Molecular Property Specialist.

Your ONLY job: calculate and interpret molecular properties.

Tools:
- validate_smiles: verify SMILES validity
- calculate_properties: compute 8 key descriptors (LogP, QED, SAS, TPSA, etc.)
- check_lipinski: Lipinski's Rule of Five evaluation
- check_toxicity: PAINS/Brenk toxicity alerts (CRITICAL for safety)

Workflow:
1. ALWAYS validate SMILES first
2. Calculate properties + check_lipinski + check_toxicity in parallel
3. Report results

Toxicity rules:
- PAINS alert → false-positive bioactive compound, NOT developable
- Brenk alert → potentially toxic/reactive/unstable substructure
- If has_alerts=True: list each alert by name with a one-sentence explanation.
  If clean: one line, no paragraph.

Output style:
- No ## headings, no markdown tables for single molecules
- No decorative emoji
- Single molecule: indent list of properties, judgment line at end
- Do NOT explain normal values — scientists know them"""

PH_SYSTEM_PROMPT = """You are the pH Stability Specialist.

Your ONLY job: analyze pH-dependent stability of linker molecules.

Tools:
- predict_ph_stability: check stability at a specific pH
- predict_ph_stability_all_phases: check all 6 physiological pH phases

Workflow:
1. Call predict_ph_stability_all_phases
2. Check library_coverage:
   - < 1.0: list uncovered groups
   - = 0: state "无已知 pH 敏感官能团"
3. Flag: blood-unstable = toxicity risk; lysosome-stable = ineffective

ADC linker rule: stable at blood pH 7.4, cleaved at lysosome pH 5.0-5.5.

Output style:
- One line per phase with status
- Do NOT annotate every phase — only unstable or borderline ones
- Library gaps: one line"""

LINKER_SYSTEM_PROMPT = """You are the ADC Linker Design Specialist.

Your ONLY job: design, evaluate, and optimize ADC linker candidates.

CRITICAL RULES:
1. NEVER INVENT SMILES. Only use SMILES from tools or user input.
2. If validate_smiles returns invalid, STOP.
3. Do not call the same tool with the same arguments more than twice.

Tools: validate_smiles, calculate_properties, check_lipinski, check_toxicity,
       predict_ph_stability, predict_ph_stability_all_phases,
       search_linker_scaffolds, design_linker, search_literature

Call independent tools in parallel when possible.

Output style:
- 3+ candidates: comparison table (this is the ONLY valid use of tables)
- Single candidate: indent list, no table
- Top recommendation: one line with name, score, SMILES
- No ## headings, no decorative emoji"""

LITERATURE_SYSTEM_PROMPT = """You are the ADC Literature Research Specialist.

Your ONLY job: search and verify claims against published literature.

Tool: search_literature

Workflow (2 rounds MAX):
1. Round 1: Construct 2-3 targeted English queries → call ALL in ONE response
2. If results found: STOP immediately, summarize findings
3. If NO results (round 1 empty): ONE more round with broader/alternative terms, then STOP
4. NEVER search more than 2 rounds

Critical rules:
- NEVER fabricate titles, authors, or DOIs
- No results → state "未找到相关文献" and STOP
- Always include DOI link (https://doi.org/...)
- Distinguish: direct evidence / review mention / no evidence

Output style:
- Each paper: one line. Number. Authors. *Title*. Journal Year. DOI
- No ## headings, no tables for literature results
- No results: one sentence with suggestion for alternative terms"""


# ─── 容错与上下文管理 ───

_LLM_MAX_RETRIES = 3
_LLM_BACKOFF_BASE = 2.0
_TOOL_MAX_RETRIES = 2
_MAX_CONTEXT_EST_TOKENS = 100_000
_TRIM_KEEP_LAST = 8

_TRANSIENT_PATTERNS = (
    "timeout", "connection", "rate limit", "rate_limit",
    "503", "504", "429", "temporary", "throttl", "unavailable",
)


def _estimate_tokens(messages: list) -> int:
    """粗略估计消息列表的 token 数（2 chars ≈ 1 token）。"""
    total = 0
    for m in messages:
        content = str(getattr(m, "content", ""))
        total += len(content) // 2
    return total


def _call_model_with_retry(model, messages: list, name: str = "") -> Any:
    """带指数退避的 LLM 调用重试。"""
    last_error = None
    for attempt in range(_LLM_MAX_RETRIES):
        try:
            return model.invoke(messages)
        except Exception as e:
            last_error = e
            if attempt < _LLM_MAX_RETRIES - 1:
                delay = _LLM_BACKOFF_BASE ** attempt
                print(
                    f"[{name or 'specialist'}] LLM call attempt "
                    f"{attempt + 1} failed ({type(e).__name__}), "
                    f"retrying in {delay:.0f}s..."
                )
                time.sleep(delay)
    raise last_error


def _execute_tool_with_retry(func, args: dict, name: str = "") -> Any:
    """工具执行重试，仅对瞬时错误重试。"""
    for attempt in range(_TOOL_MAX_RETRIES):
        try:
            return func.invoke(args)
        except Exception as e:
            msg = str(e).lower()
            is_transient = any(p in msg for p in _TRANSIENT_PATTERNS)
            if is_transient and attempt < _TOOL_MAX_RETRIES - 1:
                delay = _LLM_BACKOFF_BASE ** attempt
                print(
                    f"[{name or 'tool'}] transient error on attempt "
                    f"{attempt + 1} — retrying in {delay:.0f}s..."
                )
                time.sleep(delay)
                continue
            raise


def _trim_context(messages: list) -> list:
    """上下文裁剪：token 超限时保留 system + 最后 N 条消息。"""
    if _estimate_tokens(messages) < _MAX_CONTEXT_EST_TOKENS:
        return messages
    if len(messages) <= _TRIM_KEEP_LAST + 1:
        return messages
    trim_from = max(1, len(messages) - _TRIM_KEEP_LAST)
    return [messages[0]] + messages[trim_from:]


# ─── 工具名 → 函数映射 ───

_TOOL_MAP = {
    "validate_smiles": validate_smiles,
    "calculate_properties": calculate_properties,
    "check_lipinski": check_lipinski,
    "check_toxicity": check_toxicity,
    "predict_ph_stability": predict_ph_stability,
    "predict_ph_stability_all_phases": predict_ph_stability_all_phases,
    "search_linker_scaffolds": search_linker_scaffolds,
    "design_linker": design_linker,
    "search_literature": search_literature,
}


# ─── 工具执行（返回 ToolMessage + 原始结果） ───


def _execute_tool_calls(
    ai_message: AIMessage,
) -> tuple[list[ToolMessage], dict[str, Any]]:
    """
    执行 AIMessage 中的 tool_calls，返回 ToolMessage 列表和原始结果。

    返回:
      (tool_messages, raw_results)
      - tool_messages: 用于 LLM 上下文的 ToolMessage 列表
      - raw_results: {tool_name: result_dict} 用于提取结构化数据

    区分瞬时/永久错误，瞬时错误自动重试。
    """
    tool_messages: list[ToolMessage] = []
    raw_results: dict[str, Any] = {}

    for tc in ai_message.tool_calls:
        tool_name = tc.get("name", "")
        tool_args = tc.get("args", {})
        call_id = tc.get("id", "unknown")

        func = _TOOL_MAP.get(tool_name)
        if func is None:
            content = f"Error: unknown tool '{tool_name}'"
            raw_results[tool_name] = {"error": content}
        else:
            try:
                result = _execute_tool_with_retry(
                    func, tool_args, name=tool_name
                )
                raw_results[tool_name] = result
                content = json.dumps(
                    result, ensure_ascii=False, indent=2
                )
            except Exception as e:
                content = f"Error executing {tool_name}: {e}"
                raw_results[tool_name] = {"error": str(e)}

        tool_messages.append(
            ToolMessage(content=content, tool_call_id=call_id)
        )

    return tool_messages, raw_results


# ─── 结构化数据提取函数（每个 specialist 不同） ───


def _extract_property_data(raw_results: dict[str, Any]) -> dict:
    """从工具结果中提取性质数据 → shared_context.property_data"""
    smiles = ""
    if "validate_smiles" in raw_results:
        smiles = raw_results["validate_smiles"].get("smiles", "")

    props = None
    if "calculate_properties" in raw_results:
        props = raw_results["calculate_properties"]
        if "error" not in props:
            props = {k: v for k, v in props.items() if k != "smiles"}

    lipinski = raw_results.get("check_lipinski")
    toxicity = raw_results.get("check_toxicity")

    return {
        "smiles": smiles,
        "properties": props,
        "lipinski": lipinski,
        "toxicity": toxicity,
    }


def _extract_ph_data(raw_results: dict[str, Any]) -> dict:
    """从工具结果中提取 pH 数据 → shared_context.ph_data"""
    # predict_ph_stability_all_phases 返回 {phase: {result...}}
    all_phases = raw_results.get("predict_ph_stability_all_phases", {})
    if all_phases and "error" not in all_phases:
        return all_phases

    # 降级：使用单个 pH 检测结果
    single = raw_results.get("predict_ph_stability", {})
    if single and "error" not in single:
        return {"single_check": single}

    return {}


def _extract_design_report(raw_results: dict[str, Any]) -> dict | None:
    """从工具结果中提取设计报告 → shared_context.design_report"""
    design = raw_results.get("design_linker", {})
    if "_report" in design:
        return design["_report"]
    return None


def _extract_literature_data(raw_results: dict[str, Any]) -> dict:
    """从工具结果中提取文献数据 → shared_context.literature_data"""
    all_papers: list[dict] = []
    all_queries: list[str] = []

    # 汇总所有 search_literature 调用的结果
    for tool_name, result in raw_results.items():
        if tool_name == "search_literature" and isinstance(result, dict):
                all_queries.append(result.get("query", ""))
                papers = result.get("papers", [])
                if isinstance(papers, list):
                    all_papers.extend(papers)

    return {
        "papers": all_papers,
        "queries": all_queries,
        "total_found": len(all_papers),
    }


# ─── 专长 Agent 工厂函数 ───


def create_specialist_node(
    name: str,
    system_prompt: str,
    tools: list[Any],
    context_key: str,
    extract_fn: Callable[[dict[str, Any]], Any],
) -> Any:
    """
    创建一个专长 Agent 节点（架构 v2）。

    相比旧版的关键变更：
      - 工具执行后保留原始结果（raw_results）
      - 使用 extract_fn 提取结构化数据写入 shared_context
      - 返回双通道：messages（AIMessage）+ shared_context 更新

    Args:
        name: Agent 名称（用于日志和路由）
        system_prompt: 专长 Agent 的系统提示
        tools: 该 Agent 可用的工具列表（最小权限分配）
        context_key: shared_context 中的键名（如 "property_data"）
        extract_fn: 从 raw_results 提取结构化数据的函数

    Returns:
        LangGraph 节点函数
    """
    model = create_model(temperature=0.2, tools=tools)

    def specialist_node(state: AgentState) -> dict:
        """专长 Agent 节点: 执行任务，写入双通道。"""
        messages = list(state["messages"])

        # 注入系统提示
        system_msg = SystemMessage(content=system_prompt)
        request_messages = [system_msg] + messages

        # 迭代上限
        max_iterations = min(max(len(tools) * 2, 4), 16)
        tool_calls_made = 0

        # 累积所有工具调用结果（用于最终数据提取）
        all_raw_results: dict[str, Any] = {}

        for _iteration in range(max_iterations):
            # 上下文裁剪
            request_messages = _trim_context(request_messages)

            # LLM 调用（带重试）
            try:
                response = _call_model_with_retry(
                    model, request_messages, name=name
                )
            except Exception as e:
                return {
                    "messages": [
                        AIMessage(
                            content=(
                                f"[{name}] LLM 调用失败"
                                f"（{_LLM_MAX_RETRIES} 次重试后）: {e}"
                            )
                        )
                    ],
                    "shared_context": {
                        "errors": [
                            {
                                "agent": name,
                                "phase": "llm_call",
                                "error": str(e),
                            }
                        ]
                    },
                }

            # 有 tool_calls → 执行并继续
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_messages, raw_results = _execute_tool_calls(response)
                # 累积原始结果
                all_raw_results.update(raw_results)
                request_messages.append(response)
                request_messages.extend(tool_messages)
                tool_calls_made += len(response.tool_calls)
                continue

            # 无 tool_calls → 最终回复
            # 提取结构化数据
            try:
                structured_data = extract_fn(all_raw_results)
            except Exception:
                structured_data = None

            # 构建共享上下文更新
            shared_update: dict = {}
            if structured_data is not None:
                shared_update[context_key] = structured_data

            return {
                "messages": [response],
                "shared_context": shared_update,
            }

        # 达到最大迭代次数 → 强制返回
        # 即使超轮次，仍尝试提取已有的结构化数据
        try:
            structured_data = extract_fn(all_raw_results)
        except Exception:
            structured_data = None

        shared_update: dict = {}
        if structured_data is not None:
            shared_update[context_key] = structured_data
        shared_update["errors"] = [
            {
                "agent": name,
                "phase": "max_iterations",
                "error": (
                    f"已执行 {tool_calls_made} 次工具调用"
                    f"（已达 {max_iterations} 轮上限）"
                ),
            }
        ]

        return {
            "messages": [
                AIMessage(
                    content=(
                        f"[{name}] 已执行 {tool_calls_made} 次工具调用"
                        f"（已达 {max_iterations} 轮迭代上限）。"
                    )
                )
            ],
            "shared_context": shared_update,
        }

    specialist_node.__name__ = name
    specialist_node.__doc__ = f"{name}: {system_prompt[:100]}..."
    return specialist_node


# ─── 四个专长 Agent ───

property_agent = create_specialist_node(
    name="property_agent",
    system_prompt=PROPERTY_SYSTEM_PROMPT,
    tools=PROPERTY_TOOLS,
    context_key="property_data",
    extract_fn=_extract_property_data,
)

ph_agent = create_specialist_node(
    name="ph_agent",
    system_prompt=PH_SYSTEM_PROMPT,
    tools=PH_TOOLS,
    context_key="ph_data",
    extract_fn=_extract_ph_data,
)

linker_agent = create_specialist_node(
    name="linker_agent",
    system_prompt=LINKER_SYSTEM_PROMPT,
    tools=LINKER_TOOLS,
    context_key="design_report",
    extract_fn=_extract_design_report,
)

literature_agent = create_specialist_node(
    name="literature_agent",
    system_prompt=LITERATURE_SYSTEM_PROMPT,
    tools=LITERATURE_TOOLS,
    context_key="literature_data",
    extract_fn=_extract_literature_data,
)
