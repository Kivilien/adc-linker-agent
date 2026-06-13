"""
Agent 状态定义（架构重写 v2）

核心变更（相比旧 MultiAgentState）：
  1. 双通道状态：messages（LLM 对话上下文）+ shared_context（结构化数据仓库）
  2. shared_context 让文献/性质/设计等结构化数据在 LLM 失败后仍然存活
  3. UI 可直接从 shared_context 渲染，不依赖 LLM 文本解析

旧状态（已废弃）：
  MultiAgentState: messages + next
  问题：所有数据封在 AIMessage 文本里，LLM 失败=数据丢失

新状态（当前）：
  AgentState: messages + next + shared_context
  保证：文献结果、性质数据、设计报告始终可被 UI 访问
"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# ─── Agent 路由类型 ───

# 可被路由到的节点名称
SpecialistName = Literal[
    "property_agent",
    "ph_agent",
    "linker_agent",
    "literature_agent",
    "__synthesize__",
    "FINISH",
]

# 可被路由到的专业 Agent（不包括内部节点和 FINISH）
RoutableAgent = Literal[
    "property_agent",
    "ph_agent",
    "linker_agent",
    "literature_agent",
]


# ─── Shared Context 结构 ───


def _merge_context(left: dict, right: dict) -> dict:
    """
    shared_context 的 reducer 函数。

    合并策略：
      - errors 和 execution_log：列表拼接（追加模式）
      - 其他字段：右边覆盖左边（更新模式）

    这保证了各个 specialist 写入的数据互不覆盖，
    而 errors 和日志持续累积。
    """
    merged = {**left}
    for key, value in right.items():
        if key in ("errors", "execution_log") and key in merged:
            # 列表字段：追加
            merged[key] = merged[key] + value
        else:
            # 标量字段：覆盖
            merged[key] = value
    return merged


def make_shared_context() -> dict:
    """
    创建初始 shared_context。

    Returns:
        带有所有默认值的 shared_context dict
    """
    return {
        # Supervisor 计划
        "plan": [],          # list[dict]: 每个元素 {"agent": str, "reason": str}
        "plan_index": 0,     # int: 当前执行的计划步骤索引

        # 领域结果（各 specialist 写入）
        "property_data": None,    # dict | None: MolPropertyCalculator 计算结果
        "ph_data": None,          # dict | None: PhSimulator 全阶段分析结果
        "design_report": None,    # dict | None: DesignReport 序列化数据
        # dict | None: {"papers": [...], "queries": [...], "total_found": int}
        "literature_data": None,

        # 错误与日志
        "errors": [],             # list[dict]: {"agent": str, "phase": str, "error": str}
        "execution_log": [],      # list[str]: 执行步骤日志
    }


# ─── Agent State ───


class AgentState(TypedDict):
    """
    ADC Linker Agent 的全局状态。

    三个通道：
      messages       — LLM 对话历史（LangGraph add_messages reducer）
      next           — 路由决策（下一个要执行的节点）
      shared_context — 结构化数据仓库（_merge_context reducer）

    shared_context 是本次架构重写的核心创新。
    它确保：
      - 文献搜索结果在 LLM 综合失败后仍可被 UI 渲染
      - 分子性质数据不依赖文本解析
      - 设计报告可被 UI 直接渲染为结构化组件
      - 错误日志透明可追溯
    """

    messages: Annotated[list[BaseMessage], add_messages]
    next: str
    shared_context: Annotated[dict, _merge_context]
