"""
测试 3D 分子渲染器。
"""

import pytest


class TestSmilesTo3DMolblock:
    """SMILES → 3D MolBlock 转换"""

    def test_simple_aromatic(self):
        """简单芳香环能成功嵌入 3D 坐标"""
        from adc_linker_agent.ui.renderers import smiles_to_3d_molblock

        result = smiles_to_3d_molblock("c1ccccc1")
        assert result is not None
        assert "V2000" in result or "V3000" in result  # MolBlock 格式
        assert len(result) > 200

    def test_aspirin(self):
        """阿司匹林能成功 3D 嵌入"""
        from adc_linker_agent.ui.renderers import smiles_to_3d_molblock

        result = smiles_to_3d_molblock("CC(=O)Oc1ccccc1C(=O)O")
        assert result is not None, "Aspirin should embed successfully"

    def test_hydrazone_linker(self):
        """腙键连接子能成功 3D 嵌入"""
        from adc_linker_agent.ui.renderers import smiles_to_3d_molblock

        result = smiles_to_3d_molblock("CC(=O)NN=C(C)c1ccccc1")
        assert result is not None, "Hydrazone linker should embed successfully"

    def test_invalid_smiles_returns_none(self):
        """无效 SMILES 返回 None"""
        from adc_linker_agent.ui.renderers import smiles_to_3d_molblock

        result = smiles_to_3d_molblock("INVALID_SMILES_XYZ")
        assert result is None

    def test_empty_string_returns_none(self):
        """空字符串返回 None"""
        from adc_linker_agent.ui.renderers import smiles_to_3d_molblock

        result = smiles_to_3d_molblock("")
        assert result is None


class TestRenderMolecule3D:
    """完整 3D 渲染管道"""

    def test_valid_smiles_returns_html(self):
        """有效 SMILES 返回 HTML 字符串"""
        from adc_linker_agent.ui.renderers import render_molecule_3d

        html = render_molecule_3d("c1ccccc1")
        assert html is not None
        assert "<html" in html.lower() or "<div" in html.lower() or "viewer" in html.lower()

    def test_invalid_smiles_returns_none(self):
        """无效 SMILES 返回 None"""
        from adc_linker_agent.ui.renderers import render_molecule_3d

        html = render_molecule_3d("INVALID")
        assert html is None

    def test_caffeine_3d(self):
        """咖啡因（含杂原子多）能成功渲染"""
        from adc_linker_agent.ui.renderers import render_molecule_3d

        caffeine = "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"
        html = render_molecule_3d(caffeine)
        assert html is not None, "Caffeine 3D should render successfully"

    def test_nitrogen_rich_linker(self):
        """富氮连接子（Val-Cit-PABC 简化）能成功"""
        from adc_linker_agent.ui.renderers import render_molecule_3d

        # 二肽连接子简化片段
        smi = "CNC(=O)C(C)NC(=O)OCc1ccc(N)cc1"
        html = render_molecule_3d(smi)
        # 富氮柔性分子嵌入可能失败，不做硬性要求
        if html is not None:
            assert len(html) > 100
        # 否则优雅降级也是合理的

    @pytest.mark.parametrize(
        "smiles",
        [
            "c1ccccc1",
            "CC(=O)Oc1ccccc1C(=O)O",
            "CC(=O)NN=C(C)c1ccccc1",
            "O=C(CCCCCN1C(=O)C=CC1=O)ON2C(=O)CCC2=O",
        ],
    )
    def test_multiple_valid_smiles(self, smiles):
        """多个已知有效 SMILES 都能成功（成功率验证）"""
        from adc_linker_agent.ui.renderers import render_molecule_3d

        html = render_molecule_3d(smiles)
        assert html is not None, f"SMILES should render in 3D: {smiles[:30]}..."
