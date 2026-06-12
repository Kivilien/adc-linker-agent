"""
测试 domain/molecule.py — 领域模型验证

测试策略：
1. 正常创建 —— 验证数据类可以正确实例化
2. 边界条件 —— 空 SMILES、极端数值
3. 枚举验证 —— CleavageMechanism 的正确值
4. ADCLinker 组合 —— 连接子 + 毒素的完整视图
"""

import pytest
from pydantic import ValidationError

from adc_linker_agent.domain.molecule import (
    Molecule,
    Linker,
    Payload,
    ADCLinker,
    CleavageMechanism,
)


# ─── Molecule 基础类测试 ───


class TestMolecule:
    """测试基础分子模型"""

    def test_create_simple_molecule(self):
        """最简单的分子：阿司匹林（SMILES）"""
        mol = Molecule(smiles="CC(=O)Oc1ccccc1C(=O)O", name="阿司匹林")
        assert mol.smiles == "CC(=O)Oc1ccccc1C(=O)O"
        assert mol.name == "阿司匹林"

    def test_create_without_name(self):
        """name 是可选字段"""
        mol = Molecule(smiles="CCO")
        assert mol.smiles == "CCO"
        assert mol.name is None

    def test_empty_smiles_raises_error(self):
        """空 SMILES 应该抛出 ValidationError"""
        with pytest.raises(ValidationError):
            Molecule(smiles="")

    def test_whitespace_smiles_raises_error(self):
        """纯空格 SMILES 应该抛出 ValidationError"""
        with pytest.raises(ValidationError):
            Molecule(smiles="   ")

    def test_smiles_is_stripped(self):
        """SMILES 前后的空格应该被自动去除"""
        mol = Molecule(smiles="  CCO  ")
        assert mol.smiles == "CCO"

    def test_complex_smiles(self):
        """测试一个更复杂的分子（Val-Cit-PABC 连接子的简化版）"""
        smiles = "CC(C)C(NC(=O)C(N)C(C)C)C(=O)NC(CCCNC(N)=O)C(=O)O"
        mol = Molecule(smiles=smiles)
        assert len(mol.smiles) > 20  # 复杂分子的 SMILES 会比较长


# ─── CleavageMechanism 枚举测试 ───


class TestCleavageMechanism:
    """测试裂解机制枚举"""

    def test_all_mechanisms_exist(self):
        """确保所有预期的裂解机制都在枚举中"""
        mechanisms = [m.value for m in CleavageMechanism]
        assert "pH_sensitive" in mechanisms
        assert "enzymatic" in mechanisms
        assert "redox" in mechanisms
        assert "non_cleavable" in mechanisms

    def test_ph_sensitive_is_default_for_tmalin_like(self):
        """宜联生物的 TMALIN 是 pH 敏感的（肿瘤微环境激活）"""
        mech = CleavageMechanism.PH_SENSITIVE
        assert mech.value == "pH_sensitive"


# ─── Linker 模型测试 ───


class TestLinker:
    """测试连接子模型"""

    def test_create_ph_sensitive_linker(self):
        """创建一个 pH 敏感型连接子（类似 TMALIN 平台）"""
        linker = Linker(
            smiles="CC(=O)NNC(=O)c1ccc(cc1)",
            name="TMALIN-like linker",
            cleavage_mechanism=CleavageMechanism.PH_SENSITIVE,
            ph_labile_low=5.0,
            ph_labile_high=6.5,
            target_payload="Exatecan",
        )
        assert linker.cleavage_mechanism == CleavageMechanism.PH_SENSITIVE
        assert linker.ph_labile_low == 5.0
        assert linker.target_payload == "Exatecan"

    def test_create_enzymatic_linker(self):
        """创建一个酶裂解型连接子（如 Val-Cit-PABC）"""
        linker = Linker(
            smiles="CC(C)C(NC(=O)C(N)C(C)C)C(=O)NC",
            name="Val-Cit-PABC",
            cleavage_mechanism=CleavageMechanism.ENZYMATIC,
            ph_labile_low=5.0,
            ph_labile_high=6.0,
            target_payload="MMAE",
        )
        assert linker.cleavage_mechanism == CleavageMechanism.ENZYMATIC

    def test_ph_range_validation(self):
        """pH 范围应该合法 (0-14)"""
        linker = Linker(
            smiles="CCO",
            cleavage_mechanism=CleavageMechanism.PH_SENSITIVE,
            ph_labile_low=5.5,
            ph_labile_high=6.5,
        )
        assert linker.ph_labile_high > linker.ph_labile_low  # type: ignore[operator]

    def test_invalid_ph_range_low(self):
        """pH 不能小于 0"""
        with pytest.raises(ValidationError):
            Linker(
                smiles="CCO",
                cleavage_mechanism=CleavageMechanism.PH_SENSITIVE,
                ph_labile_low=-1.0,
            )

    def test_invalid_ph_range_high(self):
        """pH 不能大于 14"""
        with pytest.raises(ValidationError):
            Linker(
                smiles="CCO",
                cleavage_mechanism=CleavageMechanism.PH_SENSITIVE,
                ph_labile_high=15.0,
            )


