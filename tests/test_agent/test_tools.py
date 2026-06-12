"""
测试 LangChain 工具封装
"""

from langchain_core.tools import BaseTool

from adc_linker_agent.agent.tools import (
    ALL_TOOLS,
    validate_smiles,
    calculate_properties,
    check_lipinski,
    predict_ph_stability,
    predict_ph_stability_all_phases,
    search_linker_scaffolds,
)


# ─── 测试用 SMILES ───
ASPIRIN_SMILES = "CC(=O)Oc1ccccc1C(=O)O"
BENZENE_SMILES = "c1ccccc1"
HYDRAZONE_SMILES = "CC(=O)NN=C(C)c1ccccc1"


class TestToolWrappers:
    """测试 LangChain 工具封装"""

    def test_all_tools_are_base_tool(self):
        """所有工具都应该是 BaseTool 实例"""
        for tool in ALL_TOOLS:
            assert isinstance(tool, BaseTool), f"{tool.name} is not BaseTool"

    def test_seven_tools_in_list(self):
        """ALL_TOOLS 应该包含 7 个工具"""
        assert len(ALL_TOOLS) == 7

    def test_unique_tool_names(self):
        """工具名称应该不重复"""
        names = [t.name for t in ALL_TOOLS]
        assert len(names) == len(set(names))

    def test_all_tools_have_description(self):
        """每个工具必须有描述（LLM 依赖描述来选择工具）"""
        for tool in ALL_TOOLS:
            assert tool.description, f"{tool.name} has no description"
            assert len(tool.description) > 20, (
                f"{tool.name} description too short: {len(tool.description)} chars"
            )


class TestValidateSmilesTool:
    """测试 validate_smiles LangChain 工具"""

    def test_valid_smiles(self):
        result = validate_smiles.invoke({"smiles": ASPIRIN_SMILES})
        assert result["valid"] is True
        assert result["formula"] == "C9H8O4"

    def test_invalid_smiles(self):
        result = validate_smiles.invoke({"smiles": "INVALID"})
        assert result["valid"] is False

    def test_empty_string(self):
        result = validate_smiles.invoke({"smiles": ""})
        assert result["valid"] is False


class TestCalculatePropertiesTool:
    """测试 calculate_properties LangChain 工具"""

    def test_returns_all_properties(self):
        result = calculate_properties.invoke({"smiles": BENZENE_SMILES})
        expected = {"smiles", "logp", "qed", "sas", "tpsa",
                     "molecular_weight", "hbd", "hba", "rotatable_bonds"}
        assert set(result.keys()) == expected

    def test_invalid_smiles_returns_error(self):
        result = calculate_properties.invoke({"smiles": "NOT_VALID"})
        assert "error" in result


class TestCheckLipinskiTool:
    """测试 check_lipinski LangChain 工具"""

    def test_aspirin_passes(self):
        result = check_lipinski.invoke({"smiles": ASPIRIN_SMILES})
        assert result["is_oral_drug_like"] is True

    def test_returns_all_keys(self):
        result = check_lipinski.invoke({"smiles": ASPIRIN_SMILES})
        expected = {"molecular_weight", "logp", "hbd", "hba",
                     "violations", "violation_details", "is_oral_drug_like"}
        assert set(result.keys()) == expected


class TestPredictPhStabilityTool:
    """测试 predict_ph_stability LangChain 工具"""

    def test_hydrazone_stable_at_blood_ph(self):
        result = predict_ph_stability.invoke({"smiles": HYDRAZONE_SMILES, "ph": 7.4})
        assert result["is_stable"] is True

    def test_hydrazone_labile_at_lysosome_ph(self):
        result = predict_ph_stability.invoke({"smiles": HYDRAZONE_SMILES, "ph": 5.0})
        assert result["is_stable"] is False


class TestPredictPhAllPhasesTool:
    """测试 predict_ph_stability_all_phases LangChain 工具"""

    def test_returns_six_phases(self):
        result = predict_ph_stability_all_phases.invoke({"smiles": HYDRAZONE_SMILES})
        assert len(result) == 6

    def test_blood_stable_lysosome_labile(self):
        result = predict_ph_stability_all_phases.invoke({"smiles": HYDRAZONE_SMILES})
        assert result["blood"]["is_stable"] is True
        assert result["lysosome"]["is_stable"] is False


class TestSearchLinkerScaffoldsTool:
    """测试 search_linker_scaffolds LangChain 工具"""

    def test_returns_all_without_filter(self):
        result = search_linker_scaffolds.invoke({})
        assert len(result) >= 5

    def test_filter_by_mechanism(self):
        result = search_linker_scaffolds.invoke({"mechanism": "pH_sensitive"})
        assert len(result) >= 3
        for linker in result:
            assert linker["mechanism"] == "pH_sensitive"

    def test_each_result_has_properties(self):
        result = search_linker_scaffolds.invoke({})
        for linker in result:
            assert "properties" in linker
