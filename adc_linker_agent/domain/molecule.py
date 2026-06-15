"""
ADC Linker Domain Models

用 Pydantic 数据类表示 ADC 药物研发中的核心实体。
每个字段的含义在教学中有详细解释。

类比: 这些数据类就像数据库的 Schema —— 定义了
"一个连接子长什么样，包含哪些字段，字段之间有什么关系"。
"""

import contextlib
import logging
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class CleavageMechanism(StrEnum):
    """连接子裂解机制

    连接子在什么条件下"断开"释放毒素？
    这是 ADC 设计的核心技术选型。
    """

    PH_SENSITIVE = "pH_sensitive"  # 酸敏感（腙键），在 pH 5.5 裂解
    ENZYMATIC = "enzymatic"  # 酶裂解（Val-Cit），被组织蛋白酶 B 切断
    REDOX = "redox"  # 氧化还原敏感（二硫键），被谷胱甘肽还原
    NON_CLEAVABLE = "non_cleavable"  # 不可裂解，依赖抗体完全降解


class Molecule(BaseModel):
    """基础分子模型

    SMILES 是什么？
    SMILES = Simplified Molecular Input Line Entry System
    一种用字符串表示分子结构的标准格式。
    比如:
      CCO = 乙醇（酒精）
      CC(=O)O = 乙酸（醋的主要成分）
      c1ccccc1 = 苯（六元碳环）

    对程序员来说，SMILES 就是分子的"序列化格式"，
    就像 JSON 序列化数据一样。
    """

    smiles: str = Field(
        ...,
        description="SMILES 分子表示字符串",
        examples=["CC(=O)Oc1ccccc1C(=O)O"],
    )
    name: str | None = Field(
        default=None,
        description="分子的通俗名称（如 '阿司匹林'、'Val-Cit-PABC'）",
    )

    @field_validator("smiles")
    @classmethod
    def smiles_must_not_be_empty(cls, v: str) -> str:
        """SMILES 不能为空字符串"""
        if not v or not v.strip():
            raise ValueError("SMILES string cannot be empty")
        return v.strip()

    # 等 Week 2 引入 RDKit 后，我们会添加更多验证器：
    # @field_validator("smiles")
    # def smiles_must_be_valid_chemistry(cls, v):
    #     mol = Chem.MolFromSmiles(v)
    #     if mol is None:
    #         raise ValueError(f"Invalid SMILES: {v}")
    #     return Chem.MolToSmiles(mol)  # 规范化为标准形式


class Linker(Molecule):
    """连接子（Linker）模型

    连接子的职责（类比快递包装）:
    1. 在血液中 (pH 7.4) 不能破 —— 稳定
    2. 到了肿瘤细胞溶酶体 (pH 5.5) 必须破 —— 释放毒素
    3. 不能太"油腻"（LogP 适中）—— 不然会聚集
    4. 化学家得能合成（SAS 不能太高）

    核心设计参数:
    - ph_labile_range: 在什么 pH 范围裂解
    - cleavage_mechanism: 裂解机制（酶/酸/还原）
    - target_payload: 这个连接子要携带什么毒素
    """

    cleavage_mechanism: CleavageMechanism = Field(
        ...,
        description="连接子的裂解机制",
    )
    ph_labile_low: float | None = Field(
        default=None,
        ge=0,
        le=14,
        description="开始裂解的最低 pH（如 5.0）",
    )
    ph_labile_high: float | None = Field(
        default=None,
        ge=0,
        le=14,
        description="完全裂解的最高 pH（如 6.5）",
    )
    target_payload: str | None = Field(
        default=None,
        description="该连接子常用于携带的毒素类型（如 'MMAE', 'SN-38'）",
    )


class Payload(Molecule):
    """小分子毒素（Payload）模型

    这是 ADC 的"弹头"——进入癌细胞后释放的杀伤性分子。
    常见毒素:
    - MMAE/MMAF: 微管抑制剂（阻断细胞分裂）
    - DM1/DM4: 美登素衍生物（微管抑制剂）
    - SN-38/Exatecan/Dxd: 拓扑异构酶 I 抑制剂（喜树碱类）
      ↑ 宜联生物 TMALIN 平台使用的就是这一类
    - PBD: DNA 交联剂（极端毒性）

    关键参数:
    - potency_ic50: 半数抑制浓度 (nM)，数字越小越毒
    """

    drug_class: str = Field(
        ...,
        description="毒素药物类别（如 'topoisomerase_I_inhibitor', 'tubulin_inhibitor'）",
    )
    potency_ic50_nm: float | None = Field(
        default=None,
        description="IC50 值 (nM)，数字越小毒性越强",
    )


