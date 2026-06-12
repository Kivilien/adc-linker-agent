"""
API 数据模型（Pydantic v2）

定义 FastAPI 端点的请求/响应结构。
所有模型使用 Pydantic v2 的 model_validate 进行自动校验。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ─── 请求模型 ───


class AgentQueryRequest(BaseModel):
    """
    Agent 查询请求。

    Example:
        {
            "message": "计算阿司匹林的所有分子性质",
            "thread_id": "session_abc",
            "mode": "multi"
        }
    """

    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="用户输入的自然语言查询",
        examples=["计算苯的分子性质", "设计一个 pH 5.5 裂解的连接子"],
    )
    thread_id: str = Field(
        default="default",
        description="对话线程 ID（同一线程共享历史记忆）",
    )
    mode: str = Field(
        default="multi",
        pattern="^(single|multi)$",
        description="Agent 模式：single (Week 4) 或 multi (Week 5)",
    )
    model_name: str = Field(
        default="claude-fable-5",
        description="Anthropic 模型名称",
    )


# ─── 响应模型 ───


class ToolCallInfo(BaseModel):
    """单个工具调用的信息"""

    name: str = Field(..., description="工具名称")
    args: dict = Field(default_factory=dict, description="工具参数")
    result: Optional[dict] = Field(None, description="工具返回结果")


class AgentMessage(BaseModel):
    """Agent 回复中的单条消息"""

    role: str = Field(..., description="消息角色：assistant / tool")
    content: str = Field(..., description="消息文本内容")
    tool_calls: list[ToolCallInfo] = Field(
        default_factory=list, description="该消息中包含的工具调用"
    )


class AgentQueryResponse(BaseModel):
    """
    Agent 查询响应。

    Example:
        {
            "thread_id": "session_abc",
            "messages": [...],
            "tool_calls_made": 3,
            "elapsed_ms": 1234
        }
    """

    thread_id: str = Field(..., description="对话线程 ID")
    messages: list[AgentMessage] = Field(
        default_factory=list, description="本次查询产生的消息列表"
    )
    tool_calls_made: int = Field(
        default=0, description="本次查询中工具调用总次数"
    )
    elapsed_ms: float = Field(
        default=0.0, description="处理耗时（毫秒）"
    )


class HealthResponse(BaseModel):
    """健康检查响应"""

    status: str = Field(default="ok", description="服务状态")
    version: str = Field(default="0.1.0", description="API 版本")
    agent_mode: str = Field(default="multi", description="当前 Agent 模式")
    tools_available: int = Field(default=7, description="可用工具数")


class ToolInfo(BaseModel):
    """工具信息"""

    name: str
    description: str


class ToolsListResponse(BaseModel):
    """工具列表响应"""

    tools: list[ToolInfo]
    count: int


class ErrorResponse(BaseModel):
    """错误响应"""

    error: str = Field(..., description="错误描述")
    detail: Optional[str] = Field(None, description="详细错误信息")
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="错误时间戳",
    )
