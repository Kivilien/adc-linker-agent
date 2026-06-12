"""
配置管理模块

加载 .env 文件中的环境变量，提供类型安全的配置访问。
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


# 加载项目根目录的 .env 文件
def _find_project_root() -> Path:
    """向上查找项目根目录（包含 pyproject.toml 或 .env 的目录）"""
    current = Path(__file__).resolve().parent
    for _ in range(10):  # 最多向上找 10 层
        if (current / ".env").exists() or (current / "pyproject.toml").exists():
            return current
        current = current.parent
    # Fallback: 使用当前文件所在的包根目录
    return Path(__file__).resolve().parent.parent.parent


PROJECT_ROOT = _find_project_root()
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    """应用配置

    使用方式:
        from adc_linker_agent.utils.config import get_config
        config = get_config()
        print(config.anthropic_api_key)  # 从 .env 加载
    """

    def __init__(self) -> None:
        self.anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
        self.llm_model: str = os.getenv("LLM_MODEL", "claude-3-5-haiku-20241022")
        self.synthesis_model: str = os.getenv(
            "SYNTHESIS_MODEL", "claude-3-5-sonnet-20241022"
        )
        self.mcp_host: str = os.getenv("MCP_HOST", "0.0.0.0")
        self.mcp_port: int = int(os.getenv("MCP_PORT", "8000"))
        self.project_root: Path = PROJECT_ROOT
        self.data_dir: Path = PROJECT_ROOT / "data"

    def validate(self) -> list[str]:
        """检查必要的配置是否齐全。返回缺失项的列表。"""
        missing = []
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY (set in .env)")
        return missing


@lru_cache(maxsize=1)
def get_config() -> Config:
    """获取配置的单例（lru_cache 确保只初始化一次）"""
    return Config()
