"""
API 认证模块

通过 X-API-Key 请求头验证客户端身份。

行为:
  - 若未配置 ADC_API_KEY：认证可选（开发模式），所有请求通过
  - 若已配置 ADC_API_KEY：强制验证 X-API-Key 头，不匹配返回 401

使用方式:
    from adc_linker_agent.api.auth import verify_api_key

    @router.post("/query")
    async def agent_query(..., api_key: str = Depends(verify_api_key)):
        ...
"""

from fastapi import HTTPException, Request
from fastapi import status as http_status

from adc_linker_agent.utils.config import get_config


async def verify_api_key(request: Request) -> str:
    """
    FastAPI 依赖：验证 X-API-Key 请求头。

    若 API Key 未配置（开发模式），跳过验证。
    若配置了 API Key，请求头必须匹配才放行。

    Returns:
        验证通过时返回 "verified"

    Raises:
        HTTPException 401: API Key 缺失或不匹配
    """
    config = get_config()

    # 未配置 API Key → 开发模式，跳过认证
    if not config.api_key:
        return "dev_mode"

    api_key = request.headers.get("X-API-Key", "")
    if not api_key:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header. "
                   "Add your API key in the request header: X-API-Key: <your-key>",
        )

    if api_key != config.api_key:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    return "verified"
