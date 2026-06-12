"""
测试 MCP 工具: calculate_properties, check_lipinski
"""

import pytest

from adc_linker_agent.mcp_tools.tool_property import calculate_properties, check_lipinski


# ─── 测试用 SMILES ───
ASPIRIN_SMILES = "CC(=O)Oc1ccccc1C(=O)O"      # 阿司匹林
BENZENE_SMILES = "c1ccccc1"                     # 苯
ALKANE_SMILES = "CCCCCCCCCCCCCCCCCCCC"          # 20碳烷烃


class TestCalculateProperties:
    """测试性质计算 MCP 工具"""

    def test_returns_all_keys(self):
        """应该返回全部 8 个描述符 + smiles"""
        result = calculate_properties(ASPIRIN_SMILES)
        expected_keys = {
            "smiles", "logp", "qed", "sas", "tpsa",
            "molecular_weight", "hbd", "hba", "rotatable_bonds",
        }
        assert set(result.keys()) == expected_keys

    def test_all_values_positive(self):
        """所有数值应该是正数（或零）"""
        result = calculate_properties(ASPIRIN_SMILES)
        numeric_keys = ["logp", "qed", "sas", "tpsa", "molecular_weight"]
        for key in numeric_keys:
            assert result[key] >= 0, f"{key} should be >= 0, got {result[key]}"

    def test_aspirin_qed_drug_like(self):
        """阿司匹林 QED 应该大于 0.5（已上市药物）"""
        result = calculate_properties(ASPIRIN_SMILES)
        assert result["qed"] > 0.5

    def test_alkane_qed_low(self):
        """长链烷烃 QED 应该很低"""
        result = calculate_properties(ALKANE_SMILES)
        assert result["qed"] < 0.3

    def test_benzene_simple(self):
        """简单分子苯的性质"""
        result = calculate_properties(BENZENE_SMILES)
        assert result["molecular_weight"] < 100
        assert result["tpsa"] == 0.0  # 苯无极性原子

    def test_error_on_invalid_smiles(self):
        """无效 SMILES 返回 error 字段而不抛异常"""
        result = calculate_properties("NOT_VALID")
        assert "error" in result
        assert "smiles" in result


class TestCheckLipinski:
    """测试 Lipinski 五规则检查 MCP 工具"""

    def test_aspirin_passes(self):
        """阿司匹林应该完全通过 Lipinski 五规则"""
        result = check_lipinski(ASPIRIN_SMILES)
        assert result["is_oral_drug_like"] is True
        assert result["violations"] == 0
        assert result["violation_details"] == []

    def test_alkane_fails(self):
        """长链烷烃违反 LogP 规则"""
        result = check_lipinski(ALKANE_SMILES)
        assert result["violations"] >= 1
        # 至少有一条违规详细信息
        assert len(result["violation_details"]) >= 1

    def test_result_has_expected_keys(self):
        """返回结果包含完整字段"""
        result = check_lipinski(ASPIRIN_SMILES)
        expected_keys = {
            "molecular_weight", "logp", "hbd", "hba",
            "violations", "violation_details", "is_oral_drug_like",
        }
        assert set(result.keys()) == expected_keys

    def test_benzene_not_drug_like(self):
        """苯太小了，不像口服药（但 Lipinski 本身不检查 MW 下限）"""
        result = check_lipinski(BENZENE_SMILES)
        # 苯 MW=78, LogP~1.7, HBD=0, HBA=0 — 不违反任何 Lipinski 规则
        # 但这不意味着它是好的口服药（QED 会捕获这个问题）
        assert result["violations"] == 0
