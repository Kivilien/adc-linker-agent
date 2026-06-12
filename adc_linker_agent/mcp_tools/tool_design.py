"""
连接子设计工具 —— MCP Tool

封装 LinkerDesigner 的设计优化循环为 LLM 可调用的工具。
这是 ADC Agent 的"核心武器"——从需求到候选连接子的全流程。

Week 7 新增，与 tool_linker.py（简单搜索）互补：
  - search_linker_scaffolds: 查询骨架库（Week 3）
  - design_linker: 设计优化循环（Week 7）← 本文件
"""

from typing import Optional

from adc_linker_agent.domain.linker_designer import (
    LinkerDesigner,
    LinkerDesignRequest,
    DesignResult,
)


# ─── 单例（避免重复加载 CSV） ───
_designer: Optional[LinkerDesigner] = None


def _get_designer() -> LinkerDesigner:
    global _designer
    if _designer is None:
        _designer = LinkerDesigner()
    return _designer


def design_linker(
    target_ph: float = 5.0,
    preferred_mechanism: Optional[str] = None,
    min_qed: float = 0.2,
    max_sas: float = 7.0,
    require_blood_stable: bool = True,
    max_results: int = 3,
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

    Returns:
        dict with keys:
        - candidates: list of ranked linker candidates with full evaluation
        - total_evaluated: number of scaffolds considered
        - total_filtered: number filtered out
        - design_summary: human-readable summary
    """
    designer = _get_designer()

    request = LinkerDesignRequest(
        target_ph=target_ph,
        preferred_mechanism=preferred_mechanism,
        min_qed=min_qed,
        max_sas=max_sas,
        require_blood_stable=require_blood_stable,
        max_results=max_results,
    )

    result: DesignResult = designer.design(request)

    # 序列化候选结果
    candidates_data = []
    for c in result.candidates:
        candidates_data.append({
            "rank": len(candidates_data) + 1,
            "name": c.name,
            "smiles": c.smiles,
            "mechanism": c.mechanism,
            "description": c.description,
            "drugs_using": c.drugs_using,
            "properties": {
                "logp": c.logp,
                "qed": c.qed,
                "sas": c.sas,
                "tpsa": c.tpsa,
                "molecular_weight": c.molecular_weight,
                "hbd": c.hbd,
                "hba": c.hba,
                "rotatable_bonds": c.rotatable_bonds,
            },
            "ph_stability": {
                "blood_stable": c.blood_stable,
                "lysosome_labile": c.lysosome_labile,
                "summary": c.ph_stability_summary,
            },
            "scores": {
                "blood_stability": round(c.score_blood_stability, 3),
                "lysosome_lability": round(c.score_lysosome_lability, 3),
                "drug_likeness": round(c.score_drug_likeness, 3),
                "synthetic_accessibility": round(c.score_synthetic, 3),
                "overall": round(c.overall_score, 3),
            },
            "strengths": c.strengths,
            "weaknesses": c.weaknesses,
            "recommendation": c.recommendation,
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
    }
