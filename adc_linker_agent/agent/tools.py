"""
LangChain 工具封装

将 Week 2 的领域计算器和 Week 3 的 MCP 工具函数封装为
LangChain 兼容的 Tool 对象，供 LangGraph Agent 调用。

为什么同时有 MCP tools 和 LangChain tools？
  - MCP tools (mcp_tools/): 通过 stdio/HTTP 暴露，供外部 LLM 调用
  - LangChain tools (agent/tools.py): 在 LangGraph 图内直接调用，不走网络
  两者底层是同一套领域函数（MolPropertyCalculator, PhSimulator）。

当 Agent 使用 bind_tools() 绑定这些工具后:
  1. LLM 看到工具的名称和描述（来自 docstring）
  2. LLM 决定调用工具时，生成 tool_call 请求
  3. ToolNode 执行 tool_call，调用对应的 Python 函数
  4. 返回结果追加到对话历史
"""

from langchain_core.tools import tool

from adc_linker_agent.domain.ph_simulator import PhSimulator
from adc_linker_agent.domain.properties import MolPropertyCalculator

# ─── 单例实例 ───
_calc = MolPropertyCalculator()
_sim = PhSimulator()


# ─── 工具定义 ───


@tool
def validate_smiles(smiles: str) -> dict:
    """
    Validate a SMILES string and return basic molecular information.

    ALWAYS call this FIRST when the user provides a SMILES string.
    If valid=False, ask the user to provide a correct SMILES.

    Args:
        smiles: A SMILES string like "CC(=O)Oc1ccccc1C(=O)O" (aspirin)
                or "c1ccccc1" (benzene).

    Returns:
        dict with valid (bool), smiles (canonical), formula, molecular_weight
    """
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors

    if not smiles or not smiles.strip():
        return {"valid": False, "smiles": smiles, "error": "Empty SMILES string"}

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"valid": False, "smiles": smiles, "error": "Invalid SMILES string"}

    return {
        "valid": True,
        "smiles": Chem.MolToSmiles(mol, canonical=True),
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "molecular_weight": round(Descriptors.MolWt(mol), 1),
    }


@tool
def calculate_properties(smiles: str) -> dict:
    """
    Calculate 8 key molecular descriptors for a SMILES string.

    Computes LogP (oil/water), QED (drug-likeness 0-1),
    SAS (synthetic difficulty 1-10), TPSA (polar surface area),
    molecular weight, hydrogen bond donors/acceptors, and rotatable bonds.

    Use this tool to evaluate drug-likeness and ADC linker suitability.
    Call validate_smiles first to ensure the SMILES is valid.

    Args:
        smiles: A valid SMILES string

    Returns:
        dict with logp, qed, sas, tpsa, molecular_weight, hbd, hba, rotatable_bonds
    """
    try:
        return _calc.calculate_all(smiles)
    except ValueError as e:
        return {"error": str(e), "smiles": smiles}


@tool
def check_lipinski(smiles: str) -> dict:
    """
    Check Lipinski's Rule of Five for oral drug-likeness.

    Rules: MW<500, LogP<5, HBD<5, HBA<10.
    Violating ≤1 rule = likely orally bioavailable.
    Note: ADC linkers are injected, not oral, so this is a guideline.

    Args:
        smiles: A valid SMILES string

    Returns:
        dict with violations count, details, and is_oral_drug_like boolean
    """
    return _calc.check_lipinski(smiles)


@tool
def predict_ph_stability(smiles: str, ph: float = 7.4) -> dict:
    """
    Predict molecular stability at a specific pH value.

    Checks for pH-sensitive groups (hydrazone, acetal, ester, carbamate, etc.)
    Key pH values: 7.4=blood (must be stable), 5.0=lysosome (should cleave).

    Args:
        smiles: A valid SMILES string
        ph: Target pH. Use 7.4 for blood stability, 5.0 for lysosomal cleavage check.

    Returns:
        dict with is_stable, labile_groups_found, recommendation, context
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
    }


@tool
def predict_ph_stability_all_phases(smiles: str) -> dict:
    """
    Predict stability across ALL physiological pH phases in ADC delivery.

    Simulates: blood(7.4) → tumor(6.5) → early endosome(6.0) →
    late endosome(5.5) → lysosome(5.0) + stomach(2.0).

    An IDEAL ADC linker: stable at 7.4, unstable at 5.0-5.5.

    Args:
        smiles: A valid SMILES string

    Returns:
        dict mapping each phase to stability results
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
        }
        for phase, r in results.items()
    }


@tool
def search_linker_scaffolds(
    mechanism: str | None = None,
    min_molecular_weight: float | None = None,
    max_molecular_weight: float | None = None,
) -> list[dict]:
    """
    Search known ADC linker scaffolds by mechanism and molecular weight.

    Mechanisms: pH_sensitive, enzymatic, redox, non_cleavable.
    Includes Val-Cit-PABC, hydrazone, disulfide, SMCC, TMALIN-like, etc.

    Args:
        mechanism: Filter by mechanism type (or None for all)
        min_molecular_weight: Minimum molecular weight filter
        max_molecular_weight: Maximum molecular weight filter

    Returns:
        List of linker scaffolds with name, SMILES, mechanism, properties
    """
    from adc_linker_agent.mcp_tools.tool_linker import search_linker_scaffolds as _search

    return _search(mechanism, min_molecular_weight, max_molecular_weight)


@tool
def design_linker(
    target_ph: float = 5.0,
    preferred_mechanism: str | None = None,
    min_qed: float = 0.2,
    max_sas: float = 7.0,
    require_blood_stable: bool = True,
    max_results: int = 3,
) -> dict:
    """
    Design ADC linker candidates based on target requirements.

    Runs the full design optimization loop: filter scaffolds → evaluate
    properties → assess pH stability → multi-criteria scoring → rank →
    return top candidates. THIS is the main design tool.

    Use this when the user wants to DESIGN a new linker (not just search).
    For simple scaffold lookup, use search_linker_scaffolds instead.

    Args:
        target_ph: Desired cleavage pH (5.0=lysosome, 5.5=late endosome)
        preferred_mechanism: "pH_sensitive", "enzymatic", "redox", or None for all
        min_qed: Minimum drug-likeness (0-1, default 0.2)
        max_sas: Maximum synthetic difficulty (1-10, default 7.0)
        require_blood_stable: Require stability at pH 7.4 (default True)
        max_results: Max candidates to return (default 3)

    Returns:
        dict with ranked candidates, scores, strengths/weaknesses, and design summary
    """
    from adc_linker_agent.mcp_tools.tool_design import design_linker as _design

    return _design(
        target_ph=target_ph,
        preferred_mechanism=preferred_mechanism,
        min_qed=min_qed,
        max_sas=max_sas,
        require_blood_stable=require_blood_stable,
        max_results=max_results,
    )


# ─── 工具列表 ───
# 这是 Agent 的"工具箱"——ChatAnthropic.bind_tools(ALL_TOOLS)

ALL_TOOLS = [
    validate_smiles,
    calculate_properties,
    check_lipinski,
    predict_ph_stability,
    predict_ph_stability_all_phases,
    search_linker_scaffolds,
    design_linker,
]
