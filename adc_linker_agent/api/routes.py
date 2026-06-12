"""
API 路由定义

提供 REST 端点供外部客户端调用 ADC Linker Agent。

端点:
  POST /agent/query  — 向 Agent 发送查询
  GET  /health       — 健康检查
  GET  /tools        — 列出可用工具
"""

import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage

from adc_linker_agent.agent.graph import get_agent
from adc_linker_agent.agent.tools import ALL_TOOLS
from adc_linker_agent.api.models import (
    AgentMessage,
    AgentQueryRequest,
    AgentQueryResponse,
    ErrorResponse,
    HealthResponse,
    ToolCallInfo,
    ToolInfo,
    ToolsListResponse,
)

router = APIRouter(prefix="/agent", tags=["agent"])


def _extract_messages(result: dict, thread_id: str, elapsed_ms: float) -> AgentQueryResponse:
    """从 Agent 执行结果中提取响应消息。"""
    messages: list[AgentMessage] = []
    tool_calls_total = 0

    for msg in result.get("messages", []):
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", "")

        # 提取 tool_calls
        tool_calls: list[ToolCallInfo] = []
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls_total += 1
                tool_calls.append(
                    ToolCallInfo(
                        name=tc.get("name", "unknown"),
                        args=tc.get("args", {}),
                    )
                )

        # 跳过 system message
        if role == "system":
            continue

        messages.append(
            AgentMessage(role=role, content=str(content), tool_calls=tool_calls)
        )

    return AgentQueryResponse(
        thread_id=thread_id,
        messages=messages,
        tool_calls_made=tool_calls_total,
        elapsed_ms=round(elapsed_ms, 1),
    )


@router.post(
    "/query",
    response_model=AgentQueryResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="向 ADC Linker Agent 发送查询",
    description="""
    向 Multi-Agent 系统发送自然语言查询。

    Agent 会自动路由到合适的专长 Agent（Property/PHA/LinkerDesignAgent）
    并返回综合结果。支持单轮和多轮对话。
    """,
)
async def agent_query(request: AgentQueryRequest):
    """处理 Agent 查询请求。"""
    try:
        graph, config = get_agent(
            model_name=request.model_name,
            thread_id=request.thread_id,
            mode=request.mode,  # type: ignore[arg-type]
        )

        state = {"messages": [HumanMessage(content=request.message)]}

        start_time = time.perf_counter()
        result = graph.invoke(state, config)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return _extract_messages(result, request.thread_id, elapsed_ms)

    except Exception as e:
        error_msg = str(e).lower()
        if "auth" in error_msg or "api_key" in error_msg or "key" in error_msg:
            raise HTTPException(
                status_code=400,
                detail="API key not configured. Set ANTHROPIC_API_KEY in .env file.",
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="健康检查",
)
async def health_check():
    """返回服务状态。"""
    from adc_linker_agent.utils.config import get_config

    config = get_config()
    has_key = bool(config.anthropic_api_key)

    return HealthResponse(
        status="ok" if has_key else "no_api_key",
        version="0.1.0",
        agent_mode="multi",
        tools_available=len(ALL_TOOLS),
    )


@router.get(
    "/tools",
    response_model=ToolsListResponse,
    summary="列出所有可用工具",
)
async def list_tools():
    """返回 Agent 可用的所有工具列表。"""
    tools = [
        ToolInfo(name=t.name, description=t.description)
        for t in ALL_TOOLS
    ]
    return ToolsListResponse(tools=tools, count=len(tools))
