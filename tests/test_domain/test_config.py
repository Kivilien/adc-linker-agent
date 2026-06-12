"""
测试 utils/config.py — 配置管理
"""

from pathlib import Path

from adc_linker_agent.utils.config import Config, get_config, _find_project_root


class TestConfig:
    """测试配置类"""

    def test_config_defaults(self):
        """默认值应该可用"""
        config = Config()
        assert config.mcp_host == "0.0.0.0"
        assert config.mcp_port == 8000
        # llm_model 取决于 .env 是否有 DEEPSEEK_API_KEY

    def test_config_validate_without_api_key(self):
        """没有 API key 时 validate 应该报告缺失"""
        config = Config()
        missing = config.validate()
        if missing:
            assert "API_KEY" in missing[0]

    def test_project_root_exists(self):
        """项目根目录应该存在"""
        root = _find_project_root()
        assert root.exists()

    def test_data_dir(self):
        """数据目录应该在项目根目录下"""
        config = Config()
        assert config.data_dir.name == "data"
        assert config.data_dir.parent == config.project_root

    def test_get_config_singleton(self):
        """get_config 应该返回同一个实例（lru_cache）"""
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2  # 同一个对象
