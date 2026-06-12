"""
pH 稳定性模拟器（PhSimulator）

基于化学官能团规则预测分子在不同 pH 条件下的稳定性。
这不是机器学习——是化学知识的编码。

核心原理:
    每个化学键在一定 pH 范围内稳定，超出范围则断裂。
    比如腙键 (hydrazone) 在 pH 4-6 快速水解，在 pH 7.4 缓慢水解。

对程序员的类比:
    这就像一个"配置表"——定义哪些官能团在什么 pH 下触发"裂解"事件。
    跟游戏里"火焰伤害 → 冰属性免疫"的条件规则一样。

局限性（诚实标注）:
    - 这是规则引擎，不是量子化学计算
    - 只能识别已知的 pH 敏感官能团
    - 不考虑分子内相互作用（如邻近基团的电子效应）
    - 实际 pKa 值受分子环境影响，此处使用典型值
"""

from typing import Optional
from dataclasses import dataclass, field

from rdkit import Chem


# ─── pH 敏感官能团定义 ───
#
# 每条规则包含:
#   - name: 官能团名称
#   - smarts: SMARTS 模式（SMILES 的正则表达式版）
#   - pka_range: 典型的 pKa 范围
#   - labile_below: pH 低于此值时开始明显裂解
#   - stable_above: pH 高于此值时保持稳定
#   - mechanism: 裂解机制描述


@dataclass
class PhLabileGroup:
    """一个 pH 敏感的官能团规则"""

    name: str
    smarts: str
    pka_typical: float  # 典型 pKa
    labile_below: float  # 低于此 pH 开始裂解
    stable_above: float  # 高于此 pH 保持稳定
    mechanism: str = ""


# 已知的 pH 敏感官能团库
PH_LABILE_GROUPS: list[PhLabileGroup] = [
    PhLabileGroup(
        name="hydrazone",
        smarts="[CX3](=[OX1])[NX2][NX3]",
        pka_typical=5.0,
        labile_below=6.0,
        stable_above=6.5,
        mechanism="酸催化水解：H+ 攻击 C=N 双键，腙键断裂为醛/酮 + 肼",
    ),
    PhLabileGroup(
        name="acetal",
        smarts="[OX2][CX4H1]([OX2])[CX4]",
        pka_typical=4.5,
        labile_below=5.5,
        stable_above=6.0,
        mechanism="酸催化水解：两个醚键逐步断裂，释放醛/酮 + 两个醇",
    ),
    PhLabileGroup(
        name="ketal",
        smarts="[OX2][CX4]([OX2])([CX4])[CX4]",
        pka_typical=4.5,
        labile_below=5.5,
        stable_above=6.0,
        mechanism="与缩醛类似，但来自酮而非醛",
    ),
    PhLabileGroup(
        name="carboxylic_ester",
        smarts="[CX3](=[OX1])[OX2][CX4]",
        pka_typical=7.0,
        labile_below=5.0,
        stable_above=7.0,
        mechanism="酸/碱催化酯水解：水分子攻击羰基碳，释放酸 + 醇",
    ),
    PhLabileGroup(
        name="carbamate",
        smarts="[NX3][CX3](=[OX1])[OX2]",
        pka_typical=6.5,
        labile_below=5.5,
        stable_above=7.0,
        mechanism="酸催化分解：释放 CO2 + 胺 + 醇。PABC 自毁连接子的核心机制。",
    ),
    PhLabileGroup(
        name="imine",
        smarts="[CX3](=[NX2])[CX4]",
        pka_typical=5.5,
        labile_below=6.0,
        stable_above=7.0,
        mechanism="酸催化水解：C=N 断裂为 C=O + N-H（席夫碱水解）",
    ),
    PhLabileGroup(
        name="silyl_ether",
        smarts="[SiX4][OX2][CX4]",
        pka_typical=4.0,
        labile_below=5.0,
        stable_above=6.0,
        mechanism="酸催化裂解：Si-O 键断裂（在 ADC 中较少使用）",
    ),
]


# ─── 生理相关 pH 参考 ───

# ADC 药物在体内经历的关键 pH 环境
PHYSIOLOGICAL_PH = {
    "blood": 7.4,  # 血液 —— 连接子必须稳定
    "tumor_microenvironment": 6.5,  # 肿瘤微环境 —— 开始变酸
    "early_endosome": 6.0,  # 早期内吞体
    "late_endosome": 5.5,  # 晚期内吞体
    "lysosome": 5.0,  # 溶酶体 —— 连接子应该在此完全裂解
    "stomach": 2.0,  # 胃（口服药物参考）
}


@dataclass
class PhStabilityResult:
    """pH 稳定性预测结果"""

    smiles: str
    target_ph: float
    is_stable: bool
    labile_groups_found: list[str] = field(default_factory=list)
    stable_groups_found: list[str] = field(default_factory=list)
    recommendation: str = ""
    context: str = ""


