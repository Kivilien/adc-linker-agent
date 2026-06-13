"""
配置管理模块

加载 .env 文件中的环境变量，提供类型安全的配置访问。
支持 Anthropic 和 DeepSeek（OpenAI 兼容）两种 LLM 提供商。
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


def _find_project_root() -> Path:
    """向上查找项目根目录（包含 pyproject.toml 或 .env 的目录）"""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / ".env").exists() or (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return Path(__file__).resolve().parent.parent.parent


PROJECT_ROOT = _find_project_root()
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    """应用配置

    支持两种 LLM 提供商:
      - Anthropic: 设置 ANTHROPIC_API_KEY
      - DeepSeek: 设置 DEEPSEEK_API_KEY（OpenAI 兼容 API）

    优先级: DEEPSEEK_API_KEY > ANTHROPIC_API_KEY
    """

    def __init__(self) -> None:
        # ─── API Keys ───
        self.anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
        self.deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
        self.deepseek_base_url: str = os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        )

        # ─── 模型配置 ───
        self.llm_provider: str = os.getenv(
            "LLM_PROVIDER",
            "deepseek" if self.deepseek_api_key else "anthropic",
        )
        self.llm_model: str = os.getenv(
            "LLM_MODEL",
            "deepseek-chat" if self.deepseek_api_key else "claude-fable-5",
        )
        self.synthesis_model: str = os.getenv(
            "SYNTHESIS_MODEL",
            "deepseek-reasoner" if self.deepseek_api_key else "claude-fable-5",
        )

        # ─── API 认证 ───
        self.api_key: str = os.getenv("ADC_API_KEY", "")
        # 审计日志路径
        self.audit_log_path: Path = PROJECT_ROOT / "logs" / "audit.jsonl"

        # ─── 服务配置 ───
        self.mcp_host: str = os.getenv("MCP_HOST", "0.0.0.0")
        self.mcp_port: int = int(os.getenv("MCP_PORT", "8000"))
        self.project_root: Path = PROJECT_ROOT
        self.data_dir: Path = PROJECT_ROOT / "data"
        self.ph_labile_groups_path: Path = self.data_dir / "ph_labile_groups.yaml"

    @property
    def has_api_key(self) -> bool:
        """是否有任何可用的 API Key"""
        return bool(self.anthropic_api_key or self.deepseek_api_key)

    @property
    def effective_api_key(self) -> str:
        """返回实际使用的 API Key"""
        return self.deepseek_api_key or self.anthropic_api_key

    def validate(self) -> list[str]:
        """检查必要的配置是否齐全。"""
        missing = []
        if not self.has_api_key:
            missing.append(
                "DEEPSEEK_API_KEY or ANTHROPIC_API_KEY (set in .env)"
            )
        return missing


@lru_cache(maxsize=1)
def get_config() -> Config:
    """获取配置的单例"""
    return Config()