# ─── Payload 毒素模型测试 ───


class TestPayload:
    """测试毒素模型"""

    def test_create_topoisomerase_inhibitor(self):
        """喜树碱类毒素——宜联 TMALIN 平台使用的类型"""
        payload = Payload(
            smiles="CC[C@@]1(O)CC(=O)OCC2=C1C=C3N(C2)Cc4c3nc5ccccc5c4=O",
            name="SN-38",
            drug_class="topoisomerase_I_inhibitor",
            potency_ic50_nm=1.0,
        )
        assert payload.drug_class == "topoisomerase_I_inhibitor"
        assert payload.potency_ic50_nm == 1.0

    def test_create_tubulin_inhibitor(self):
        """微管抑制剂——另一类常见 ADC 毒素"""
        payload = Payload(
            smiles="CC[C@H](C)[C@@H]1N(C)C(=O)CC[C@H](NC(=O)C=2C=C(OC)C=CC=2)C(=O)C1",
            name="MMAE",
            drug_class="tubulin_inhibitor",
            potency_ic50_nm=0.5,
        )
        assert payload.name == "MMAE"


# ─── ADCLinker 组合模型测试 ───


class TestADCLinker:
    """测试 ADC 连接子完整视图"""

    @pytest.fixture
    def sample_linker(self):
        return Linker(
            smiles="CC(=O)NNC(=O)c1ccc(cc1)",
            name="Hydrazone linker",
            cleavage_mechanism=CleavageMechanism.PH_SENSITIVE,
            ph_labile_low=5.0,
            ph_labile_high=6.5,
            target_payload="Doxorubicin",
        )

    @pytest.fixture
    def sample_payload(self):
        return Payload(
            smiles="CC[C@@]1(O)CC(=O)OCC2=C1C=C3N(C2)Cc4c3nc5ccccc5c4=O",
            name="SN-38",
            drug_class="topoisomerase_I_inhibitor",
            potency_ic50_nm=1.0,
        )

    def test_create_adc_linker(self, sample_linker, sample_payload):
        """创建一个完整的 ADC 连接子设计"""
        adc = ADCLinker(
            linker=sample_linker,
            payload=sample_payload,
            logp=2.1,
            qed=0.65,
            sas=3.2,
            tpsa=120.5,
        )
        assert adc.linker.name == "Hydrazone linker"
        assert adc.payload.name == "SN-38"
        assert adc.logp == 2.1

    def test_is_drug_like_true(self, sample_linker, sample_payload):
        """QED > 0.5 且 LogP 在 0-5 之间 → drug-like"""
        adc = ADCLinker(
            linker=sample_linker,
            payload=sample_payload,
            logp=2.5,
            qed=0.7,
        )
        assert adc.is_drug_like() is True

    def test_is_drug_like_false_low_qed(self, sample_linker, sample_payload):
        """QED 太低 → not drug-like"""
        adc = ADCLinker(
            linker=sample_linker,
            payload=sample_payload,
            logp=2.5,
            qed=0.3,
        )
        assert adc.is_drug_like() is False

    def test_is_drug_like_false_no_logp(self, sample_linker, sample_payload):
        """缺少性质数据 → not drug-like"""
        adc = ADCLinker(
            linker=sample_linker,
            payload=sample_payload,
            qed=0.7,
        )
        assert adc.is_drug_like() is False

    def test_summary_contains_key_info(self, sample_linker, sample_payload):
        """summary() 方法应该包含关键信息"""
        adc = ADCLinker(
            linker=sample_linker,
            payload=sample_payload,
            logp=2.1,
            qed=0.65,
        )
        summary = adc.summary()
        assert "Hydrazone linker" in summary
        assert "pH_sensitive" in summary
        assert "SN-38" in summary