class PhSimulator:
    """
    pH 稳定性模拟器

    使用方式:
        sim = PhSimulator()
        result = sim.predict("CC(=O)NNC(=O)c1ccc(cc1)", pH=5.5)
        # → is_stable=False, labile_groups_found=["hydrazone"]
    """

    def __init__(self, labile_groups: Optional[list[PhLabileGroup]] = None):
        """
        Args:
            labile_groups: 自定义 pH 敏感官能团列表。默认使用内置库。
        """
        self.labile_groups = labile_groups or PH_LABILE_GROUPS
        # 预编译 SMARTS 模式以提高性能
        self._compiled_patterns: list[tuple[PhLabileGroup, Chem.Mol]] = []
        for group in self.labile_groups:
            pattern = Chem.MolFromSmarts(group.smarts)
            if pattern is not None:
                self._compiled_patterns.append((group, pattern))

    def predict(self, smiles: str, ph: float = 7.4) -> PhStabilityResult:
        """
        预测分子在指定 pH 下的稳定性。

        Args:
            smiles: 待评估的分子 SMILES
            ph: 目标 pH 值（默认 7.4 = 血液）

        Returns:
            PhStabilityResult 包含稳定性判断和详细分析

        算法:
            1. 解析 SMILES → 分子对象
            2. 遍历所有已知 pH 敏感官能团，检查是否在分子中出现
            3. 对找到的每个官能团，比对 pH 是否在裂解范围内
            4. 综合给出稳定性判断
        """
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES: {smiles}")

        # 增强立体化学感知（提升子结构匹配准确性）
        Chem.AssignStereochemistry(mol, cleanIt=True, force=True)

        labile_found: list[str] = []
        stable_found: list[str] = []

        for group, pattern in self._compiled_patterns:
            if mol.HasSubstructMatch(pattern):
                # 检查：这个 pH 在这个官能团的"裂解区"还是"安全区"？
                if ph <= group.labile_below:
                    labile_found.append(group.name)
                elif ph >= group.stable_above:
                    stable_found.append(group.name)
                # 中间区域：部分不稳定（保守处理，标记为潜在风险）
                else:
                    labile_found.append(f"{group.name}(partial)")

        # 综合判断
        is_stable = len(labile_found) == 0

        # 生成建议
        recommendation = self._generate_recommendation(
            ph, labile_found, stable_found, is_stable
        )

        # 生理上下文
        context = self._get_physiological_context(ph)

        return PhStabilityResult(
            smiles=smiles,
            target_ph=ph,
            is_stable=is_stable,
            labile_groups_found=labile_found,
            stable_groups_found=stable_found,
            recommendation=recommendation,
            context=context,
        )

    def predict_physiological_phases(self, smiles: str) -> dict[str, PhStabilityResult]:
        """
        预测分子在 ADC 递送路径中各个生理 pH 阶段的表现。

        这模拟了注射后 ADC 在体内经历的所有 pH 环境。
        """
        results = {}
        for phase, ph in PHYSIOLOGICAL_PH.items():
            results[phase] = self.predict(smiles, ph)
        return results

    def _generate_recommendation(
        self,
        ph: float,
        labile_found: list[str],
        stable_found: list[str],
        is_stable: bool,
    ) -> str:
        """根据预测结果生成人类可读的建议"""
        if is_stable:
            if stable_found:
                groups = ", ".join(stable_found)
                return (
                    f"pH {ph} 下稳定。检测到的官能团 ({groups}) "
                    f"在该 pH 范围内保持稳定。"
                )
            else:
                return (
                    f"pH {ph} 下稳定。未检测到已知的 pH 敏感官能团。"
                    f"（注意：可能存在规则库未覆盖的裂解机制）"
                )
        else:
            groups = ", ".join(labile_found)
            return (
                f"pH {ph} 下不稳定！以下官能团可能发生裂解: {groups}。"
                f"如果该 pH 是目标裂解条件（如溶酶体 pH 5.0），这是期望行为。"
                f"如果该 pH 是循环条件（如血液 pH 7.4），需要重新设计连接子。"
            )

    @staticmethod
    def _get_physiological_context(ph: float) -> str:
        """给出目标 pH 在人体中的生理位置"""
        closest = min(
            PHYSIOLOGICAL_PH.items(),
            key=lambda x: abs(x[1] - ph),
        )
        return f"pH {ph} 最接近人体的 {closest[0]}（pH {closest[1]}）"


# ─── 便捷函数 ───


def quick_check(smiles: str, ph: float = 7.4) -> str:
    """快速检查：一行代码看结果"""
    sim = PhSimulator()
    result = sim.predict(smiles, ph)
    status = "🟢 稳定" if result.is_stable else "🔴 不稳定"
    return f"{status} | {result.recommendation}"
