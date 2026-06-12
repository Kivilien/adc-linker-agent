"""
SMILES 校验工具 —— MCP Tool

这是 LLM 调用化学工具之前的"安检门"。
如果 SMILES 字符串本身是无效的，后续计算全部无用。
"""

from rdkit import Chem
from rdkit.Chem import Descriptors


def validate_smiles(smiles: str) -> dict:
    """
    Validate a SMILES string and return basic molecular information.

    This is the FIRST tool to call when the user provides a SMILES string.
    If valid=False, skip all subsequent calculations and ask the user
    to provide a correct SMILES.

    Args:
        smiles: A SMILES string representing a molecule.
                Examples:
                - "CC(=O)Oc1ccccc1C(=O)O" (aspirin)
                - "c1ccccc1" (benzene)
                - "CC(=O)NN=C(C)c1ccccc1" (hydrazone linker)

    Returns:
        dict with keys:
        - valid (bool): Whether the SMILES is chemically valid
        - smiles (str): Canonical SMILES (standardized form)
        - formula (str): Molecular formula (e.g., "C9H8O4")
        - molecular_weight (float): Molecular weight in Daltons
    """
    # 空字符串或纯空白不是有效 SMILES
    if not smiles or not smiles.strip():
        return {"valid": False, "smiles": smiles, "error": "Empty SMILES string"}

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"valid": False, "smiles": smiles, "error": "Invalid SMILES string"}

    from rdkit.Chem.rdMolDescriptors import CalcMolFormula

    return {
        "valid": True,
        "smiles": Chem.MolToSmiles(mol, canonical=True),
        "formula": CalcMolFormula(mol),
        "molecular_weight": round(Descriptors.MolWt(mol), 1),
    }
