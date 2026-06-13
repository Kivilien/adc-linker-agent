"""
测试 MCP 工具: validate_smiles
"""


from adc_linker_agent.mcp_tools.tool_validate import validate_smiles

# ─── 复用 domain 测试中的 SMILES ───
ASPIRIN_SMILES = "CC(=O)Oc1ccccc1C(=O)O"
BENZENE_SMILES = "c1ccccc1"
HYDRAZONE_SMILES = "CC(=O)NN=C(C)c1ccccc1"


class TestValidateSmiles:
    """测试 SMILES 校验工具"""

    def test_valid_smiles_aspirin(self):
        """阿司匹林 SMILES 应该校验通过"""
        result = validate_smiles(ASPIRIN_SMILES)
        assert result["valid"] is True
        assert result["formula"] == "C9H8O4"
        assert 170 < result["molecular_weight"] < 190

    def test_valid_smiles_returns_canonical_form(self):
        """校验通过时返回规范化 SMILES"""
        result = validate_smiles(ASPIRIN_SMILES)
        assert "smiles" in result
        assert len(result["smiles"]) > 0

    def test_valid_smiles_benzene(self):
        """简单分子苯也应该通过"""
        result = validate_smiles(BENZENE_SMILES)
        assert result["valid"] is True
        assert result["formula"] == "C6H6"

    def test_invalid_smiles_returns_false(self):
        """无效 SMILES 返回 valid=False 而不抛异常"""
        result = validate_smiles("THIS_IS_NOT_A_MOLECULE")
        assert result["valid"] is False
        assert "error" in result

    def test_invalid_smiles_preserves_input(self):
        """无效 SMILES 保留原始输入以便调试"""
        bad_smiles = "INVALID_STRING"
        result = validate_smiles(bad_smiles)
        assert result["smiles"] == bad_smiles

    def test_empty_string(self):
        """空字符串也是无效 SMILES"""
        result = validate_smiles("")
        assert result["valid"] is False

    def test_hydrazone_linker(self):
        """腙键连接子 SMILES 应该校验通过"""
        result = validate_smiles(HYDRAZONE_SMILES)
        assert result["valid"] is True
        assert result["molecular_weight"] > 0

    def test_result_has_expected_keys(self):
        """返回结果应该包含所有期望的字段"""
        result = validate_smiles(ASPIRIN_SMILES)
        assert set(result.keys()) == {"valid", "smiles", "formula", "molecular_weight"}
