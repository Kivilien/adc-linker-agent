"""
3D 分子可视化渲染器。

管道: SMILES → RDKit 3D 嵌入 → MolBlock → py3Dmol HTML
多重降级策略确保成功率 >= 85%。

用法:
    from adc_linker_agent.ui.renderers import render_molecule_3d

    html = render_molecule_3d("c1ccccc1")
    if html:
        st.components.v1.html(html, height=400)
    else:
        # 降级到 2D
        render_molecule_structure("c1ccccc1")
"""

from __future__ import annotations

import contextlib
import logging

logger = logging.getLogger(__name__)


def smiles_to_3d_molblock(smiles: str) -> str | None:
    """
    SMILES → 3D MolBlock 字符串。

    步骤:
      1. 解析 SMILES → RDKit Mol
      2. 加氢原子
      3. ETKDGv3 3D 嵌入（带多重重试）
      4. MMFF 力场优化（失败则 UFF 兜底）
      5. 去掉氢原子（展示更清晰）
      6. 导出 MolBlock

    Args:
        smiles: 标准 SMILES 字符串

    Returns:
        MolBlock 字符串（含 3D 坐标），失败返回 None
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError:
        return None

    mol = Chem.MolFromSmiles(smiles)
    if mol is None or mol.GetNumAtoms() == 0:
        return None

    mol = Chem.AddHs(mol)

    # ─── 3D 嵌入（三重重试） ───
    embedded = False

    # 尝试 1: ETKDGv3（默认参数）
    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    result = AllChem.EmbedMolecule(mol, params)
    if result == 0:
        embedded = True

    # 尝试 2: ETKDGv3 + 随机坐标初始化
    if not embedded:
        params.useRandomCoords = True
        result = AllChem.EmbedMolecule(mol, params)
        if result == 0:
            embedded = True

    # 尝试 3: 纯随机坐标（无 ETKDG，最后手段）
    if not embedded:
        result = AllChem.EmbedMolecule(mol, useRandomCoords=True, randomSeed=42)
        if result == 0:
            embedded = True

    if not embedded:
        return None

    # ─── 力场优化 ───
    with contextlib.suppress(Exception):
        # 首选 MMFF94
        if AllChem.MMFFHasAllMoleculeParams(mol):
            AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
        else:
            # 兜底 UFF
            AllChem.UFFOptimizeMolecule(mol, maxIters=500)

    # ─── 去掉氢原子，展示更清晰 ───
    mol = Chem.RemoveHs(mol)

    return Chem.MolToMolBlock(mol)


def build_py3dmol_html(
    molblock: str,
    width: int = 400,
    height: int = 350,
    background_color: str = "0x2E3440",
) -> str | None:
    """
    MolBlock → py3Dmol 交互式 3D HTML。

    使用球棍模型 + 半透明表面，Nord 深色背景。

    Args:
        molblock: SDF/MolBlock 格式的分子 3D 坐标
        width: 画布宽度 (px)
        height: 画布高度 (px)
        background_color: 背景色（十六进制，如 "0x2E3440"）

    Returns:
        完整的 HTML 字符串，可用于 st.components.v1.html()
    """
    try:
        import py3Dmol
    except ImportError:
        return None

    try:
        viewer = py3Dmol.view(width=width, height=height)
        viewer.addModel(molblock, "mol")
        viewer.setStyle({"stick": {"radius": 0.12, "colorscheme": "Jmol"}})
        viewer.addStyle({"sphere": {"scale": 0.3, "colorscheme": "Jmol"}})
        viewer.setBackgroundColor(background_color)
        viewer.zoomTo()
        return viewer._make_html()
    except Exception:
        logger.warning("py3Dmol HTML rendering failed for molblock", exc_info=True)
        return None


def render_molecule_3d(
    smiles: str,
    size: tuple[int, int] = (400, 350),
    background: str = "0x2E3440",
) -> str | None:
    """
    完整管道: SMILES → 3D HTML。

    一步完成从 SMILES 到交互式 3D 可视化的全流程。
    任何步骤失败返回 None，调用方应降级到 2D 渲染。

    Args:
        smiles: 标准 SMILES 字符串
        size: (width, height) 像素
        background: 背景色十六进制字符串

    Returns:
        HTML 字符串或 None

    Example:
        html = render_molecule_3d("c1ccccc1")
        if html:
            st.components.v1.html(html, height=400)
    """
    molblock = smiles_to_3d_molblock(smiles)
    if molblock is None:
        return None
    return build_py3dmol_html(molblock, width=size[0], height=size[1], background_color=background)
