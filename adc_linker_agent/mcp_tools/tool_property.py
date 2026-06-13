"""
分子性质计算工具 —— MCP Tools

将 MolPropertyCalculator 的 8 个描述符封装为 LLM 可调用的工具。
每个工具返回结构化 dict，方便 Agent 在思考链中使用。

设计原则:
    - 工具函数只返回 dict（JSON 可序列化）
    - 错误不抛异常，而是包含在返回值的 error 字段中
    - 高内聚：两个工具共享同一个计算器实例
"""

from adc_linker_agent.domain.properties import (
    MolPropertyCalculator,
    check_toxicity_alerts,
)

_calc = MolPropertyCalculator()


def calculate_properties(smiles: str) -> dict:
    """
    Calculate all key molecular descriptors for a given SMILES.

    Computes 8 properties useful for drug design and ADC linker evaluation:
    - logp: Oil/water partition coefficient (ideal 1-3 for ADC linkers)
    - qed: Drug-likeness score 0-1 (>0.5 = drug-like)
    - sas: Synthetic accessibility 1-10 (<4 = easy to synthesize)
    - tpsa: Polar surface area in Å² (80-140 ideal for membrane permeability)
    - molecular_weight: Molecular weight in Da
    - hbd: Hydrogen bond donors
    - hba: Hydrogen bond acceptors
    - rotatable_bonds: Number of rotatable bonds

    Args:
        smiles: A valid SMILES string (validate with validate_smiles first)

    Returns:
        dict with all 8 properties rounded to reasonable precision
    """
    try:
        return _calc.calculate_all(smiles)
    except ValueError as e:
        return {"error": str(e), "smiles": smiles}


def check_lipinski(smiles: str) -> dict:
    """
    Check Lipinski's Rule of Five for oral drug-likeness.

    Lipinski's rules (Pfizer, 1997):
    - Molecular weight < 500 Da
    - LogP < 5
    - Hydrogen bond donors < 5
    - Hydrogen bond acceptors < 10
    - Violating ≤1 rule = likely orally bioavailable

    Note: ADC linkers are injected, not oral, so Lipinski is a guideline
    not a hard requirement. But it helps flag problematic molecules.

    Args:
        smiles: A valid SMILES string

    Returns:
        dict with keys: molecular_weight, logp, hbd, hba, violations,
        violation_details (list of strings), is_oral_drug_like (bool)
    """
    return _calc.check_lipinski(smiles)


def check_toxicity(smiles: str) -> dict:
    """
    Check for PAINS and Brenk toxicity alerts in a molecule.

    PAINS (Pan-Assay Interference Compounds) flags compounds that frequently
    show false-positive bioactivity — not developable as drugs. Brenk alerts
    flag potentially toxic, unstable, or metabolically reactive substructures
    (alkylating agents, Michael acceptors, etc.).

    CRITICAL: Call this for EVERY linker candidate before recommending it.

    Args:
        smiles: A valid SMILES string

    Returns:
        dict with has_alerts (bool), alerts (list of {description, category}),
        pains_count, brenk_count, summary
    """
    return check_toxicity_alerts(smiles)
