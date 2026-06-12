"""
连接子设计引擎（LinkerDesigner）

Week 7 核心模块：pH 感知的连接子设计优化循环。

设计流程:
  1. 解析用户需求 → LinkerDesignRequest
  2. 从骨架数据库筛选匹配的候选
  3. 计算每个候选的分子性质（8 描述符）
  4. 评估 pH 稳定性（全生理阶段）
  5. 多维度打分排序
  6. 返回 Top-N 候选 + 对比分析

多维度评分（每项 0-1，加权平均）:
  - blood_stability: 血液 pH 7.4 必须稳定
  - lysosome_lability: 溶酶体 pH 5.0 期望裂解
  - drug_likeness: QED 药物相似性
  - synthetic_accessibility: SAS 合成难度（反向归一化）
  - overall: 加权综合分

类比:
  这是连接子设计的"招聘系统"——
  骨架库 = 简历库，筛选 = HR初筛，评估 = 技术面，
  打分 = 综合评分，排名 = offer排序
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from adc_linker_agent.domain.ph_simulator import PhSimulator
from adc_linker_agent.domain.properties import MolPropertyCalculator

# ─── 数据模型 ───


class LinkerDesignRequest(BaseModel):
    """
    连接子设计需求。

    Example:
        request = LinkerDesignRequest(
            target_ph=5.5,
            preferred_mechanism="pH_sensitive",
            min_qed=0.3,
            max_sas=6.0,
            max_results=3,
        )
    """

    target_ph: float = Field(
        default=5.0,
        ge=0, le=14,
        description="期望的裂解 pH（默认 5.0 = 溶酶体）",
    )
    preferred_mechanism: str | None = Field(
        default=None,
        description="偏好的裂解机制：pH_sensitive / enzymatic / redox / non_cleavable",
    )
    min_qed: float = Field(
        default=0.2,
        ge=0, le=1,
        description="最低 QED 药物相似性阈值",
    )
    max_sas: float = Field(
        default=7.0,
        ge=1, le=10,
        description="最高合成难度阈值",
    )
    min_molecular_weight: float | None = Field(
        default=None,
        description="最小分子量 (Da)",
    )
    max_molecular_weight: float | None = Field(
        default=None,
        description="最大分子量 (Da)",
    )
    require_blood_stable: bool = Field(
        default=True,
        description="是否要求血液 pH 7.4 稳定",
    )
    max_results: int = Field(
        default=5,
        ge=1, le=20,
        description="返回的最大候选数",
    )


@dataclass
class LinkerCandidate:
    """单个连接子候选的完整评估结果"""

    name: str
    smiles: str
    mechanism: str
    description: str
    drugs_using: list[str] = field(default_factory=list)

    # 分子性质
    logp: float = 0.0
    qed: float = 0.0
    sas: float = 0.0
    tpsa: float = 0.0
    molecular_weight: float = 0.0
    hbd: int = 0
    hba: int = 0
    rotatable_bonds: int = 0

    # pH 稳定性
    blood_stable: bool = True
    lysosome_labile: bool = False
    ph_stability_summary: str = ""

    # 评分 (0-1)
    score_blood_stability: float = 0.0
    score_lysosome_lability: float = 0.0
    score_drug_likeness: float = 0.0
    score_synthetic: float = 0.0
    overall_score: float = 0.0

    # 设计建议
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    recommendation: str = ""


@dataclass
class DesignResult:
    """连接子设计结果"""

    request: LinkerDesignRequest
    candidates: list[LinkerCandidate]
    total_evaluated: int
    total_filtered: int
    design_summary: str = ""

    @property
    def top_candidate(self) -> LinkerCandidate | None:
        return self.candidates[0] if self.candidates else None


# ─── 设计引擎 ───


class LinkerDesigner:
    """
    pH 感知连接子设计引擎。

    使用方式:
        designer = LinkerDesigner()
        result = designer.design(LinkerDesignRequest(target_ph=5.5))

        for c in result.candidates:
            print(f"{c.name}: score={c.overall_score:.2f}")
    """

    # 评分权重
    WEIGHT_BLOOD_STABILITY = 0.35     # 血液稳定性最重要（安全第一）
    WEIGHT_LYSOSOME_LABILITY = 0.30   # 溶酶体裂解（有效性）
    WEIGHT_DRUG_LIKENESS = 0.20       # 药物相似性
    WEIGHT_SYNTHETIC = 0.15           # 合成可行性

    def __init__(self, csv_path: str | None = None):
        """
        Args:
            csv_path: 连接子骨架 CSV 文件路径。
                      默认: <project_root>/data/linker_scaffolds.csv
        """
        if csv_path is None:
            from adc_linker_agent.utils.config import get_config
            config = get_config()
            csv_path = str(config.data_dir / "linker_scaffolds.csv")

        self.csv_path = Path(csv_path)
        self._property_calc = MolPropertyCalculator()
        self._ph_sim = PhSimulator()
        self._scaffolds: list[dict] = self._load_scaffolds()

    def _load_scaffolds(self) -> list[dict]:
        """从 CSV 加载连接子骨架数据库。"""
        scaffolds: list[dict] = []
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 解析列表字段
                if "drugs_using" in row and row["drugs_using"]:
                    row["drugs_using"] = [
                        d.strip() for d in row["drugs_using"].split("|") if d.strip()
                    ]
                else:
                    row["drugs_using"] = []

                # 解析数值字段
                if "trigger_ph" in row and row["trigger_ph"]:
                    try:
                        row["trigger_ph"] = float(row["trigger_ph"])
                    except ValueError:
                        row["trigger_ph"] = None
                else:
                    row["trigger_ph"] = None

                scaffolds.append(row)
        return scaffolds

    @property
    def scaffold_count(self) -> int:
        """骨架数据库中连接子总数"""
        return len(self._scaffolds)

    # ─── 设计主流程 ───

    def design(self, request: LinkerDesignRequest) -> DesignResult:
        """
        执行连接子设计优化循环。

        流程: 筛选 → 评估 → 打分 → 排序 → 返回 Top-N
        """
        # ─── 1. 筛选候选骨架 ───
        candidates = self._filter_scaffolds(request)
        total_evaluated = len(candidates)

        # ─── 2. 评估每个候选 ───
        results: list[LinkerCandidate] = []
        for scaffold in candidates:
            try:
                cand = self._evaluate_candidate(scaffold, request)
                results.append(cand)
            except Exception:
                continue  # 跳过计算失败的候选

        # ─── 3. 多维度打分 ───
        for cand in results:
            self._score_candidate(cand, request)

        # ─── 4. 过滤低分候选 ───
        filtered = [
            c for c in results
            if c.qed >= request.min_qed
            and c.sas <= request.max_sas
            and (not request.require_blood_stable or c.blood_stable)
        ]
        total_filtered = len(results) - len(filtered)

        # ─── 5. 排序 ───
        filtered.sort(key=lambda c: c.overall_score, reverse=True)

        # ─── 6. 截取 Top-N ───
        top = filtered[:request.max_results]

        # ─── 7. 生成设计总结 ───
        summary = self._generate_summary(top, request, total_evaluated, total_filtered)

        return DesignResult(
            request=request,
            candidates=top,
            total_evaluated=total_evaluated,
            total_filtered=total_filtered,
            design_summary=summary,
        )

    # ─── 筛选 ───

    def _filter_scaffolds(self, request: LinkerDesignRequest) -> list[dict]:
        """根据需求筛选匹配的骨架。"""
        matches: list[dict] = []

        for scaffold in self._scaffolds:
            # 机制筛选
            if (
                request.preferred_mechanism
                and scaffold.get("mechanism") != request.preferred_mechanism
            ):
                continue

            # pH 匹配度：骨架的 trigger_ph 应该接近 target_ph
            trigger_ph = scaffold.get("trigger_ph")
            if trigger_ph is not None and request.target_ph:
                ph_diff = abs(trigger_ph - request.target_ph)
                # 允许 ±1.5 pH 单位的容差
                if ph_diff > 1.5:
                    continue

            matches.append(scaffold)

        # 如果没有精确匹配，放宽机制筛选
        if not matches and request.preferred_mechanism:
            for scaffold in self._scaffolds:
                matches.append(scaffold)

        return matches

    # ─── 评估 ───

    def _evaluate_candidate(
        self, scaffold: dict, request: LinkerDesignRequest
    ) -> LinkerCandidate:
        """
        全面评估一个连接子候选。

        计算分子性质 + pH 稳定性 + 优缺点分析。
        """
        name = scaffold.get("name", "Unknown")
        smiles = scaffold.get("smiles", "")
        mechanism = scaffold.get("mechanism", "unknown")

        # ─── 分子性质 ───
        props = self._property_calc.calculate_all(smiles)

        # ─── pH 稳定性 ───
        ph_results = self._ph_sim.predict_physiological_phases(smiles)
        blood_stable = ph_results.get("blood", None)
        lysosome = ph_results.get("lysosome", None)

        blood_ok = blood_stable.is_stable if blood_stable else True
        lysosome_ok = not lysosome.is_stable if lysosome else False

        # 稳定性摘要
        summary_parts = []
        for phase, result in ph_results.items():
            status = "✓" if result.is_stable else "✗"
            summary_parts.append(f"{phase}={status}")
        stability_summary = ", ".join(summary_parts)

        # ─── 优缺点分析 ───
        strengths: list[str] = []
        weaknesses: list[str] = []

        qed = props.get("qed", 0)
        logp = props.get("logp", 0)
        sas = props.get("sas", 0)
        tpsa = props.get("tpsa", 0)

        # QED
        if qed >= 0.5:
            strengths.append(f"良好药物相似性 (QED={qed:.3f})")
        elif qed < 0.3:
            weaknesses.append(f"药物相似性低 (QED={qed:.3f})")

        # LogP
        if 1 <= logp <= 3:
            strengths.append(f"理想亲脂性 (LogP={logp:.1f})")
        elif logp > 5:
            weaknesses.append(f"过度亲油 (LogP={logp:.1f})，有聚集风险")

        # SAS
        if sas <= 4:
            strengths.append(f"合成容易 (SAS={sas:.1f})")
        elif sas > 6:
            weaknesses.append(f"合成困难 (SAS={sas:.1f})")

        # TPSA
        if 80 <= tpsa <= 140:
            strengths.append(f"极性表面积理想 (TPSA={tpsa:.0f})")

        # pH 稳定性
        if blood_ok:
            strengths.append("血液中稳定 ✓")
        else:
            weaknesses.append("⚠️ 血液中不稳定！毒素可能提前释放")

        if lysosome_ok:
            strengths.append("溶酶体中可裂解 ✓")
        elif mechanism != "non_cleavable":
            weaknesses.append("溶酶体中裂解不充分")

        # 推荐
        if blood_ok and lysosome_ok:
            recommendation = (
                f"✅ 推荐：{name} 满足理想 ADC 连接子条件"
                f"（血液稳定 + 溶酶体裂解）"
            )
        elif blood_ok and not lysosome_ok:
            recommendation = (
                f"⚠️ 可用但需优化：{name} 血液稳定但溶酶体裂解不足"
            )
        elif not blood_ok:
            recommendation = (
                f"❌ 不推荐：{name} 在血液中不稳定，不适合 ADC 应用"
            )
        else:
            recommendation = f"需进一步评估：{name}"

        return LinkerCandidate(
            name=name,
            smiles=smiles,
            mechanism=mechanism,
            description=scaffold.get("description", ""),
            drugs_using=scaffold.get("drugs_using", []),
            logp=round(logp, 2),
            qed=round(qed, 3),
            sas=round(sas, 2),
            tpsa=round(tpsa, 1),
            molecular_weight=round(props.get("molecular_weight", 0), 1),
            hbd=props.get("hbd", 0),
            hba=props.get("hba", 0),
            rotatable_bonds=props.get("rotatable_bonds", 0),
            blood_stable=blood_ok,
            lysosome_labile=lysosome_ok,
            ph_stability_summary=stability_summary,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendation=recommendation,
        )

    # ─── 打分 ───

    def _score_candidate(
        self, cand: LinkerCandidate, request: LinkerDesignRequest
    ) -> None:
        """
        多维度综合评分。

        每项归一化到 [0, 1]，加权平均得总分。
        """
        # 1. 血液稳定性 (0 或 1)
        cand.score_blood_stability = 1.0 if cand.blood_stable else 0.0

        # 2. 溶酶体裂解 (0 或 1，non_cleavable 给 0.5)
        if cand.mechanism == "non_cleavable":
            cand.score_lysosome_lability = 0.5
        else:
            cand.score_lysosome_lability = 1.0 if cand.lysosome_labile else 0.3

        # 3. 药物相似性 (QED 本身就在 [0,1])
        cand.score_drug_likeness = min(cand.qed, 1.0)

        # 4. 合成可行性 (SAS: 1=easy, 10=hard → 反向归一化)
        cand.score_synthetic = max(0.0, 1.0 - (cand.sas - 1) / 9)

        # 加权总分
        cand.overall_score = (
            self.WEIGHT_BLOOD_STABILITY * cand.score_blood_stability
            + self.WEIGHT_LYSOSOME_LABILITY * cand.score_lysosome_lability
            + self.WEIGHT_DRUG_LIKENESS * cand.score_drug_likeness
            + self.WEIGHT_SYNTHETIC * cand.score_synthetic
        )

    # ─── 报告生成 ───

    def _generate_summary(
        self,
        candidates: list[LinkerCandidate],
        request: LinkerDesignRequest,
        total_evaluated: int,
        total_filtered: int,
    ) -> str:
        """生成设计结果的人类可读摘要。"""
        if not candidates:
            return (
                f"从 {total_evaluated} 个骨架中未找到符合条件的连接子。"
                f"建议放宽筛选条件（当前 QED≥{request.min_qed}, "
                f"SAS≤{request.max_sas}）。"
            )

        top = candidates[0]
        mechanism_info = {
            "pH_sensitive": "酸敏感裂解（腙键/缩醛/酯等）",
            "enzymatic": "酶裂解（Cathepsin B 等）",
            "redox": "氧化还原裂解（谷胱甘肽还原二硫键）",
            "non_cleavable": "不可裂解（需抗体完全降解）",
        }

        mech_desc = mechanism_info.get(top.mechanism, top.mechanism)

        return (
            f"从 {total_evaluated} 个骨架中筛选，"
            f"过滤 {total_filtered} 个不符合条件，"
            f"返回 Top-{len(candidates)} 候选。\n"
            f"最佳候选: {top.name}（{mech_desc}），"
            f"综合评分 {top.overall_score:.2f}/1.0。"
        )


# ─── 便捷函数 ───


def quick_design(
    target_ph: float = 5.0,
    preferred_mechanism: str | None = None,
    max_results: int = 3,
) -> DesignResult:
    """
    快速设计：一行代码完成连接子设计。

    Example:
        result = quick_design(target_ph=5.5, preferred_mechanism="pH_sensitive")
        for c in result.candidates:
            print(c.name, c.overall_score)
    """
    designer = LinkerDesigner()
    request = LinkerDesignRequest(
        target_ph=target_ph,
        preferred_mechanism=preferred_mechanism,
        max_results=max_results,
    )
    return designer.design(request)
