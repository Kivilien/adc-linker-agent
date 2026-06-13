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

规则外部化:
    pH 敏感官能团规则存储在 data/ph_labile_groups.yaml。
    可通过编辑 YAML 添加/修改规则，无需改 Python 源码。
    YAML 不可用时自动回退到内置硬编码列表。
"""

from dataclasses import dataclass, field
from pathlib import Path

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
    """一个化学官能团规则（pH敏感、酶催化、或氧化还原触发）"""

    name: str
    smarts: str
    pka_typical: float  # 典型 pKa（非 pH 驱动时为 0.0）
    labile_below: float  # 低于此 pH 开始裂解（所有机制统一用 pH 阈值编码）
    stable_above: float  # 高于此 pH 保持稳定
    mechanism: str = ""
    mechanism_type: str = "pH_sensitive"  # "pH_sensitive" | "enzymatic" | "redox"
    enzyme_name: str = ""  # 酶名称，如 "Cathepsin B"（仅 enzymatic）
    trigger_description: str = ""  # 人类可读的触发描述，如 "谷胱甘肽还原"


def load_labile_groups(yaml_path: str | None = None) -> list[PhLabileGroup]:
    """
    从 YAML 文件加载 pH 敏感官能团规则。

    Args:
        yaml_path: YAML 文件路径。默认使用 data/ph_labile_groups.yaml。

    Returns:
        PhLabileGroup 列表。YAML 不可用时返回内置硬编码列表。

    加载顺序: YAML → 内置硬编码列表（降级）
    """
    if yaml_path is None:
        from adc_linker_agent.utils.config import get_config

        config = get_config()
        yaml_path = str(config.ph_labile_groups_path)

    path = Path(yaml_path)
    if path.exists():
        try:
            import yaml

            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if data and "groups" in data:
                groups: list[PhLabileGroup] = []
                for item in data["groups"]:
                    groups.append(
                        PhLabileGroup(
                            name=item["name"],
                            smarts=item["smarts"],
                            pka_typical=item["pka_typical"],
                            labile_below=item["labile_below"],
                            stable_above=item["stable_above"],
                            mechanism=item.get("mechanism", ""),
                            mechanism_type=item.get("mechanism_type", "pH_sensitive"),
                            enzyme_name=item.get("enzyme_name", ""),
                            trigger_description=item.get("trigger_description", ""),
                        )
                    )
                return groups
        except Exception:
            pass  # YAML 解析失败 → 降级到内置列表

    # 降级：返回内置硬编码列表
    return _builtin_labile_groups()


def _builtin_labile_groups() -> list[PhLabileGroup]:
    """内置硬编码 pH 敏感官能团列表（YAML 不可用时的降级方案）。"""
    return [
    PhLabileGroup(
        name="hydrazone",
        smarts="[CX3](=[OX1])[NX2][NX3]",
        pka_typical=5.0,
        labile_below=6.0,
        stable_above=6.5,
        mechanism=(
            "酸催化水解（H⁺为催化剂，H₂O 为反应物）："
            "R₂C=N-NH-CO-R' + H₂O → R₂C=O + H₂N-NH-CO-R'。"
            "H⁺质子化 C=N 使碳更具亲电性→水亲核进攻→H⁺再生。"
        ),
    ),
    PhLabileGroup(
        name="acetal",
        smarts="[OX2][CX4H1]([OX2])[CX4]",
        pka_typical=4.5,
        labile_below=5.5,
        stable_above=6.0,
        mechanism=(
            "酸催化水解（H⁺为催化剂，H₂O 为反应物）："
            "R₂C(OR')₂ + H₂O → R₂C=O + 2 HO-R'。"
            "H⁺质子化一个烷氧基→水亲核进攻断裂第一个醚键→"
            "半缩醛中间体→第二个醚键断裂→H⁺再生。"
        ),
    ),
    PhLabileGroup(
        name="ketal",
        smarts="[OX2][CX4]([OX2])([CX4])[CX4]",
        pka_typical=4.5,
        labile_below=5.5,
        stable_above=6.0,
        mechanism=(
            "酸催化水解（H⁺为催化剂，H₂O 为反应物）："
            "R₂C(OR')₂ + H₂O → R₂C=O + 2 HO-R'。"
            "与缩醛机理相同，但起始原料为酮而非醛。"
        ),
    ),
    PhLabileGroup(
        name="carboxylic_ester",
        smarts="[CX3](=[OX1])[OX2][CX4]",
        pka_typical=7.0,
        labile_below=5.0,
        stable_above=7.0,
        mechanism=(
            "酸催化水解（H⁺为催化剂，不被消耗）："
            "R-COOR' + H₂O → R-COOH + HO-R'。"
            "H⁺先质子化羰基氧使碳更具亲电性，水分子亲核进攻后 H⁺再生。"
        ),
    ),
    PhLabileGroup(
        name="carbamate",
        smarts="[NX3][CX3](=[OX1])[OX2]",
        pka_typical=6.5,
        labile_below=5.5,
        stable_above=7.0,
        mechanism=(
            "酸催化分解（H⁺为催化剂，不被消耗；H₂O 为实际反应物）："
            "R-O-CO-NHR' + H₂O → R-OH + CO₂↑ + H₂N-R'。"
            "分三步：(1)H⁺质子化羰基氧→(2)H₂O 亲核进攻、C-O 断裂释放醇→"
            "(3)氨基甲酸中间体自发脱羧释放 CO₂+胺，H⁺再生。"
            "PABC 自毁连接子的核心机制。"
        ),
    ),
    PhLabileGroup(
        name="imine",
        smarts="[CX3](=[NX2])[CX4]",
        pka_typical=5.5,
        labile_below=6.0,
        stable_above=7.0,
        mechanism=(
            "酸催化水解（H⁺为催化剂，H₂O 为反应物）："
            "R₂C=N-R' + H₂O → R₂C=O + H₂N-R'。"
            "H⁺质子化亚胺氮→水亲核进攻→C=N 断裂→H⁺再生（席夫碱水解）。"
        ),
    ),
    PhLabileGroup(
        name="silyl_ether",
        smarts="[SiX4][OX2][CX4]",
        pka_typical=4.0,
        labile_below=5.0,
        stable_above=6.0,
        mechanism=(
            "酸催化裂解（H⁺为催化剂，H₂O 为反应物）："
            "R₃Si-O-R' + H₂O → R₃Si-OH + HO-R'。"
            "H⁺促进 Si-O 键断裂（在 ADC 中较少使用）。"
        ),
        mechanism_type="pH_sensitive",
        trigger_description="酸催化水解",
    ),
    # ─── 酶裂解机制 ───
    PhLabileGroup(
        name="val_dipeptide",
        smarts="[CX4H1]([CH3])([CH3])[CX4H1][CX3](=[OX1])[NX3]",
        pka_typical=0.0,
        labile_below=5.5,
        stable_above=7.0,
        mechanism=(
            "酶催化裂解：Cathepsin B（半胱氨酸蛋白酶）识别 Val-Cit 或 "
            "Val-Ala 二肽序列，在溶酶体酸性环境（pH 4.5-5.5）中切割酰胺键。"
            "裂解后触发 PABC 自毁间隔臂消除，释放游离药物。"
            "这是 ADC 中最成熟、应用最广泛的连接子类型（Adcetris®、Polivy® 等）。"
        ),
        mechanism_type="enzymatic",
        enzyme_name="Cathepsin B",
        trigger_description="Cathepsin B 酶切 (Val-Cit/Val-Ala 二肽)",
    ),
    PhLabileGroup(
        name="glucuronide",
        smarts="[OX2]([CX4H1][CX4H1]([OX2H1])[CX4H1]([OX2H1])[CX4H1]([OX2H1])[CX4H1]([CX3](=[OX1])[OX2H1])[OX2])[cX3]",
        pka_typical=0.0,
        labile_below=5.5,
        stable_above=7.0,
        mechanism=(
            "酶催化裂解：β-glucuronidase 催化葡萄糖苷酸键水解，"
            "释放醇/酚类药物。该酶在溶酶体和肿瘤坏死区域高表达，"
            "但在血液中活性低，使葡萄糖苷酸连接子具有较好的肿瘤选择性。"
        ),
        mechanism_type="enzymatic",
        enzyme_name="β-glucuronidase",
        trigger_description="β-glucuronidase 酶切 (葡萄糖苷酸)",
    ),
    PhLabileGroup(
        name="beta_lactam",
        smarts="[CX3]1(=[OX1])[NX3][CX4][CX4]1",
        pka_typical=4.0,
        labile_below=4.5,
        stable_above=6.5,
        mechanism=(
            "酶催化开环：β-内酰胺四元环具有高环张力（~26 kcal/mol），"
            "对亲核试剂（水、酶活性位点丝氨酸）高度活泼。"
            "β-lactamase 催化水解开环生成 β-氨基酸衍生物。"
            "在 ADC 中作为酶触发释放元件使用。"
        ),
        mechanism_type="enzymatic",
        enzyme_name="β-lactamase",
        trigger_description="β-lactamase 酶切 (β-内酰胺开环)",
    ),
    # ─── 氧化还原机制 ───
    PhLabileGroup(
        name="disulfide",
        smarts="[#6][SX2][SX2][#6]",
        pka_typical=0.0,
        labile_below=6.5,
        stable_above=7.0,
        mechanism=(
            "还原裂解：R-S-S-R' + 2 GSH → R-SH + HS-R' + GSSG。"
            "肿瘤细胞内谷胱甘肽浓度（~1-10 mM）远高于血液（~0.5-5 μM），"
            "因此二硫键连接子在血液循环中稳定，进入肿瘤细胞后被还原裂解。"
            "Mylotarg®（Gemtuzumab ozogamicin）使用的就是二硫键连接子。"
        ),
        mechanism_type="redox",
        trigger_description="谷胱甘肽 (GSH) 还原裂解",
    ),
    PhLabileGroup(
        name="azo",
        smarts="[NX2]=[NX2]",
        pka_typical=0.0,
        labile_below=6.5,
        stable_above=7.0,
        mechanism=(
            "偶氮键（R-N=N-R'）在缺氧条件下被偶氮还原酶还原为两分子胺。"
            "实体肿瘤常存在缺氧区域，偶氮还原酶活性升高，"
            "使偶氮连接子具有一定的肿瘤选择性。"
        ),
        mechanism_type="redox",
        trigger_description="偶氮还原酶裂解 (缺氧条件)",
    ),
    # ─── 酸敏感机制（扩展） ───
    PhLabileGroup(
        name="orthoester",
        smarts="[CX4]([OX2])([OX2])([OX2])",
        pka_typical=3.5,
        labile_below=5.0,
        stable_above=6.5,
        mechanism=(
            "原酸酯（R-C(OR')₃）对酸极度敏感，在 pH 5 以下快速水解。"
            "H⁺质子化一个烷氧基→水亲核进攻→醇离去→"
            "重复两次→最终生成酯和水。"
            "原酸酯连接子能在溶酶体中快速裂解，释放速率比腙键和酯键更快。"
        ),
        mechanism_type="pH_sensitive",
        trigger_description="酸催化水解 (超快，t₁/₂ < 1 min @ pH 5)",
    ),
    PhLabileGroup(
        name="phosphoramidate",
        smarts="[PX4](=[OX1])([OX2])([OX2])[NX3]",
        pka_typical=3.0,
        labile_below=4.5,
        stable_above=6.5,
        mechanism=(
            "磷酰胺酯（R-O-P(=O)(-OH)-NHR'）在酸性条件下 P-N 键断裂。"
            "H⁺质子化氮原子使 P-N 键削弱→水或邻近羟基亲核进攻→"
            "释放胺和磷酸酯。"
        ),
        mechanism_type="pH_sensitive",
        trigger_description="酸催化水解 (P-N 键断裂)",
    ),
    ]


# 向后兼容：模块级变量，首次访问时从 YAML 加载（降级 → 内置列表）
PH_LABILE_GROUPS: list[PhLabileGroup] = load_labile_groups()


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


# ─── 通用官能团 SMARTS 库（用于框架外检测） ───
#
# 这些是分子中常见的官能团，不仅限于 pH 敏感的 7 个。
# 当 PH_LABILE_GROUPS 匹配不到时，用这个库告诉用户"你的分子里有什么"。
GENERAL_FUNCTIONAL_GROUPS: dict[str, str] = {
    "amide": "[NX3][CX3](=[OX1])[#6]",
    "ester": "[#6][CX3](=[OX1])[OX2][#6]",
    "carboxylic_acid": "[CX3](=[OX1])[OX2H1]",
    "alcohol": "[OX2H][CX4]",
    "phenol": "[OX2H]c",
    "ether": "[OD2]([#6])[#6]",
    "amine_primary": "[NX3H2][CX4]",
    "amine_secondary": "[NX3H1]([CX4])[CX4]",
    "amine_tertiary": "[NX3]([CX4])([CX4])[CX4]",
    "ketone": "[#6][CX3](=[OX1])[#6]",
    "aldehyde": "[CX3H1](=[OX1])[#6]",
    "nitro": "[NX3](=[OX1])=[OX1]",
    "nitrile": "[CX2]#[NX1]",
    "sulfonamide": "[#6][SX4](=[OX1])(=[OX1])[NX3]",
    "thioether": "[#6][SX2][#6]",
    "disulfide": "[#6][SX2][SX2][#6]",
    "aromatic_ring": "a1aaaaa1",
    "alkene": "[CX3]=[CX3]",
    "alkyne": "[CX2]#[CX2]",
    "carbonate": "[OX2][CX3](=[OX1])[OX2]",
    "urea": "[NX3][CX3](=[OX1])[NX3]",
    "halogen": "[F,Cl,Br,I]",
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
    # 新增：分子中检测到的所有官能团（含规则库内和库外）
    all_detected_groups: list[str] = field(default_factory=list)
    groups_in_library: list[str] = field(default_factory=list)
    groups_outside_library: list[str] = field(default_factory=list)
    library_coverage: float = 0.0  # 0.0~1.0，库内/总检测 的比例


class PhSimulator:
    """
    pH 稳定性模拟器

    使用方式:
        sim = PhSimulator()
        result = sim.predict("CC(=O)NNC(=O)c1ccc(cc1)", pH=5.5)
        # → is_stable=False, labile_groups_found=["hydrazone"]
    """

    def __init__(self, labile_groups: list[PhLabileGroup] | None = None):
        """
        Args:
            labile_groups: 自定义 pH 敏感官能团列表。
                           默认从 data/ph_labile_groups.yaml 加载（降级到内置列表）。
        """
        self.labile_groups = labile_groups if labile_groups is not None else load_labile_groups()
        # 预编译 SMARTS 模式以提高性能
        self._compiled_patterns: list[tuple[PhLabileGroup, Chem.Mol]] = []
        for group in self.labile_groups:
            pattern = Chem.MolFromSmarts(group.smarts)
            if pattern is not None:
                self._compiled_patterns.append((group, pattern))

        # 预编译通用官能团 SMARTS（用于框架外检测）
        self._general_patterns: dict[str, Chem.Mol] = {}
        for fg_name, fg_smarts in GENERAL_FUNCTIONAL_GROUPS.items():
            pattern = Chem.MolFromSmarts(fg_smarts)
            if pattern is not None:
                self._general_patterns[fg_name] = pattern

    def _is_covered_by_library(self, fg_name: str) -> bool:
        """判断通用官能团是否被规则库覆盖"""
        coverage_map = {
            "ester": "carboxylic_ester",
            "carbonate": "carbamate",
            "disulfide": "disulfide",  # 新增：二硫键现已覆盖
        }
        covered_name = coverage_map.get(fg_name, fg_name)
        covered_names = {g.name for g in self.labile_groups}
        if covered_name in covered_names:
            return True
        # 模糊匹配：通用官能团名出现在任一 pH 敏感规则名中
        return any(
            covered_name in g.name or g.name in covered_name
            for g in self.labile_groups
        )

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

        # 步骤 1: 遍历 pH 敏感官能团规则库（框架内检测）
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

        # 步骤 2: 扫描通用官能团（框架外检测 — 告诉用户分子里有什么）
        all_detected: list[str] = []
        in_library: list[str] = []
        outside_library: list[str] = []

        # 先用通用 SMARTS 扫描
        for fg_name in self._general_patterns:
            pattern = self._general_patterns[fg_name]
            if mol.HasSubstructMatch(pattern):
                all_detected.append(fg_name)
                # 判断是否被 7 个 pH 敏感规则覆盖
                is_covered = self._is_covered_by_library(fg_name)
                if is_covered:
                    in_library.append(fg_name)
                else:
                    outside_library.append(fg_name)

        # 加上 pH 敏感库直接匹配到的（可能跟通用库有重叠）
        for g in labile_found + stable_found:
            clean_name = g.replace("(partial)", "").strip()
            if clean_name not in all_detected:
                all_detected.append(clean_name)
                in_library.append(clean_name)

        # 计算规则库覆盖率
        library_coverage = (
            len(in_library) / len(all_detected) if all_detected else 1.0
        )

        # 综合判断
        is_stable = len(labile_found) == 0

        # 生成建议（含框架外讨论提示）
        recommendation = self._generate_recommendation(
            ph, labile_found, stable_found, is_stable,
            all_detected, in_library, outside_library, library_coverage,
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
            all_detected_groups=all_detected,
            groups_in_library=in_library,
            groups_outside_library=outside_library,
            library_coverage=library_coverage,
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
        all_detected: list[str],
        in_library: list[str],
        outside_library: list[str],
        library_coverage: float,
    ) -> str:
        """根据预测结果生成人类可读的建议，区分 pH/酶/氧化还原机制"""
        parts: list[str] = []

        # ─── 构建 group_name → PhLabileGroup 映射（用于获取机制详情）───
        group_map: dict[str, PhLabileGroup] = {}
        for g in self.labile_groups:
            group_map[g.name] = g

        # ─── 按机制类型分组 labile groups ───
        ph_labile: list[str] = []
        enzymatic_labile: list[str] = []
        redox_labile: list[str] = []

        for raw_name in labile_found:
            clean = raw_name.replace("(partial)", "").strip()
            g = group_map.get(clean)
            if g and g.mechanism_type == "enzymatic":
                enzymatic_labile.append(raw_name)
            elif g and g.mechanism_type == "redox":
                redox_labile.append(raw_name)
            else:
                ph_labile.append(raw_name)

        # ─── 框架内：有匹配到官能团 ───
        if labile_found or stable_found:
            if is_stable:
                parts.append(f"✅ pH {ph} 下稳定。")
                if stable_found:
                    details = []
                    for s in stable_found:
                        g = group_map.get(s)
                        if g and g.trigger_description:
                            details.append(f"{s}({g.trigger_description})")
                        else:
                            details.append(s)
                    parts.append(
                        f"检测到的官能团 ({', '.join(details)}) 在此条件下保持稳定。"
                    )
            else:
                total_labile = len(labile_found)
                parts.append(f"⚠️ pH {ph} 下不稳定！检测到 {total_labile} 个可裂解官能团。")

                # 按机制分类报告
                if ph_labile:
                    parts.append(f"🔴 酸敏感裂解: {', '.join(ph_labile)}")
                if enzymatic_labile:
                    enzyme_names = set()
                    for e in enzymatic_labile:
                        clean = e.replace("(partial)", "").replace("(enzymatic)", "").strip()
                        g = group_map.get(clean)
                        if g and g.enzyme_name:
                            enzyme_names.add(g.enzyme_name)
                    parts.append(
                        f"🟢 酶催化裂解: {', '.join(enzymatic_labile)} "
                        f"（{', '.join(enzyme_names)} 触发）"
                    )
                if redox_labile:
                    parts.append(f"🟡 氧化还原裂解: {', '.join(redox_labile)}")

                # 生理意义解释
                if ph >= 7.0:
                    parts.append(
                        "血液 pH ≥7.0 条件下不稳定意味着"
                        "连接子会提前释放载荷（⚠️ 高全身毒性风险！）。"
                    )
                elif ph <= 5.5:
                    parts.append(
                        "如果目标是溶酶体裂解（pH 4.5-5.5），这是期望行为——"
                        "ADC 在血液中稳定、进入细胞后被触发释放。"
                    )

            if outside_library:
                parts.append(
                    f"（另外检测到 {len(outside_library)} 个规则库外的官能团: "
                    f"{', '.join(outside_library)}，其稳定性未知）"
                )

        # ─── 框架外：未匹配到任何官能团 ───
        else:
            if all_detected:
                parts.append(f"🔍 pH {ph} 下未检测到已知敏感官能团。")
                parts.append(
                    f"但分子中检测到 {len(all_detected)} 个官能团: "
                    f"{', '.join(all_detected)}。"
                )
                if outside_library:
                    parts.append(
                        f"⚠️ {len(outside_library)} 个官能团不在 "
                        f"当前 {len(self.labile_groups)} 种规则库内: "
                        f"{', '.join(outside_library)}。"
                    )
                    parts.append(
                        f"规则库覆盖率仅 {library_coverage:.0%}。"
                        f"这些官能团的稳定性行为无法自动预测。"
                    )
                    parts.append(
                        "💬 建议讨论："
                        "(1) 这些官能团在文献中的稳定性如何？"
                        "(2) 是否有已知 ADC 连接子使用过类似结构？"
                        "(3) 是否可用 search_literature 工具查找相关证据？"
                    )
                else:
                    parts.append("所有检测到的官能团均被规则库覆盖。分子判断为稳定。")
            else:
                parts.append(
                    f"❓ pH {ph} 下：未检测到任何已知官能团。"
                    f"该分子结构可能过于简单或不含典型官能团。"
                    f"请确认 SMILES 是否正确、完整。"
                )

        return " ".join(parts)

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
