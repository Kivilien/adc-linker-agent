"""
测试 domain/properties.py —— 分子性质计算
"""

import pytest

from adc_linker_agent.domain.properties import (
    MolPropertyCalculator,
    CachedMolPropertyCalculator,
)

# ─── 测试用例：已知性质的参考分子 ───
# 阿司匹林：LogP ≈ 1.4, QED ≈ 0.78
ASPIRIN_SMILES = "CC(=O)Oc1ccccc1C(=O)O"
# Val-Cit-PABC 连接子（简化版）
VAL_CIT_SMILES = "CC(C)[C@H](N)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1"
# 长链烷烃：极低 QED
ALKANE_SMILES = "CCCCCCCCCCCCCCCCCCCC"


class TestMolPropertyCalculator:
    """测试基础性质计算器"""

    calc = MolPropertyCalculator()

    # ─── LogP ───

    def test_logp_aspirin(self):
        """阿司匹林的 LogP 应该在 1.3-1.5 之间"""
        logp = self.calc.calculate_logp(ASPIRIN_SMILES)
        assert 1.0 < logp < 2.0, f"Expected LogP ~1.4, got {logp}"

    def test_logp_alkane_high(self):
        """长链烷烃（20碳）LogP 应该很高（极度亲油）"""
        logp = self.calc.calculate_logp(ALKANE_SMILES)
        assert logp > 5, f"Expected high LogP for alkane, got {logp}"

    def test_logp_invalid_smiles(self):
        """无效 SMILES 应该抛出 ValueError"""
        with pytest.raises(ValueError, match="Invalid SMILES"):
            self.calc.calculate_logp("NOT_A_VALID_SMILES")

    # ─── QED ───

    def test_qed_aspirin(self):
        """阿司匹林的 QED 应该较高（它是已上市药物）"""
        qed = self.calc.calculate_qed(ASPIRIN_SMILES)
        assert qed > 0.5, f"Expected QED > 0.5 for aspirin, got {qed}"

    def test_qed_alkane_low(self):
        """长链烷烃 QED 应该极低（不是药物）—— 实际值为 0.237"""
        qed = self.calc.calculate_qed(ALKANE_SMILES)
        assert qed < 0.3, f"Expected low QED for alkane, got {qed}"

    def test_qed_range(self):
        """QED 范围应该在 0-1 之间"""
        qed = self.calc.calculate_qed(ASPIRIN_SMILES)
        assert 0 <= qed <= 1

    # ─── SAS ───

    def test_sas_aspirin_easy(self):
        """阿司匹林合成容易（简单分子）"""
        sas = self.calc.calculate_sas(ASPIRIN_SMILES)
        assert sas < 3, f"Expected SAS < 3 for aspirin, got {sas}"

    def test_sas_val_cit_moderate(self):
        """Val-Cit-PABC 合成难度中等"""
        sas = self.calc.calculate_sas(VAL_CIT_SMILES)
        assert 1 < sas < 10, f"Expected SAS 1-10, got {sas}"

    # ─── TPSA ───

    def test_tpsa_aspirin(self):
        """阿司匹林的 TPSA 应该在 60-70 范围"""
        tpsa = self.calc.calculate_tpsa(ASPIRIN_SMILES)
        assert 50 < tpsa < 80, f"Expected TPSA 50-80, got {tpsa}"

    # ─── 氢键 ───

    def test_hbd_aspirin(self):
        """阿司匹林有 1 个氢键供体（羧基 -OH）"""
        hbd = self.calc.calculate_hbd(ASPIRIN_SMILES)
        assert hbd == 1, f"Expected HBD=1, got {hbd}"

    def test_hba_aspirin(self):
        """阿司匹林有 3 个氢键受体（羰基 O + 两个酯 O — 注意羧酸 -OH 不是受体）"""
        hba = self.calc.calculate_hba(ASPIRIN_SMILES)
        assert hba == 3, f"Expected HBA=3, got {hba}"

    def test_mw_aspirin(self):
        """阿司匹林分子量 ~180"""
        mw = self.calc.calculate_molecular_weight(ASPIRIN_SMILES)
        assert 170 < mw < 190, f"Expected MW ~180, got {mw}"

    # ─── Lipinski ───

    def test_lipinski_aspirin_passes(self):
        """阿司匹林完全符合 Lipinski 五规则"""
        result = self.calc.check_lipinski(ASPIRIN_SMILES)
        assert result["is_oral_drug_like"] is True
        assert result["violations"] == 0

    def test_lipinski_alkane_fails(self):
        """长链烷烃违反 Lipinski（LogP 太高）"""
        result = self.calc.check_lipinski(ALKANE_SMILES)
        assert result["violations"] >= 1

    # ─── calculate_all ───

    def test_calculate_all_returns_all_keys(self):
        """calculate_all 应该返回完整的性质字典"""
        result = self.calc.calculate_all(ASPIRIN_SMILES)
        expected_keys = {
            "smiles", "logp", "qed", "sas", "tpsa",
            "molecular_weight", "hbd", "hba", "rotatable_bonds",
        }
        assert set(result.keys()) == expected_keys

    def test_calculate_all_numeric_values(self):
        """所有性质值应该是数字（不是 None 或 NaN）"""
        result = self.calc.calculate_all(ASPIRIN_SMILES)
        numeric_keys = ["logp", "qed", "sas", "tpsa", "molecular_weight"]
        for key in numeric_keys:
            assert isinstance(result[key], (int, float)), f"{key} is not numeric"
            assert result[key] > 0, f"{key} should be positive"


class TestCachedMolPropertyCalculator:
    """测试缓存版本的性质计算器"""

    def test_cache_same_result(self):
        """缓存版本和原始版本应该返回相同结果"""
        calc = CachedMolPropertyCalculator()
        original = MolPropertyCalculator().calculate_all(ASPIRIN_SMILES)
        cached = calc.calculate_all_cached(ASPIRIN_SMILES)
        assert original == cached

    def test_cache_hit(self):
        """第二次调用应该从缓存中获取（通过检查 info 验证）"""
        calc = CachedMolPropertyCalculator()
        # 第一次调用，填充缓存
        result1 = calc.calculate_all_cached(ASPIRIN_SMILES)
        # 第二次调用，应该命中缓存
        result2 = calc.calculate_all_cached(ASPIRIN_SMILES)
        assert result1 == result2
        # 验证缓存信息
        info = calc.calculate_logp_cached.cache_info()  # type: ignore[attr-defined]
        assert info.hits >= 1
