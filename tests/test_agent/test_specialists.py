"""
测试专长 Agent（Week 5 Multi-Agent）

验证:
  1. 每个专长 Agent 的工具集（最小权限原则）
  2. 系统提示不被截断或混淆
  3. _execute_tool_calls 正确执行
  4. 专长 Agent 工厂函数
"""

from langchain_core.messages import AIMessage, ToolMessage

from adc_linker_agent.agent.specialists import (
    _TOOL_MAP,
    ALL_TOOLS,
    LINKER_TOOLS,
    LITERATURE_TOOLS,
    PH_TOOLS,
    PROPERTY_TOOLS,
    _execute_tool_calls,
    create_specialist_node,
    linker_agent,
    ph_agent,
    property_agent,
)


class TestToolSetAssignment:
    """测试最小权限原则：每个 Agent 只有必需的 tools"""

    def test_property_agent_has_4_tools(self):
        """PropertyAgent 有 4 个工具（含毒性检测）"""
        assert len(PROPERTY_TOOLS) == 4
        tool_names = {t.name for t in PROPERTY_TOOLS}
        assert tool_names == {
            "validate_smiles",
            "calculate_properties",
            "check_lipinski",
            "check_toxicity",
        }

    def test_ph_agent_has_2_tools(self):
        """PHAgent 只有 2 个工具"""
        assert len(PH_TOOLS) == 2
        tool_names = {t.name for t in PH_TOOLS}
        assert tool_names == {"predict_ph_stability", "predict_ph_stability_all_phases"}

    def test_linker_agent_has_all_tools(self):
        """LinkerDesignAgent 拥有全部工具（含 PubChem 搜索）"""
        assert len(LINKER_TOOLS) == len(ALL_TOOLS)
        assert LINKER_TOOLS == ALL_TOOLS

    def test_literature_agent_has_1_tool(self):
        """LiteratureAgent 只有 1 个文献搜索工具"""
        assert len(LITERATURE_TOOLS) == 1
        tool_names = {t.name for t in LITERATURE_TOOLS}
        assert tool_names == {"search_literature"}

    def test_property_agent_cannot_access_ph_tools(self):
        """PropertyAgent 不应该有 pH 工具"""
        property_names = {t.name for t in PROPERTY_TOOLS}
        ph_names = {t.name for t in PH_TOOLS}
        assert property_names.isdisjoint(ph_names)

    def test_ph_agent_cannot_access_property_tools(self):
        """PHAgent 不应该有性质计算工具"""
        ph_names = {t.name for t in PH_TOOLS}
        property_names = {t.name for t in PROPERTY_TOOLS}
        assert ph_names.isdisjoint(property_names)


class TestToolMap:
    """测试工具名→函数映射"""

    def test_all_9_tools_in_map(self):
        """_TOOL_MAP 应该包含全部 9 个工具（含毒性检测）"""
        assert len(_TOOL_MAP) == 9
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
        assert set(_TOOL_MAP.keys()) == expected

    def test_each_mapped_function_has_invoke(self):
        """每个映射的 LangChain StructuredTool 应该有 invoke 方法"""
        for name, func in _TOOL_MAP.items():
            assert hasattr(func, "invoke"), f"{name} should have .invoke() method"


class TestExecuteToolCalls:
    """测试 specialist 内部工具执行"""

    def test_single_tool_call(self):
        """正确执行单个 tool_call"""
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "validate_smiles",
                    "args": {"smiles": "c1ccccc1"},
                    "id": "call_test_1",
                }
            ],
        )
        results = _execute_tool_calls(ai_msg)
        tool_messages, raw_results = results
        assert len(tool_messages) == 1
        assert isinstance(tool_messages[0], ToolMessage)
        assert "valid" in tool_messages[0].content
        assert "true" in tool_messages[0].content.lower()

    def test_multiple_tool_calls(self):
        """正确执行多个并发 tool_calls"""
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "validate_smiles",
                    "args": {"smiles": "CC(=O)Oc1ccccc1C(=O)O"},
                    "id": "call_v",
                },
                {
                    "name": "calculate_properties",
                    "args": {"smiles": "CC(=O)Oc1ccccc1C(=O)O"},
                    "id": "call_p",
                },
            ],
        )
        results = _execute_tool_calls(ai_msg)
        tool_messages, _raw = results
        assert len(tool_messages) == 2
        assert all(isinstance(r, ToolMessage) for r in tool_messages)
        # 第一条应该是 validate_smiles 结果
        assert "C9H8O4" in tool_messages[0].content
        # 第二条应该是 calculate_properties 结果
        assert "logp" in tool_messages[1].content

    def test_unknown_tool_name_returns_error(self):
        """未知工具名返回错误信息而不崩溃"""
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "nonexistent_tool_xyz",
                    "args": {},
                    "id": "call_bad",
                }
            ],
        )
        tool_messages, _raw = _execute_tool_calls(ai_msg)
        assert len(tool_messages) == 1
        assert "unknown" in tool_messages[0].content.lower()

    def test_empty_tool_calls_returns_empty(self):
        """没有 tool_calls 时返回空列表"""
        ai_msg = AIMessage(content="No tools needed")
        results = _execute_tool_calls(ai_msg)
        assert results == ([], {})

    def test_tool_call_with_invalid_args_returns_error(self):
        """工具参数无效时返回错误不崩溃"""
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "validate_smiles",
                    "args": {"smiles": "THIS_IS_NOT_VALID"},
                    "id": "call_invalid",
                }
            ],
        )
        tool_messages, _raw = _execute_tool_calls(ai_msg)
        assert len(tool_messages) == 1
        # validate_smiles 对无效 SMILES 返回 valid: false，不抛异常


class TestCreateSpecialistNode:
    """测试专长 Agent 节点工厂"""

    def test_creates_callable_node(self):
        """工厂函数返回可调用对象"""
        node = create_specialist_node(
            name="test_agent",
            system_prompt="You are a test agent.",
            tools=PROPERTY_TOOLS[:1],  # 只用 validate_smiles
            context_key="test_data",
            extract_fn=lambda raw: {"result": str(raw)},
        )
        assert callable(node)

    def test_node_has_name(self):
        """创建的节点有名称"""
        node = create_specialist_node(
            name="test_specialist",
            system_prompt="Test prompt.",
            tools=PROPERTY_TOOLS[:1],
            context_key="test_data",
            extract_fn=lambda raw: {"result": str(raw)},
        )
        assert node.__name__ == "test_specialist"

    def test_property_agent_is_callable(self):
        """property_agent 模块级实例应该是可调用的"""
        assert callable(property_agent)
        assert property_agent.__name__ == "property_agent"

    def test_ph_agent_is_callable(self):
        """ph_agent 模块级实例应该是可调用的"""
        assert callable(ph_agent)
        assert ph_agent.__name__ == "ph_agent"

    def test_linker_agent_is_callable(self):
        """linker_agent 模块级实例应该是可调用的"""
        assert callable(linker_agent)
        assert linker_agent.__name__ == "linker_agent"
