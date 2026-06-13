"""
结构化报告引擎

将 DesignResult 转换为组会/科研报告格式的结构化数据。
纯数据聚合，不依赖 LLM。

报告结构:
  1. HEADER: 需求摘要 + 候选统计
  2. CANDIDATE TABLE: 多维度对比表
  3. DETAILED CARDS: Top-3 详细卡片
  4. COMPARISON: 关键差异分析
  5. TOXICITY SUMMARY: 毒性/安全性汇总
  6. DISCLAIMER

设计原则:
  - 所有数据来自领域计算结果（DesignResult / LinkerCandidate）
  - 不调用 LLM、不访问外部 API
  - UI 层按 schema 渲染，不解析自然语言
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from adc_linker_agent.domain.linker_designer import DesignResult, LinkerCandidate

# ─── 报告 Schema ───


@dataclass
class CandidateSummary:
    """单个候选的摘要（用于对比表）"""

    rank: int
    name: str
    smiles: str
    mechanism: str
    mechanism_label: str
    overall_score: float
    blood_stable: bool
    lysosome_labile: bool
    qed: float
    logp: float
    sas: float
    tpsa: float
    molecular_weight: float
    has_toxicity_alerts: bool
    toxicity_count: int
    recommendation: str
    risk_flags: list[str] = field(default_factory=list)


@dataclass
class DesignReport:
    """连接子设计结构化报告"""

    # Header
    generated_at: str
    request_summary: str
    total_evaluated: int
    total_filtered: int
    candidate_count: int

    # Candidate table
    candidates: list[CandidateSummary]

    # Top-3 detailed cards
    detailed_cards: list[dict]

    # Comparison
    comparison_text: str
    comparison_dimensions: list[dict]

    # Toxicity
    has_any_toxicity: bool
    toxicity_summary: str

    # Warnings
    warnings: list[str]
    failed_scaffolds: list[dict]


# ─── 报告生成 ───


def generate_report(result: DesignResult) -> DesignReport:
    """
    从 DesignResult 生成结构化报告。

    Args:
        result: LinkerDesigner.design() 的返回结果

    Returns:
        DesignReport — 结构化报告数据，UI 层直接渲染
    """
    candidates = result.candidates
    request = result.request

    # ─── Header ───
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    request_summary = _build_request_summary(request)

    # ─── Candidate Table ───
    candidate_summaries = [_summarize_candidate(c, i + 1) for i, c in enumerate(candidates)]

    # ─── Detailed Cards (Top-3) ───
    detailed_cards = [_build_detailed_card(c, i + 1) for i, c in enumerate(candidates[:3])]

    # ─── Comparison ───
    comparison_text, comparison_dimensions = _build_comparison(candidates)

    # ─── Toxicity ───
    has_any, tox_summary = _build_toxicity_summary(candidates)
    warnings = _build_warnings(candidates)

    return DesignReport(
        generated_at=generated_at,
        request_summary=request_summary,
        total_evaluated=result.total_evaluated,
        total_filtered=result.total_filtered,
        candidate_count=len(candidates),
        candidates=candidate_summaries,
        detailed_cards=detailed_cards,
        comparison_text=comparison_text,
        comparison_dimensions=comparison_dimensions,
        has_any_toxicity=has_any,
        toxicity_summary=tox_summary,
        warnings=warnings,
        failed_scaffolds=result.failed_scaffolds,
    )


# ─── 私有 helper ───


def _build_request_summary(request) -> str:
    """构建需求摘要文本"""
    parts = [f"目标 pH: {request.target_ph}"]
    if request.preferred_mechanism:
        mech_labels = {
            "pH_sensitive": "酸敏感裂解",
            "enzymatic": "酶裂解",
            "redox": "氧化还原裂解",
            "non_cleavable": "不可裂解",
        }
        label = mech_labels.get(request.preferred_mechanism, request.preferred_mechanism)
        parts.append(f"偏好机制: {label}")
    parts.append(f"QED ≥ {request.min_qed} | SAS ≤ {request.max_sas}")
    if request.require_blood_stable:
        parts.append("血液稳定性: 必需")
    existing_params = {p.split(":")[0].strip() for p in parts}
    new_part = f"返回 Top-{request.max_results}"
    if new_part.split(":")[0].strip() not in existing_params:
        parts.append(new_part)
    return " | ".join(parts)


MECHANISM_LABELS = {
    "pH_sensitive": "🔴 酸敏感",
    "enzymatic": "🟢 酶裂解",
    "redox": "🟡 氧化还原",
    "non_cleavable": "⚫ 不可裂解",
}


def _summarize_candidate(c: LinkerCandidate, rank: int) -> CandidateSummary:
    """将 LinkerCandidate 转为对比表摘要"""
    return CandidateSummary(
        rank=rank,
        name=c.name,
        smiles=c.smiles,
        mechanism=c.mechanism,
        mechanism_label=MECHANISM_LABELS.get(c.mechanism, c.mechanism),
        overall_score=round(c.overall_score, 3),
        blood_stable=c.blood_stable,
        lysosome_labile=c.lysosome_labile,
        qed=round(c.qed, 3),
        logp=round(c.logp, 1),
        sas=round(c.sas, 1),
        tpsa=round(c.tpsa, 1),
        molecular_weight=round(c.molecular_weight, 1),
        has_toxicity_alerts=c.has_toxicity_alerts,
        toxicity_count=len(c.toxicity_alerts),
        recommendation=c.recommendation,
        risk_flags=list(c.risk_flags),
    )


def _build_detailed_card(c: LinkerCandidate, rank: int) -> dict:
    """构建单个候选的详细卡片数据"""
    return {
        "rank": rank,
        "name": c.name,
        "smiles": c.smiles,
        "mechanism": c.mechanism,
        "mechanism_label": MECHANISM_LABELS.get(c.mechanism, c.mechanism),
        "description": c.description,
        "drugs_using": c.drugs_using,
        # 性质仪表盘
        "properties": {
            "logp": {"value": c.logp, "ideal": "1-3", "status": _logp_status(c.logp)},
            "qed": {"value": c.qed, "ideal": "≥0.5", "status": _qed_status(c.qed)},
            "sas": {"value": c.sas, "ideal": "≤4", "status": _sas_status(c.sas)},
            "tpsa": {"value": c.tpsa, "ideal": "80-140", "status": _tpsa_status(c.tpsa)},
            "molecular_weight": {"value": c.molecular_weight, "unit": "Da"},
            "hbd": c.hbd,
            "hba": c.hba,
            "rotatable_bonds": c.rotatable_bonds,
        },
        # pH 稳定性
        "ph_stability": {
            "blood_stable": c.blood_stable,
            "lysosome_labile": c.lysosome_labile,
            "summary": c.ph_stability_summary,
        },
        # 评分
        "scores": {
            "blood_stability": round(c.score_blood_stability, 3),
            "lysosome_lability": round(c.score_lysosome_lability, 3),
            "drug_likeness": round(c.score_drug_likeness, 3),
            "synthetic": round(c.score_synthetic, 3),
            "overall": round(c.overall_score, 3),
        },
        "strengths": c.strengths,
        "weaknesses": c.weaknesses,
        "recommendation": c.recommendation,
        "has_toxicity_alerts": c.has_toxicity_alerts,
        "toxicity_alerts": c.toxicity_alerts,
        "risk_flags": c.risk_flags,
    }


# ─── 状态判断 helpers ───


def _logp_status(logp: float) -> str:
    if 1 <= logp <= 3:
        return "ideal"
    if logp > 5:
        return "warning"
    return "ok"


def _qed_status(qed: float) -> str:
    if qed >= 0.5:
        return "ideal"
    if qed < 0.3:
        return "warning"
    return "ok"


def _sas_status(sas: float) -> str:
    if sas <= 4:
        return "ideal"
    if sas > 6:
        return "warning"
    return "ok"


def _tpsa_status(tpsa: float) -> str:
    if 80 <= tpsa <= 140:
        return "ideal"
    return "ok"


# ─── 对比分析 ───


def _build_comparison(candidates: list[LinkerCandidate]) -> tuple[str, list[dict]]:
    """
    生成候选间关键差异对比。

    Returns:
        (comparison_text, comparison_dimensions)
    """
    if len(candidates) < 2:
        return "仅有一个候选，无法进行对比分析。", []

    dimensions = []

    # 总体评分差异
    best = candidates[0]
    worst = candidates[-1]
    score_gap = best.overall_score - worst.overall_score
    if score_gap > 0.3:
        dimensions.append({
            "dimension": "综合评分差距",
            "detail": (
                f"最佳候选 ({best.name}: {best.overall_score:.3f}) 与"
                f"最低候选 ({worst.name}: {worst.overall_score:.3f}) 差距 {score_gap:.2f}。"
                f"差距显著，推荐优先考虑前 2 名。"
            ),
        })

    # 机制分布
    mechanisms = set(c.mechanism for c in candidates)
    if len(mechanisms) > 1:
        dimensions.append({
            "dimension": "裂解机制多样性",
            "detail": (
                f"Top-{len(candidates)} 覆盖 {len(mechanisms)} 种裂解机制: "
                f"{', '.join(sorted(mechanisms))}。"
                f"建议根据目标肿瘤类型和 payload 特性选择最合适的机制。"
            ),
        })

    # 毒性对比
    toxic_candidates = [c for c in candidates if c.has_toxicity_alerts]
    clean_candidates = [c for c in candidates if not c.has_toxicity_alerts]
    if toxic_candidates and clean_candidates:
        dimensions.append({
            "dimension": "安全性对比",
            "detail": (
                f"{len(toxic_candidates)} 个候选有毒性警报"
                f"（{', '.join(c.name for c in toxic_candidates)}），"
                f"{len(clean_candidates)} 个候选通过毒性筛查"
                f"（{', '.join(c.name for c in clean_candidates)}）。"
                f"建议排除含 PAINS/Brenk 警报的候选。"
            ),
        })

    # QED 分布
    qed_values = [c.qed for c in candidates]
    qed_spread = max(qed_values) - min(qed_values)
    if qed_spread > 0.2:
        dimensions.append({
            "dimension": "药物相似性 (QED) 分布",
            "detail": (
                f"QED 范围: {min(qed_values):.3f} — {max(qed_values):.3f} "
                f"(差距: {qed_spread:.3f})。"
                f"QED ≥ 0.5 为理想药物样分子。"
            ),
        })

    if not dimensions:
        dimensions.append({
            "dimension": "候选相似度高",
            "detail": "各候选在核心指标上差异较小，建议综合权衡合成难度和文献支持选择。",
        })

    comparison_text = "; ".join(d["detail"] for d in dimensions)
    return comparison_text, dimensions


# ─── 毒性汇总 ───


def _build_toxicity_summary(candidates: list[LinkerCandidate]) -> tuple[bool, str]:
    """构建毒性/安全性汇总"""
    toxic_count = sum(1 for c in candidates if c.has_toxicity_alerts)
    total_alerts = sum(len(c.toxicity_alerts) for c in candidates)

    if toxic_count == 0:
        return False, "✅ 所有候选均通过 PAINS 和 Brenk 毒性筛查。"

    if toxic_count == len(candidates):
        return True, (
            f"🚨 所有 {len(candidates)} 个候选均检测到毒性/假阳性警报 "
            f"(共 {total_alerts} 条)。强烈建议重新设计或更换骨架。"
        )

    return True, (
        f"⚠️ {toxic_count}/{len(candidates)} 个候选检测到毒性/假阳性警报 "
        f"(共 {total_alerts} 条)。建议优先选择通过筛查的候选。"
    )


def _build_warnings(candidates: list[LinkerCandidate]) -> list[str]:
    """从候选优缺点中提取全局警告"""
    warnings: list[str] = []
    blood_unstable = [c.name for c in candidates if not c.blood_stable]
    if blood_unstable:
        warnings.append(
            f"⚠️ 血液不稳定候选: {', '.join(blood_unstable)}。"
            f"在血液中不稳定会导致毒素提前释放（全身毒性风险）。"
        )

    low_qed = [c.name for c in candidates if c.qed < 0.3]
    if low_qed:
        warnings.append(
            f"⚠️ 低药物相似性: {', '.join(low_qed)}。"
            f"QED < 0.3 表示需要大量结构优化。"
        )

    hard_synthesis = [c.name for c in candidates if c.sas > 6]
    if hard_synthesis:
        warnings.append(
            f"⚠️ 合成困难: {', '.join(hard_synthesis)}。"
            f"SAS > 6 表示合成路线复杂、成本高。"
        )

    return warnings
