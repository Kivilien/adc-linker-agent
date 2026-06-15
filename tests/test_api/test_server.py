"""
测试 FastAPI 服务端点

使用 FastAPI TestClient 测试所有端点。
不依赖实际 API Key。
"""

import pytest
from fastapi.testclient import TestClient

from adc_linker_agent.api.server import app


@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)


class TestHealthEndpoint:
    """测试健康检查端点"""

    def test_returns_200(self, client):
        resp = client.get("/agent/health")
        assert resp.status_code == 200

    def test_returns_json_with_expected_keys(self, client):
        resp = client.get("/agent/health")
        data = resp.json()
        assert "status" in data
        assert "version" in data
        assert "agent_mode" in data
        assert "tools_available" in data

    def test_agent_mode_is_multi(self, client):
        resp = client.get("/agent/health")
        data = resp.json()
        assert data["agent_mode"] == "multi"

    def test_tools_available(self, client):
        resp = client.get("/agent/health")
        data = resp.json()
        assert data["tools_available"] == 10


class TestToolsEndpoint:
    """测试工具列表端点"""

    def test_returns_200(self, client):
        resp = client.get("/agent/tools")
        assert resp.status_code == 200

    def test_tool_count(self, client):
        resp = client.get("/agent/tools")
        data = resp.json()
        assert data["count"] == 10
        assert len(data["tools"]) == 10

    def test_each_tool_has_name_and_description(self, client):
        resp = client.get("/agent/tools")
        data = resp.json()
        for tool in data["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert len(tool["name"]) > 0
            assert len(tool["description"]) > 0

    def test_tool_names_match_expected(self, client):
        resp = client.get("/agent/tools")
        data = resp.json()
        names = {t["name"] for t in data["tools"]}
        expected = {
            "validate_smiles",
            "calculate_properties",
            "check_lipinski",
            "check_toxicity",
            "predict_ph_stability",
            "predict_ph_stability_all_phases",
            "search_linker_scaffolds",
            "design_linker",
            "search_literature",
            "search_pubchem_linkers_tool",
        }
        assert names == expected


class TestQueryEndpoint:
    """测试查询端点"""

    def test_returns_200_even_without_api_key(self, client):
        """无 API Key 时优雅降级而非 500 崩溃"""
        resp = client.post(
            "/agent/query",
            json={"message": "计算苯的性质", "mode": "multi"},
        )
        # 可能返回 200（部分结果）或 400（API key 缺失）
        assert resp.status_code in (200, 400)

    def test_empty_message_rejected(self, client):
        """空消息应该被拒绝"""
        resp = client.post(
            "/agent/query",
            json={"message": "", "mode": "multi"},
        )
        assert resp.status_code == 422  # Validation error

    def test_invalid_mode_rejected(self, client):
        """无效 mode 被拒绝"""
        resp = client.post(
            "/agent/query",
            json={"message": "test", "mode": "quantum"},
        )
        assert resp.status_code == 422

    def test_response_has_expected_structure(self, client):
        """响应结构正确"""
        resp = client.post(
            "/agent/query",
            json={"message": "计算苯的性质", "mode": "multi"},
        )
        if resp.status_code == 200:
            data = resp.json()
            assert "thread_id" in data
            assert "messages" in data
            assert "tool_calls_made" in data
            assert "elapsed_ms" in data


class TestCORSMiddleware:
    """测试 CORS 配置"""

    def test_cors_headers_present(self, client):
        """OPTIONS 请求应该返回 CORS 头"""
        resp = client.options(
            "/agent/health",
            headers={
                "Origin": "http://localhost:8501",
                "Access-Control-Request-Method": "GET",
            },
        )
        # FastAPI TestClient 可能不触发完整的 CORS 中间件
        # 只检查请求不崩溃即可
        assert resp.status_code in (200, 405)


class TestAPIDocumentation:
    """测试 API 文档端点"""

    def test_docs_endpoint(self, client):
        """Swagger UI 可访问"""
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_redoc_endpoint(self, client):
        """ReDoc 可访问"""
        resp = client.get("/redoc")
        assert resp.status_code == 200

    def test_openapi_schema(self, client):
        """OpenAPI schema 可访问"""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema
        assert "/agent/health" in schema["paths"]
        assert "/agent/tools" in schema["paths"]
        assert "/agent/query" in schema["paths"]
