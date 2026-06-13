"""
pH 稳定性预测工具 —— MCP Tools

将 PhSimulator 的规则引擎封装为 LLM 可调用的工具。
这是 ADC 连接子设计中最关键的工具——连接子必须在血液中稳定、
在溶酶体中裂解。

MCP 工具返回的 dict 包含人类可读的推荐和建议，
Agent 可以直接引用到对话回复中。
"""

from adc_linker_agent.domain.ph_simulator import PhSimulator

_sim = PhSimulator()


def predict_ph_stability(smiles: str, ph: float = 7.4) -> dict:
    """
    Predict the stability of a molecule at a specific pH value.

    Checks the molecule against 7 known pH-sensitive functional groups:
    hydrazone, acetal, ketal, carboxylic ester, carbamate, imine, silyl ether.

    Key pH reference points for ADC design:
    - pH 7.4 = blood (linker MUST be stable here)
    - pH 6.5 = tumor microenvironment
    - pH 5.5 = late endosome
    - pH 5.0 = lysosome (linker SHOULD cleave here)

    Args:
        smiles: A valid SMILES string for the linker or linker-payload
        ph: Target pH value (default 7.4). Use 5.0 for lysosomal cleavage check.

    Returns:
        dict with keys:
        - smiles, target_ph, is_stable
        - labile_groups_found: groups that WILL cleave at this pH
        - stable_groups_found: groups that remain stable
        - recommendation: human-readable advice
        - context: physiological relevance of this pH
    """
    try:
        result = _sim.predict(smiles, ph)
    except ValueError as e:
        return {"error": str(e), "smiles": smiles, "target_ph": ph}

    return {
        "smiles": result.smiles,
        "target_ph": result.target_ph,
        "is_stable": result.is_stable,
        "labile_groups_found": result.labile_groups_found,
        "stable_groups_found": result.stable_groups_found,
        "recommendation": result.recommendation,
        "context": result.context,
        "all_detected_groups": result.all_detected_groups,
        "groups_in_library": result.groups_in_library,
        "groups_outside_library": result.groups_outside_library,
        "library_coverage": result.library_coverage,
    }


def predict_ph_stability_all_phases(smiles: str) -> dict:
    """
    Predict stability across ALL physiological pH phases in the ADC delivery path.

    Simulates the complete journey of an ADC after intravenous injection:
    blood (7.4) → tumor microenvironment (6.5) → early endosome (6.0) →
    late endosome (5.5) → lysosome (5.0).

    An IDEAL ADC linker should show:
    - "stable" at pH 7.4 and 6.5
    - "stable" or "partial" at pH 6.0
    - "unstable" at pH 5.5 and 5.0

    Args:
        smiles: A valid SMILES string for the linker

    Returns:
        dict mapping phase names to {target_ph, is_stable, labile_groups_found, recommendation}
    """
    try:
        results = _sim.predict_physiological_phases(smiles)
    except ValueError as e:
        return {"error": str(e), "smiles": smiles}

    return {
        phase: {
            "target_ph": r.target_ph,
            "is_stable": r.is_stable,
            "labile_groups_found": r.labile_groups_found,
            "recommendation": r.recommendation,
            "all_detected_groups": r.all_detected_groups,
            "groups_in_library": r.groups_in_library,
            "groups_outside_library": r.groups_outside_library,
            "library_coverage": r.library_coverage,
        }
        for phase, r in results.items()
    }
