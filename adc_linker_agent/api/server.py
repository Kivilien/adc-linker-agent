"""
FastAPI 应用主入口

启动方式:
  python -m adc_linker_agent.api.server
  或:
  uvicorn adc_linker_agent.api.server:app --reload --port 8000

API 文档:
  启动后访问 http://localhost:8000/docs (Swagger UI)
  或 http://localhost:8000/redoc (ReDoc)
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from adc_linker_agent.api.routes import router

# ─── 应用生命周期 ───


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用启动和关闭时的钩子。"""
    # 启动
    from adc_linker_agent.utils.config import get_config

    config = get_config()
    missing = config.validate()
    if missing:
        print(f"⚠️  Missing config: {', '.join(missing)}")
        print("  Agent query endpoint will return 400 until .env is configured.")
    else:
        print("✅ API key configured, Agent ready.")

    print("📡 API docs: http://localhost:8000/docs")
    yield
    # 关闭：无需清理


# ─── 创建应用 ───

app = FastAPI(
    title="ADC Linker Agent API",
    description="""
    ADC (Antibody-Drug Conjugate) 连接子智能设计 AI Agent。

    ## 功能
    - **分子性质计算**：LogP, QED, SAS, TPSA, 分子量等 8 个描述符
    - **pH 稳定性分析**：模拟 ADC 在体内全生理阶段的稳定性
    - **连接子骨架搜索**：查询已知 ADC 连接子数据库
    - **Lipinski 五规则**：口服药物相似性评估

    ## 使用方式
    1. `POST /agent/query` — 发送自然语言查询
    2. `GET /agent/tools` — 查看可用工具
    3. `GET /agent/health` — 健康检查
    """,
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS 配置 ───
# 允许 Streamlit (默认端口 8501) 和前端跨域请求

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "http://localhost:8502",
        "http://localhost:3000",
        "http://127.0.0.1:8501",
        "http://127.0.0.1:8502",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

# ─── 注册路由 ───

app.include_router(router)


# ─── 入口点 ───


def main():
    """开发模式启动服务器。"""
    import uvicorn

    uvicorn.run(
        "adc_linker_agent.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
