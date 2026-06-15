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
from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors

from adc_linker_agent.domain.literature import LiteratureSearchEngine
from adc_linker_agent.domain.ph_simulator import PhSimulator
from adc_linker_agent.domain.properties import MolPropertyCalculator, check_toxicity_alerts
from adc_linker_agent.utils.validators import validate_smiles_input

# ─── 单例实例 ───
_calc = MolPropertyCalculator()
_sim = PhSimulator()
_literature = LiteratureSearchEngine()


# ─── 工具定义 ───


@tool
def validate_smiles(smiles: str) -> dict:
    """
    Validate a SMILES string and return basic molecular information.

    🚨 NEVER INVENT a SMILES to pass to this tool. Only validate SMILES that:
    (1) were explicitly provided by the user, OR
    (2) were returned by design_linker, search_linker_scaffolds, or calculate_properties.
    If you don't have a real SMILES from one of these sources, ASK the user.
    If valid=False, move on — do NOT retry with a modified SMILES.

    Args:
        smiles: A SMILES from user input or a tool result (never LLM-invented)

    Returns:
        dict with valid (bool), smiles (canonical), formula, molecular_weight
    """
    if not smiles or not smiles.strip():
        return {"valid": False, "smiles": smiles, "error": "Empty SMILES string"}

    # 集中输入校验（长度、恶意模式检测）
    validation_error = validate_smiles_input(smiles)
    if validation_error:
        return {"valid": False, "smiles": smiles, "error": validation_error}

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
def check_toxicity(smiles: str) -> dict:
    """
    Check for PAINS (Pan-Assay Interference Compounds) and Brenk toxicity alerts.

    PAINS alerts flag compounds that frequently show false-positive bioactivity —
    not developable as drugs. Brenk alerts flag potentially toxic, unstable, or
    metabolically reactive substructures (alkylating agents, Michael acceptors, etc.).

    🚨 CRITICAL: Call this for EVERY linker candidate before recommending it.
    A linker with PAINS or Brenk alerts is a RED FLAG — warn the user loudly.

    Args:
        smiles: A valid SMILES string

    Returns:
        dict with has_alerts, alerts (list of {description, category}),
        pains_count, brenk_count, summary
    """
    return check_toxicity_alerts(smiles)


@tool
def predict_ph_stability(smiles: str, ph: float = 7.4) -> dict:
    """
    Predict molecular stability at a specific pH value.

    Checks for pH-sensitive groups (hydrazone, acetal, ester, carbamate, etc.)
    Key pH values: 7.4=blood (must be stable), 5.0=lysosome (should cleave).

    Also detects ALL functional groups in the molecule and reports which are
    covered by the 7-rule library vs. outside it (library_coverage).
    If library_coverage < 1.0, some groups' pH behavior is UNKNOWN —
    discuss with the user.

    Args:
        smiles: A valid SMILES string
        ph: Target pH. Use 7.4 for blood stability, 5.0 for lysosomal cleavage check.

    Returns:
        dict with is_stable, labile_groups_found, recommendation, context,
        all_detected_groups, groups_in_library, groups_outside_library,
        library_coverage
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


@tool
def predict_ph_stability_all_phases(smiles: str) -> dict:
    """
    Predict stability across ALL physiological pH phases in ADC delivery.

    Simulates: blood(7.4) → tumor(6.5) → early endosome(6.0) →
    late endosome(5.5) → lysosome(5.0) + stomach(2.0).

    An IDEAL ADC linker: stable at 7.4, unstable at 5.0-5.5.

    Each phase returns: is_stable, labile_groups_found, recommendation,
    plus all_detected_groups, groups_outside_library, library_coverage.
    Check library_coverage to assess prediction reliability.

    Args:
        smiles: A valid SMILES string

    Returns:
        dict mapping each phase to stability results with coverage info
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
    weights: dict | None = None,
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
        weights: Optional custom scoring weights dict with keys
                 blood_stability, lysosome_lability, drug_likeness, synthetic.
                 Values normalized to sum=1.0. Default uses built-in weights.

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
        weights=weights,
    )


@tool
def search_literature(query: str, max_results: int = 5) -> dict:
    """
    Search scientific literature (PubMed/Europe PMC) for ADC-related papers.

    Returns REAL papers with verified titles, authors, journals, DOIs, and abstracts.
    Use this to:
    - Verify chemical/biological claims against published research
    - Find evidence for linker stability, cleavage mechanisms, payload compatibility
    - Get up-to-date references on ADC design patterns
    - Ground your recommendations in peer-reviewed literature

    Tips for best results:
    - Use English keywords (PubMed/Europe PMC index English literature)
    - Include specific terms: "carbamate linker", "pH 5.5 cleavage", "camptothecin ADC"
    - Add "review" for comprehensive overview papers

    Args:
        query: Search query in English (e.g., "carbamate linker pH stability blood ADC")
        max_results: Max papers to return (default 5, max 10)

    Returns:
        dict with 'papers' list (each with title, authors, year, journal, doi, abstract, url)
        and 'total_found' count. Papers include clickable DOI links.
    """
    try:
        papers = _literature.search(query, max_results=min(max_results, 10))

        return {
            "query": query,
            "total_found": len(papers),
            "papers": [
                {
                    "title": p.title,
                    "authors": p.authors,
                    "year": p.year,
                    "journal": p.journal,
                    "doi": p.doi,
                    "url": p.url,
                    "abstract": p.abstract[:300] if p.abstract else "",
                    "citation_count": p.citation_count,
                    "citation": p.format_citation("brief"),
                }
                for p in papers
            ],
        }
    except Exception as e:
        return {"error": str(e), "query": query, "papers": []}


@tool
def search_pubchem_linkers_tool(
    query_type: str,
    query_value: str,
    max_results: int = 20,
) -> dict:
    """
    Search PubChem for ADC linker-related compounds.

    Use this tool when:
    - Finding novel linker structures from PubChem's database
    - Searching compounds by substructure (SMILES)
    - Searching compounds by name
    - Looking up compound properties by CID

    Args:
        query_type: Search type — "substructure" (SMILES), "name", or "property" (CIDs)
        query_value: SMILES string, compound name, or comma-separated CIDs
        max_results: Max results to return (default 20)
    """
    from adc_linker_agent.mcp_tools.tool_pubchem import search_pubchem_linkers

    return search_pubchem_linkers(
        query_type=query_type,
        query_value=query_value,
        max_results=max_results,
    )


# ─── 工具列表 ───
# 这是 Agent 的"工具箱"——ChatAnthropic.bind_tools(ALL_TOOLS)

ALL_TOOLS = [
    validate_smiles,
    calculate_properties,
    check_lipinski,
    check_toxicity,
    predict_ph_stability,
    predict_ph_stability_all_phases,
    search_linker_scaffolds,
    design_linker,
    search_literature,
    search_pubchem_linkers_tool,
]
