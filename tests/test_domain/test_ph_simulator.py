"""
测试 domain/ph_simulator.py —— pH 稳定性预测
"""

import pytest

from adc_linker_agent.domain.ph_simulator import (
    PhSimulator,
    PhStabilityResult,
    PhLabileGroup,
    PHYSIOLOGICAL_PH,
    quick_check,
)


# ─── 测试用分子 ───

# 腙键 (hydrazone) 连接子 —— 应该在 pH 5.5 裂解
HYDRAZONE_SMILES = "CC(=O)NN=C(C)c1ccccc1"

# Val-Cit-PABC 连接子（简化版）—— 主要是酶裂解而非 pH 敏感
VAL_CIT_SMILES = "CC(C)[C@H](N)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1"

# 简单酯 —— 在强酸/强碱下水解
ESTER_SMILES = "CC(=O)OCC"

# 无 pH 敏感基团的分子 —— 苯
BENZENE_SMILES = "c1ccccc1"

# 包含羧酸酯的分子 —— 在 pH 5 以下不稳定
CARBOXYLATE_ESTER_SMILES = "CC(=O)Oc1ccccc1C(=O)O"  # 阿司匹林（含酯基）


class TestPhSimulator:
    """测试 pH 稳定性模拟器"""

    sim = PhSimulator()

    # ─── 腙键测试 ───

    def test_hydrazone_stable_at_physiological_ph(self):
        """腙键在血液 pH 7.4 应该相对稳定"""
        result = self.sim.predict(HYDRAZONE_SMILES, ph=7.4)
        # 腙键在 pH > 6.5 时较稳定
        assert result.is_stable

    def test_hydrazone_labile_at_lysosomal_ph(self):
        """
        腙键在溶酶体 pH 5.0 应该裂解。

        注意：CC(=O)NN=C(C)c1ccccc1 中 N-N=C 同时匹配
        hydrazone 和 imine 两种 SMARTS 模式。
        hydrazone 总是包含 imine 子结构，这是化学事实。
        我们验证"至少一种 pH 敏感官能团被检测到"即可。
        """
        result = self.sim.predict(HYDRAZONE_SMILES, ph=5.0)
        assert not result.is_stable
        # 腙键的 C=N 部分被 imine SMARTS 匹配，
        # N-N 部分被 hydrazone SMARTS 匹配（取决于原子价态）
        ph_labile = result.labile_groups_found
        assert any(g in ph_labile for g in ["hydrazone", "imine"]), (
            f"Expected hydrazone or imine in labile groups, got {ph_labile}"
        )

    def test_hydrazone_labile_at_tumor_ph(self):
        """腙键在肿瘤微环境 pH 6.5 应该开始不稳定"""
        result = self.sim.predict(HYDRAZONE_SMILES, ph=6.5)
        # pH 6.5 刚好在 labile_below(6.0) 和 stable_above(6.5) 之间
        # 此处 < stable_above=6.5 且在中间区域 → partial
        assert not result.is_stable

    # ─── 无 pH 敏感基团的分子 ───

    def test_benzene_stable_at_all_ph(self):
        """苯在任何 pH 下都稳定（无 pH 敏感官能团）"""
        for ph in [2.0, 5.0, 7.4, 10.0]:
            result = self.sim.predict(BENZENE_SMILES, ph=ph)
            assert result.is_stable, f"Benzene should be stable at pH {ph}"

    # ─── 无效输入 ───

    def test_invalid_smiles_raises_error(self):
        """无效 SMILES 抛出 ValueError"""
        with pytest.raises(ValueError):
            self.sim.predict("INVALID_SMILES_STRING")

    # ─── 生理阶段预测 ───

    def test_physiological_phases_returns_all_phases(self):
        """应该返回所有 ADC 递送路径中的 pH 阶段"""
        results = self.sim.predict_physiological_phases(HYDRAZONE_SMILES)
        assert set(results.keys()) == set(PHYSIOLOGICAL_PH.keys())

    def test_hydrazone_blood_stable_lysosome_labile(self):
        """理想 ADC 连接子：血液稳定 + 溶酶体裂解"""
        results = self.sim.predict_physiological_phases(HYDRAZONE_SMILES)
        # 血液 pH 7.4：应该稳定
        assert results["blood"].is_stable, "Hydrazone should be stable in blood (pH 7.4)"
        # 溶酶体 pH 5.0：应该不稳定
        assert not results["lysosome"].is_stable, (
            "Hydrazone should be labile in lysosome (pH 5.0)"
        )

    # ─── 酯键测试 ───

    def test_ester_stable_at_neutral_ph(self):
        """简单酯在中性 pH 下较稳定"""
        result = self.sim.predict(ESTER_SMILES, ph=7.4)
        assert result.is_stable

    def test_ester_labile_at_acidic_ph(self):
        """简单酯在酸性 pH 下开始水解"""
        result = self.sim.predict(ESTER_SMILES, ph=2.0)
        assert not result.is_stable


class TestPhStabilityResult:
    """测试 PhStabilityResult 数据类"""

    def test_stable_result_contains_context(self):
        """稳定结果应该包含生理上下文"""
        sim = PhSimulator()
        result = sim.predict(BENZENE_SMILES, ph=5.5)
        assert "endosome" in result.context.lower() or "5.5" in result.context

    def test_labile_result_has_recommendation(self):
        """不稳定结果应该包含建议"""
        sim = PhSimulator()
        result = sim.predict(HYDRAZONE_SMILES, ph=5.0)
        assert len(result.recommendation) > 10


class TestQuickCheck:
    """测试便捷函数"""

    def test_quick_check_returns_string(self):
        result = quick_check(HYDRAZONE_SMILES, ph=5.0)
        assert isinstance(result, str)
        assert "不稳定" in result

    def test_quick_check_stable(self):
        result = quick_check(BENZENE_SMILES, ph=7.4)
        assert "稳定" in result


class TestCustomLabileGroups:
    """测试自定义官能团库"""

    def test_custom_group_detection(self):
        """自定义官能团应该能被检测到"""
        custom_group = PhLabileGroup(
            name="test_custom",
            smarts="[OX2][CX4]",  # 匹配任何醚键
            pka_typical=5.0,
            labile_below=6.0,
            stable_above=7.0,
            mechanism="测试用",
        )
        sim = PhSimulator(labile_groups=[custom_group])
        # 乙醚包含 [OX2][CX4] 模式
        result = sim.predict("CCOCC", ph=5.0)
        assert "test_custom" in result.labile_groups_found
