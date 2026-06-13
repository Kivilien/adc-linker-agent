"""
API 路由定义

提供 REST 端点供外部客户端调用 ADC Linker Agent。

端点:
  POST /agent/query  — 向 Agent 发送查询（需认证）
  GET  /health       — 健康检查
  GET  /tools        — 列出可用工具
"""

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_core.messages import HumanMessage

from adc_linker_agent.agent.graph import get_agent
from adc_linker_agent.agent.state import make_shared_context
from adc_linker_agent.agent.tools import ALL_TOOLS
from adc_linker_agent.api.auth import verify_api_key
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
from adc_linker_agent.utils.audit import write_audit_log
from adc_linker_agent.utils.validators import MEDICAL_DISCLAIMER, validate_query_input

router = APIRouter(prefix="/agent", tags=["agent"])

# ─── 简易速率限制（内存实现，适合单机 demo） ───
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 60  # 60 秒窗口
_RATE_LIMIT_MAX = 30     # 每窗口最多 30 请求


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
        disclaimer=MEDICAL_DISCLAIMER,
        literature_data=result.get("shared_context", {}).get("literature_data"),
        design_report=result.get("shared_context", {}).get("design_report"),
    )


@router.post(
    "/query",
    response_model=AgentQueryResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="向 ADC Linker Agent 发送查询",
    description="""
    向 Multi-Agent 系统发送自然语言查询。

    Agent 会自动路由到合适的专长 Agent（Property/PH/Linker/LiteratureAgent）
    并返回综合结果。支持单轮和多轮对话。

    **认证**: 需要在请求头中携带 `X-API-Key: <your-key>`。
    若 .env 中未配置 ADC_API_KEY，则认证可选。
    """,
)
async def agent_query(
    api_request: Request,
    request: AgentQueryRequest,
    api_key: str = Depends(verify_api_key),
):
    """处理 Agent 查询请求。"""
    client_ip = api_request.client.host if api_request.client else "unknown"
    user_agent = api_request.headers.get("User-Agent", "")
    start_time = time.perf_counter()

    # ─── 输入验证 ───
    error = validate_query_input(request.message)
    if error:
        write_audit_log(
            client_ip=client_ip,
            thread_id=request.thread_id,
            query=request.message,
            status="validation_error",
            elapsed_ms=(time.perf_counter() - start_time) * 1000,
            user_agent=user_agent,
        )
        raise HTTPException(status_code=400, detail=error)

    # ─── 速率限制 ───
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW
    _rate_limit_store[client_ip] = [
        t for t in _rate_limit_store[client_ip] if t > window_start
    ]
    # 清理空列表的键防止内存泄漏
    if not _rate_limit_store[client_ip]:
        del _rate_limit_store[client_ip]
    if len(_rate_limit_store.get(client_ip, [])) >= _RATE_LIMIT_MAX:
        write_audit_log(
            client_ip=client_ip,
            thread_id=request.thread_id,
            query=request.message,
            status="rate_limited",
            elapsed_ms=(time.perf_counter() - start_time) * 1000,
            user_agent=user_agent,
        )
        raise HTTPException(
            status_code=429,
            detail=f"请求过于频繁，每 {_RATE_LIMIT_WINDOW}s 最多 {_RATE_LIMIT_MAX} 次请求",
        )
    _rate_limit_store[client_ip].append(now)

    try:
        graph, config = get_agent(
            thread_id=request.thread_id,
            mode=request.mode,  # type: ignore[arg-type]
        )

        state = {
            "messages": [HumanMessage(content=request.message)],
            "shared_context": make_shared_context(),
        }

        invoke_start = time.perf_counter()
        result = graph.invoke(state, config)
        elapsed_ms = (time.perf_counter() - invoke_start) * 1000

        response = _extract_messages(result, request.thread_id, elapsed_ms)

        write_audit_log(
            client_ip=client_ip,
            thread_id=request.thread_id,
            query=request.message,
            status="ok",
            elapsed_ms=elapsed_ms,
            tool_calls=response.tool_calls_made,
            user_agent=user_agent,
        )

        return response

    except Exception as e:
        error_msg = str(e).lower()
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        write_audit_log(
            client_ip=client_ip,
            thread_id=request.thread_id,
            query=request.message,
            status="error",
            elapsed_ms=elapsed_ms,
            user_agent=user_agent,
        )

        if "auth" in error_msg or "api_key" in error_msg:
            raise HTTPException(
                status_code=400,
                detail="API key not configured. Set ANTHROPIC_API_KEY in .env file.",
            ) from e
        raise HTTPException(
            status_code=500, detail="Internal server error"
        ) from e


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="健康检查",
)
async def health_check():
    """返回服务状态。"""
    from adc_linker_agent.utils.config import get_config

    config = get_config()
    has_key = config.has_api_key

    return HealthResponse(
        status="ok" if has_key else "no_api_key",
        version="1.1.0",
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
