"""
测试 MCP 工具: predict_ph_stability, predict_ph_stability_all_phases
"""


from adc_linker_agent.domain.ph_simulator import PHYSIOLOGICAL_PH
from adc_linker_agent.mcp_tools.tool_ph import (
    predict_ph_stability,
    predict_ph_stability_all_phases,
)

# ─── 测试用 SMILES ───
HYDRAZONE_SMILES = "CC(=O)NN=C(C)c1ccccc1"  # 腙键连接子
BENZENE_SMILES = "c1ccccc1"                   # 无 pH 敏感基团
ESTER_SMILES = "CC(=O)OCC"                    # 简单酯


class TestPredictPhStability:
    """测试 pH 稳定性预测 MCP 工具"""

    def test_hydrazone_stable_at_blood_ph(self):
        """腙键在血液 pH 7.4 应该稳定"""
        result = predict_ph_stability(HYDRAZONE_SMILES, ph=7.4)
        assert result["is_stable"] is True

    def test_hydrazone_labile_at_lysosome_ph(self):
        """腙键在溶酶体 pH 5.0 应该裂解"""
        result = predict_ph_stability(HYDRAZONE_SMILES, ph=5.0)
        assert result["is_stable"] is False
        assert len(result["labile_groups_found"]) > 0

    def test_benzene_stable_at_all_ph(self):
        """苯在任何 pH 下都稳定"""
        for ph in [2.0, 5.0, 7.4]:
            result = predict_ph_stability(BENZENE_SMILES, ph=ph)
            assert result["is_stable"] is True
            assert result["labile_groups_found"] == []

    def test_ester_stable_at_neutral(self):
        """酯在中性 pH 稳定"""
        result = predict_ph_stability(ESTER_SMILES, ph=7.4)
        assert result["is_stable"] is True

    def test_ester_labile_at_acidic(self):
        """酯在强酸下不稳定"""
        result = predict_ph_stability(ESTER_SMILES, ph=2.0)
        assert result["is_stable"] is False

    def test_invalid_smiles_returns_error(self):
        """无效 SMILES 返回 error 字段"""
        result = predict_ph_stability("INVALID", ph=7.4)
        assert "error" in result

    def test_result_has_all_keys(self):
        """返回结果包含所有必要字段"""
        result = predict_ph_stability(HYDRAZONE_SMILES, ph=5.0)
        expected_keys = {
            "smiles", "target_ph", "is_stable",
            "labile_groups_found", "stable_groups_found",
            "recommendation", "context",
            "all_detected_groups", "groups_in_library",
            "groups_outside_library", "library_coverage",
        }
        assert set(result.keys()) == expected_keys

    def test_recommendation_is_meaningful(self):
        """建议字符串应该有实际内容"""
        result = predict_ph_stability(HYDRAZONE_SMILES, ph=5.0)
        assert len(result["recommendation"]) > 20

    def test_context_mentions_physiology(self):
        """上下文描述应该提及生理位置"""
        result = predict_ph_stability(HYDRAZONE_SMILES, ph=5.0)
        assert "lysosome" in result["context"].lower() or "5.0" in result["context"]

    def test_outside_library_detection(self):
        """框架外分子应该标注规则库覆盖率并列出未覆盖官能团"""
        result = predict_ph_stability(BENZENE_SMILES, ph=7.4)
        # 苯只有芳香环，不在 7 种 pH 敏感库中
        assert "all_detected_groups" in result
        assert "groups_outside_library" in result
        assert "library_coverage" in result
        # 芳香环应该被检测到
        assert "aromatic_ring" in result["all_detected_groups"]
        # 芳香环不在 pH 敏感规则库中
        assert result["library_coverage"] < 1.0
        # 推荐信息应该提示讨论
        assert "讨论" in result["recommendation"]

    def test_inside_library_coverage_full(self):
        """框架内分子应该有较高的规则库覆盖率"""
        result = predict_ph_stability(HYDRAZONE_SMILES, ph=5.0)
        # hydrazone 在通用库中映射到 amide/ketone 等，覆盖率应 > 0
        assert result["library_coverage"] > 0


class TestPredictPhStabilityAllPhases:
    """测试全生理阶段 pH 稳定性预测 MCP 工具"""

    def test_returns_all_phases(self):
        """应该覆盖所有 ADC 递送路径中的 pH 阶段"""
        result = predict_ph_stability_all_phases(HYDRAZONE_SMILES)
        assert set(result.keys()) == set(PHYSIOLOGICAL_PH.keys())

    def test_hydrazone_blood_stable_lysosome_labile(self):
        """理想 ADC 连接子：血液稳定 + 溶酶体裂解"""
        result = predict_ph_stability_all_phases(HYDRAZONE_SMILES)
        assert result["blood"]["is_stable"] is True, \
            "Hydrazone must be stable in blood"
        assert result["lysosome"]["is_stable"] is False, \
            "Hydrazone must cleave in lysosome"

    def test_benzene_stable_all_phases(self):
        """苯在所有阶段都稳定"""
        result = predict_ph_stability_all_phases(BENZENE_SMILES)
        for phase, data in result.items():
            assert data["is_stable"] is True, \
                f"Benzene should be stable in {phase}, got {data}"

    def test_invalid_smiles_returns_error(self):
        """无效 SMILES 返回 error 字段"""
        result = predict_ph_stability_all_phases("NOT_VALID")
        assert "error" in result

    def test_each_phase_has_required_keys(self):
        """每个阶段的子结果包含所有必要字段"""
        result = predict_ph_stability_all_phases(HYDRAZONE_SMILES)
        for phase, data in result.items():
            expected = {
                "target_ph", "is_stable", "labile_groups_found",
                "recommendation",
                "all_detected_groups", "groups_in_library",
                "groups_outside_library", "library_coverage",
            }
            assert set(data.keys()) == expected, f"Missing keys in phase {phase}"
