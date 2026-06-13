"""
连接子设计工具 —— MCP Tool

封装 LinkerDesigner 的设计优化循环为 LLM 可调用的工具。
这是 ADC Agent 的"核心武器"——从需求到候选连接子的全流程。

Week 7 新增，与 tool_linker.py（简单搜索）互补：
  - search_linker_scaffolds: 查询骨架库（Week 3）
  - design_linker: 设计优化循环（Week 7）← 本文件
"""


from adc_linker_agent.domain.linker_designer import (
    DesignResult,
    LinkerDesigner,
    LinkerDesignRequest,
)
from adc_linker_agent.domain.report import DesignReport, generate_report

# ─── 单例（避免重复加载 CSV） ───
_designer: LinkerDesigner | None = None


def _get_designer() -> LinkerDesigner:
    global _designer
    if _designer is None:
        _designer = LinkerDesigner()
    return _designer


def design_linker(
    target_ph: float = 5.0,
    preferred_mechanism: str | None = None,
    min_qed: float = 0.2,
    max_sas: float = 7.0,
    require_blood_stable: bool = True,
    max_results: int = 3,
    weights: dict[str, float] | None = None,
) -> dict:
    """
    Design ADC linker candidates based on target requirements.

    This is the MAIN design tool. It runs the full optimization loop:
    filter scaffolds → evaluate properties → assess pH stability →
    multi-criteria scoring → rank → return top candidates.

    Use this tool when the user wants to:
    - Design a new linker for a specific pH trigger
    - Find the best linker for a given payload
    - Compare linker candidates side-by-side

    Args:
        target_ph: Desired cleavage pH (default 5.0 = lysosome).
                   Use 5.5 for late endosome, 6.5 for tumor microenvironment.
        preferred_mechanism: Preferred cleavage mechanism.
                             One of: "pH_sensitive", "enzymatic", "redox", "non_cleavable".
                             If None, considers all mechanisms.
        min_qed: Minimum drug-likeness threshold (0-1, default 0.2).
        max_sas: Maximum synthetic difficulty (1-10, default 7.0).
        require_blood_stable: If True, only returns candidates stable at pH 7.4 (default True).
        max_results: Maximum number of candidates to return (default 3).
        weights: Optional custom scoring weights dict with keys:
                 blood_stability, lysosome_lability, drug_likeness, synthetic.
                 Values are normalized to sum=1.0. Default uses built-in weights.

    Returns:
        dict with keys:
        - candidates: list of ranked linker candidates with full evaluation
        - total_evaluated: number of scaffolds considered
        - total_filtered: number filtered out
        - design_summary: human-readable summary
    """
    designer = _get_designer() if weights is None else LinkerDesigner(weights=weights)

    request = LinkerDesignRequest(
        target_ph=target_ph,
        preferred_mechanism=preferred_mechanism,
        min_qed=min_qed,
        max_sas=max_sas,
        require_blood_stable=require_blood_stable,
        max_results=max_results,
    )

    result: DesignResult = designer.design(request)

    # 生成结构化报告（单次遍历 candidates）
    report: DesignReport = generate_report(result)

    # 从 report 派生 LLM 用 candidates_data，消除手动二次迭代
    # Top-N（detailed_cards 中的）→ 完整数据；超出的 → CandidateSummary 基础数据
    candidates_data = []
    for i, cs in enumerate(report.candidates):
        if i < len(report.detailed_cards):
            dc = report.detailed_cards[i]
            candidates_data.append({
                "rank": cs.rank,
                "name": cs.name,
                "smiles": cs.smiles,
                "mechanism": cs.mechanism,
                "description": dc.get("description", ""),
                "drugs_using": dc.get("drugs_using", []),
                "properties": {
                    "logp": cs.logp,
                    "qed": cs.qed,
                    "sas": cs.sas,
                    "tpsa": cs.tpsa,
                    "molecular_weight": cs.molecular_weight,
                    "hbd": dc["properties"].get("hbd", "N/A"),
                    "hba": dc["properties"].get("hba", "N/A"),
                    "rotatable_bonds": dc["properties"].get(
                        "rotatable_bonds", "N/A"
                    ),
                },
                "ph_stability": dc["ph_stability"],
                "scores": {
                    "blood_stability": dc["scores"]["blood_stability"],
                    "lysosome_lability": dc["scores"]["lysosome_lability"],
                    "drug_likeness": dc["scores"]["drug_likeness"],
                    "synthetic_accessibility": dc["scores"]["synthetic"],
                    "overall": dc["scores"]["overall"],
                },
                "strengths": dc.get("strengths", []),
                "weaknesses": dc.get("weaknesses", []),
                "recommendation": cs.recommendation,
            })
        else:
            # 超出 top-3：基础数据（无详细卡片）
            candidates_data.append({
                "rank": cs.rank,
                "name": cs.name,
                "smiles": cs.smiles,
                "mechanism": cs.mechanism,
                "description": "",
                "drugs_using": [],
                "properties": {
                    "logp": cs.logp,
                    "qed": cs.qed,
                    "sas": cs.sas,
                    "tpsa": cs.tpsa,
                    "molecular_weight": cs.molecular_weight,
                    "hbd": "N/A",
                    "hba": "N/A",
                    "rotatable_bonds": "N/A",
                },
                "ph_stability": {
                    "blood_stable": cs.blood_stable,
                    "lysosome_labile": cs.lysosome_labile,
                    "summary": "",
                },
                "scores": {
                    "blood_stability": 0.0,
                    "lysosome_lability": 0.0,
                    "drug_likeness": 0.0,
                    "synthetic_accessibility": 0.0,
                    "overall": cs.overall_score,
                },
                "strengths": [],
                "weaknesses": [],
                "recommendation": cs.recommendation,
            })

    return {
        "candidates": candidates_data,
        "total_evaluated": result.total_evaluated,
        "total_filtered": result.total_filtered,
        "design_summary": result.design_summary,
        "request": {
            "target_ph": target_ph,
            "preferred_mechanism": preferred_mechanism,
            "min_qed": min_qed,
            "max_sas": max_sas,
        },
        "_report": {
            "generated_at": report.generated_at,
            "request_summary": report.request_summary,
            "total_evaluated": report.total_evaluated,
            "total_filtered": report.total_filtered,
            "candidate_count": report.candidate_count,
            "candidates": [
                {
                    "rank": cs.rank,
                    "name": cs.name,
                    "smiles": cs.smiles,
                    "mechanism": cs.mechanism,
                    "mechanism_label": cs.mechanism_label,
                    "overall_score": cs.overall_score,
                    "blood_stable": cs.blood_stable,
                    "lysosome_labile": cs.lysosome_labile,
                    "qed": cs.qed,
                    "logp": cs.logp,
                    "sas": cs.sas,
                    "tpsa": cs.tpsa,
                    "molecular_weight": cs.molecular_weight,
                    "has_toxicity_alerts": cs.has_toxicity_alerts,
                    "toxicity_count": cs.toxicity_count,
                    "recommendation": cs.recommendation,
                    "risk_flags": cs.risk_flags,
                }
                for cs in report.candidates
            ],
            "detailed_cards": report.detailed_cards,
            "comparison_text": report.comparison_text,
            "comparison_dimensions": report.comparison_dimensions,
            "has_any_toxicity": report.has_any_toxicity,
            "toxicity_summary": report.toxicity_summary,
            "warnings": report.warnings,
            "failed_scaffolds": report.failed_scaffolds,
        },
    }
