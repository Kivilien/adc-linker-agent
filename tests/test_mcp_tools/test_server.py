"""
测试 MCP Server —— 工具注册和元数据
"""



class TestMCPServer:
    """测试 MCP 服务器实例"""

    def test_server_imports_without_error(self):
        """server 模块可以正常导入"""
        from adc_linker_agent.mcp_tools.server import mcp
        assert mcp is not None

    def test_nine_tools_registered(self):
        """应该有 9 个工具注册在 MCP 服务器上"""
        from adc_linker_agent.mcp_tools.server import mcp
        tools = mcp._tool_manager._tools
        assert len(tools) == 9

    def test_all_expected_tools_present(self):
        """所有预期的工具名都应该存在"""
        from adc_linker_agent.mcp_tools.server import mcp
        tool_names = set(mcp._tool_manager._tools.keys())
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
        }
        assert tool_names == expected

    def test_server_has_name(self):
        """服务器应该有名称"""
        from adc_linker_agent.mcp_tools.server import mcp
        assert mcp.name is not None
        assert "ADC" in mcp.name or "Linker" in mcp.name

    def test_server_has_instructions(self):
        """服务器应该有使用说明（用于 Claude Desktop 系统提示）"""
        from adc_linker_agent.mcp_tools.server import mcp
        assert mcp.instructions is not None
        assert len(mcp.instructions) > 50
        assert "ADC" in mcp.instructions

    def test_tools_have_descriptions(self):
        """每个工具都应该有描述（LLM 依赖描述来决定调用时机）"""
        from adc_linker_agent.mcp_tools.server import mcp
        for name, tool in mcp._tool_manager._tools.items():
            assert tool.description, f"Tool '{name}' has no description"
            assert len(tool.description) > 20, (
                f"Tool '{name}' description too short: {len(tool.description)} chars"
            )

    def test_tools_can_be_called_via_fn(self):
        """关键工具应该能通过 .fn 属性调用并返回结果"""
        from adc_linker_agent.mcp_tools.server import mcp

        # MCP Tool 对象本身不可调用，通过 .fn 获取原始函数
        tools = mcp._tool_manager._tools
        validate_tool = tools["validate_smiles"]
        result = validate_tool.fn("c1ccccc1")
        assert result["valid"] is True