class ADCLinker(BaseModel):
    """ADC 连接子完整视图

    组合 连接子 + 毒素 + 分子性质，给出一个候选设计的完整画像。
    这个类会在 Week 2 与 MolPropertyCalculator 结合使用。
    """

    linker: Linker = Field(..., description="连接子部分")
    payload: Payload = Field(..., description="荷载毒素")
    logp: float | None = Field(
        default=None,
        description="亲脂性 (LogP)，理想范围 1-3",
    )
    qed: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="药物相似性 (QED)，>0.5 较好",
    )
    sas: float | None = Field(
        default=None,
        description="合成可及性 (SAS)，1=easy, 10=difficult",
    )
    tpsa: float | None = Field(
        default=None,
        description="拓扑极性表面积 (TPSA)，影响水溶性",
    )

    def is_drug_like(self) -> bool:
        """Check if this linker-payload combination passes basic drug-likeness filters."""
        if self.qed is None or self.logp is None:
            return False
        return self.qed > 0.5 and 0 < self.logp < 5

    def summary(self) -> str:
        """Return a human-readable summary of the ADC linker design."""
        mech = self.linker.cleavage_mechanism.value
        name = self.linker.name or "Unnamed"
        return (
            f"ADC Linker: {name}\n"
            f"  Mechanism: {mech}\n"
            f"  Payload: {self.payload.name or self.payload.smiles}\n"
            f"  LogP: {self.logp or 'N/A'}, QED: {self.qed or 'N/A'}, "
            f"SAS: {self.sas or 'N/A'}, TPSA: {self.tpsa or 'N/A'}"
        )


# ─── 分子结构渲染 ───


def render_molecule_image(smiles: str, size: tuple[int, int] = (400, 250)) -> bytes | None:
    """
    将 SMILES 渲染为 PNG 图片 bytes。

    用于 Streamlit/Web 展示分子结构。
    主方案: RDKit MolToImage (PNG)
    降级: MolToSVG (纯文本，零图形依赖)

    Args:
        smiles: 有效的 SMILES 字符串
        size: 图片尺寸 (width, height)

    Returns:
        PNG bytes，或 None（渲染失败时）
    """
    from io import BytesIO

    from rdkit import Chem
    from rdkit.Chem import Draw

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None

    # 计算 2D 坐标（如 SMILES 无坐标信息）
    with contextlib.suppress(Exception):
        Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
    try:
        from rdkit.Chem import AllChem
    except ImportError:
        pass
    else:
        with contextlib.suppress(Exception):
            AllChem.Compute2DCoords(mol)

    # 方案 A: PNG 图片
    try:
        img = Draw.MolToImage(mol, size=size, kekulize=True)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        logger.warning("MolToImage failed, falling back to SVG", exc_info=True)

    # 方案 B: SVG 降级（可能没有 2D 坐标也能渲染）
    try:
        svg = Draw.MolToSVG(mol, width=size[0], height=size[1])
        return svg.encode("utf-8")
    except Exception:
        logger.warning("MolToSVG failed, no render available", exc_info=True)
        return None


def render_molecule_svg(smiles: str, size: tuple[int, int] = (400, 250)) -> str | None:
    """
    将 SMILES 渲染为 SVG 字符串。

    纯文本输出，零图形依赖，兼容性最好。

    Args:
        smiles: 有效的 SMILES 字符串
        size: 图片尺寸

    Returns:
        SVG 字符串，或 None（渲染失败时）
    """
    from rdkit import Chem
    from rdkit.Chem import Draw

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None

    try:
        from rdkit.Chem import AllChem
    except ImportError:
        pass
    else:
        with contextlib.suppress(Exception):
            AllChem.Compute2DCoords(mol)

    try:
        return Draw.MolToSVG(mol, width=size[0], height=size[1])
    except Exception:
        logger.warning("MolToSVG failed for SMILES rendering", exc_info=True)
        return None
