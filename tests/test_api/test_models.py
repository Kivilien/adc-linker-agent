"""
测试 API 数据模型（Pydantic v2）
"""

import pytest
from pydantic import ValidationError

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


class TestAgentQueryRequest:
    """测试查询请求模型"""

    def test_minimal_request(self):
        """最小有效请求"""
        req = AgentQueryRequest(message="计算苯的性质")
        assert req.message == "计算苯的性质"
        assert req.thread_id == "default"
        assert req.mode == "multi"

    def test_full_request(self):
        """完整请求"""
        req = AgentQueryRequest(
            message="设计连接子",
            thread_id="session_123",
            mode="single",
            model_name="claude-sonnet-4-6",
        )
        assert req.thread_id == "session_123"
        assert req.mode == "single"

    def test_empty_message_rejected(self):
        """空消息应该被拒绝"""
        with pytest.raises(ValidationError):
            AgentQueryRequest(message="")

    def test_invalid_mode_rejected(self):
        """无效 mode 被拒绝"""
        with pytest.raises(ValidationError):
            AgentQueryRequest(message="test", mode="invalid_mode")

    def test_valid_modes_accepted(self):
        """single 和 multi 都被接受"""
        for mode in ["single", "multi"]:
            req = AgentQueryRequest(message="test", mode=mode)  # type: ignore[arg-type]
            assert req.mode == mode

    def test_default_values(self):
        """默认值正确"""
        req = AgentQueryRequest(message="test")
        assert req.thread_id == "default"
        assert req.mode == "multi"
        assert req.model_name == "claude-fable-5"


class TestAgentQueryResponse:
    """测试查询响应模型"""

    def test_empty_response(self):
        resp = AgentQueryResponse(thread_id="test")
        assert resp.thread_id == "test"
        assert resp.messages == []
        assert resp.tool_calls_made == 0

    def test_response_with_messages(self):
        msg = AgentMessage(role="assistant", content="Hello")
        resp = AgentQueryResponse(
            thread_id="test",
            messages=[msg],
            tool_calls_made=3,
            elapsed_ms=1234.5,
        )
        assert len(resp.messages) == 1
        assert resp.tool_calls_made == 3
        assert resp.elapsed_ms == 1234.5

    def test_serialization(self):
        resp = AgentQueryResponse(
            thread_id="abc",
            tool_calls_made=1,
            elapsed_ms=500.0,
        )
        data = resp.model_dump()
        assert data["thread_id"] == "abc"
        assert data["tool_calls_made"] == 1


class TestHealthResponse:
    """测试健康检查响应"""

    def test_default_values(self):
        resp = HealthResponse()
        assert resp.status == "ok"
        assert resp.version == "1.1.0"
        assert resp.agent_mode == "multi"
        assert resp.tools_available == 9

    def test_custom_status(self):
        resp = HealthResponse(status="no_api_key")
        assert resp.status == "no_api_key"


class TestToolsListResponse:
    """测试工具列表响应"""

    def test_empty_tools(self):
        resp = ToolsListResponse(tools=[], count=0)
        assert resp.tools == []
        assert resp.count == 0

    def test_with_tools(self):
        tools = [
            ToolInfo(name="tool_a", description="desc a"),
            ToolInfo(name="tool_b", description="desc b"),
        ]
        resp = ToolsListResponse(tools=tools, count=2)
        assert len(resp.tools) == 2
        assert resp.count == 2


class TestErrorResponse:
    """测试错误响应"""

    def test_basic_error(self):
        resp = ErrorResponse(error="something went wrong")
        assert resp.error == "something went wrong"
        assert resp.timestamp is not None


class TestToolCallInfo:
    """测试工具调用信息"""

    def test_minimal(self):
        tc = ToolCallInfo(name="validate_smiles", args={"smiles": "c1ccccc1"})
        assert tc.name == "validate_smiles"
        assert tc.args == {"smiles": "c1ccccc1"}
        assert tc.result is None

    def test_with_result(self):
        tc = ToolCallInfo(
            name="calculate_properties",
            args={"smiles": "c1ccccc1"},
            result={"logp": 1.69, "qed": 0.443},
        )
        assert tc.result is not None
        assert tc.result["logp"] == 1.69
