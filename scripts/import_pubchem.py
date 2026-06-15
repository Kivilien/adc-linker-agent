#!/usr/bin/env python3
"""
PubChem 批量导入脚本。

从 PubChem PUG REST API 搜索 ADC 连接子相关化合物，验证后导入连接子骨架库。

搜索策略:
  1. 子结构搜索 — 已知 ADC linker 关键子结构
  2. 相似性搜索 — 以现有骨架为 query
  3. 关键词搜索 — ADC 相关术语

API: PubChem PUG REST (免费，无需 API key)
  https://pubchem.ncbi.nlm.nih.gov/rest/pug/

用法:
  uv run python scripts/import_pubchem.py
  uv run python scripts/import_pubchem.py --max-per-search 50 --dry-run
"""

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ─── 搜索 query 定义 ───

# 子结构 SMILES — ADC 连接子的关键化学片段
SUBSTRUCTURE_QUERIES = [
    # 马来酰亚胺（抗体偶联）
    ("maleimide", "O=C1C=CC(=O)N1", "antibody_conjugation"),
    # PABC 自毁间隔基
    ("PABC", "NCc1ccc(O)cc1", "self_immolative"),
    # 腙键（pH 敏感）
    ("hydrazone", "CC(=O)NN=C", "pH_sensitive"),
    # 缩醛（pH 敏感）
    ("acetal", "CCOC(C)OCC", "pH_sensitive"),
    # 二硫键（氧化还原可裂解）
    ("disulfide", "CCSSC", "redox"),
    # Val-Cit 二肽骨架
    ("Val-Cit_core", "CC(C)[C@H](N)C(=O)N[C@@H](CCCNC(N)=O)C(=O)", "enzymatic"),
    # 碳酸酯（pH 敏感）
    ("carbonate", "CC(C)OC(=O)O", "pH_sensitive"),
    # 酮缩醇
    ("ketal", "CC(C)OC(C)(C)OC(C)C", "pH_sensitive"),
    # SMCC 连接基
    ("SMCC", "O=C1C=CC(=O)N1CCCCCC(=O)", "non_cleavable"),
    # PEG 链
    ("PEG3", "OCCOCCOCCO", "spacer"),
]

# 精确化合物名称搜索（PUG REST name 端点仅支持单一化合物名）
COMPOUND_NAME_QUERIES = [
    # 已上市 ADC 药物
    ("brentuximab_vedotin", "brentuximab vedotin"),
    ("ado_trastuzumab_emtansine", "ado-trastuzumab emtansine"),
    ("polatuzumab_vedotin", "polatuzumab vedotin"),
    ("enfortumab_vedotin", "enfortumab vedotin"),
    ("sacituzumab_govitecan", "sacituzumab govitecan"),
    # ADC 载荷
    ("MMAE", "monomethyl auristatin E"),
    ("MMAF", "monomethyl auristatin F"),
    ("SN38", "SN-38"),
    ("DM1", "DM1 maytansinoid"),
    ("DXd", "DXd"),
    # 马来酰亚胺衍生物
    ("maleimide", "maleimide"),
    ("SMCC", "SMCC"),
    ("succinimidyl_carbonate", "succinimidyl 4-(N-maleimidomethyl)cyclohexane-1-carboxylate"),
    # 已知连接子
    ("val_cit_dipeptide", "valyl-citrulline"),
    ("PABC", "para-aminobenzyl alcohol"),
    ("SPDP", "SPDP"),
]

# 补充子结构搜索（更多变体）
EXTRA_SUBSTRUCTURE_QUERIES = [
    # 肽 linker
    ("Val-Ala", "CC(C)[C@H](N)C(=O)N[C@H](C)C(=O)", "enzymatic"),
    ("Gly-Gly-Phe-Gly", "NCC(=O)NCC(=O)N[C@@H](Cc1ccccc1)C(=O)NCC(=O)", "enzymatic"),
    # 葡萄糖醛酸
    ("glucuronide", "OC1OC(C(=O)O)C(O)C(O)C1O", "enzymatic"),
    # 焦磷酸酯
    ("pyrophosphate", "O=P(O)(O)OP(=O)(O)O", "pH_sensitive"),
    # 磷酸酯
    ("phosphate_ester", "O=P(O)(O)OC", "pH_sensitive"),
    # 亚胺
    ("imine_linker", "CC(C)=NC", "pH_sensitive"),
    # 硅醚
    ("silyl_ether_linker", "C[Si](C)(C)OC", "pH_sensitive"),
    # 硝基芳烃
    ("nitrobenzyl", "O=[N+]([O-])c1ccccc1", "redox"),
    # 偶氮
    ("azo_linker", "N=Nc1ccccc1", "redox"),
    # 马来酰亚胺-己酸变体
    ("maleimide_caproic", "O=C1C=CC(=O)N1CCCCCC(=O)O", "non_cleavable"),
]


# ─── PubChem API 辅助函数 ───

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
REQUEST_DELAY = 0.3  # 请求间隔（秒），遵守 PubChem 使用政策


def _pubchem_request(url: str, timeout: int = 30) -> dict[str, Any] | None:
    """发送 PubChem PUG REST 请求，返回 JSON 或 None。"""
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "ADC-Linker-Agent/1.0 (research tool)")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # 无结果
        print(f"  HTTP {e.code}: {url[:80]}...")
        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None


def search_substructure(smiles: str, max_cids: int = 100) -> list[int]:
    """子结构搜索，返回 CID 列表。"""
    url = (
        f"{PUBCHEM_BASE}/compound/fastsubstructure/smiles/"
        f"{urllib.request.quote(smiles)}/cids/JSON?MaxRecords={max_cids}"
    )
    time.sleep(REQUEST_DELAY)
    data = _pubchem_request(url)
    if data and "IdentifierList" in data:
        return data["IdentifierList"].get("CID", [])
    return []


def search_keyword(keyword: str, max_cids: int = 100) -> list[int]:
    """精确化合物名称搜索，返回 CID 列表。"""
    url = (
        f"{PUBCHEM_BASE}/compound/name/"
        f"{urllib.request.quote(keyword)}/cids/JSON?MaxRecords={max_cids}"
    )
    time.sleep(REQUEST_DELAY)
    data = _pubchem_request(url)
    if data and "IdentifierList" in data:
        return data["IdentifierList"].get("CID", [])
    return []


def get_compound_properties(cids: list[int]) -> list[dict[str, Any]]:
    """批量获取化合物的 SMILES 和性质。"""
    results: list[dict[str, Any]] = []
    batch_size = 100

    for i in range(0, len(cids), batch_size):
        batch = cids[i : i + batch_size]
        cid_str = ",".join(str(c) for c in batch)
        url = (
            f"{PUBCHEM_BASE}/compound/cid/{cid_str}/property/"
            f"ConnectivitySMILES,MolecularWeight,MolecularFormula,IUPACName/JSON"
        )
        time.sleep(REQUEST_DELAY)
        data = _pubchem_request(url)
        if data and "PropertyTable" in data:
            for props in data["PropertyTable"].get("Properties", []):
                results.append(
                    {
                        "cid": props.get("CID"),
                        "smiles": props.get("ConnectivitySMILES", ""),
                        "mw": props.get("MolecularWeight", 0),
                        "formula": props.get("MolecularFormula", ""),
                        "iupac": props.get("IUPACName", ""),
                    }
                )
    return results


# ─── 验证 ───


def validate_for_adc(smiles: str, db=None) -> tuple[bool, str]:
    """
    验证化合物是否适合作为 ADC 连接子。

    Returns:
        (valid, reason)
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors

        from adc_linker_agent.domain.properties import check_toxicity_alerts
    except ImportError:
        return False, "RDKit import failed"

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return False, "Invalid SMILES"

    n_atoms = mol.GetNumAtoms()
    if n_atoms < 8:
        return False, f"Too few atoms ({n_atoms})"
    if n_atoms > 200:
        return False, f"Too many atoms ({n_atoms})"

    mw = Descriptors.MolWt(mol)
    if mw < 80:
        return False, f"MW too low ({mw:.0f})"
    if mw > 2000:
        return False, f"MW too high ({mw:.0f})"

    # Relax PAINS filter for import: only exclude PAINS, not Brenk
    from adc_linker_agent.domain.properties import check_toxicity_alerts

    tox = check_toxicity_alerts(smiles)
    pains = [a for a in tox.get("alerts", []) if a.get("category") == "pains"]
    if pains:
        return False, f"PAINS alert: {pains[0]['description']}"

    # Database dedup
    if db is not None and smiles in db:
        return False, "Already in database"

    return True, "OK"


# ─── 分类 ───


def classify_mechanism(smiles: str) -> str:
    """根据子结构匹配推断裂解机制。"""
    try:
        from rdkit import Chem

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return "unknown"

        # 二硫键 → redox
        disulfide = Chem.MolFromSmarts("[#16X2]-[#16X2]")
        if disulfide and mol.HasSubstructMatch(disulfide):
            return "redox"

        # 腙/亚胺 → pH_sensitive
        hydrazone = Chem.MolFromSmarts("[NX2]=[CX3]")
        if hydrazone and mol.HasSubstructMatch(hydrazone):
            return "pH_sensitive"

        # 缩醛/酮缩醇 → pH_sensitive
        acetal = Chem.MolFromSmarts("[OX2]([CX4])([CX4])[OX2]")
        if acetal and mol.HasSubstructMatch(acetal):
            return "pH_sensitive"

        # 酯/碳酸酯 → pH_sensitive (if not enzyme substrate)
        ester = Chem.MolFromSmarts("[CX3](=O)[OX2][CX4]")
        if ester and mol.HasSubstructMatch(ester):
            return "pH_sensitive"

        # 酰胺-酰胺（dipeptide pattern）→ enzymatic
        dipeptide = Chem.MolFromSmarts("[NX3][CX3](=O)[NX3][CX3](=O)")
        if dipeptide and mol.HasSubstructMatch(dipeptide):
            return "enzymatic"

        # 马来酰亚胺 → non_cleavable (unless paired with trigger)
        maleimide = Chem.MolFromSmarts("O=C1C=CC(=O)N1")
        if maleimide and mol.HasSubstructMatch(maleimide):
            return "non_cleavable"

        # 硝基芳烃 → redox (hypoxia)
        nitro = Chem.MolFromSmarts("[N+](=O)[O-]")
        if nitro and mol.HasSubstructMatch(nitro):
            return "redox"

        return "unknown"
    except Exception:
        return "unknown"


# ─── 主流程 ───


def main():
    parser = argparse.ArgumentParser(description="Import ADC linkers from PubChem")
    parser.add_argument(
        "--max-per-search", type=int, default=100, help="Max CIDs per search query (default: 100)"
    )
    parser.add_argument(
        "--max-total", type=int, default=500, help="Max total compounds to fetch (default: 500)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate but don't save")
    args = parser.parse_args()

    print("=" * 60)
    print("PubChem ADC Linker Import")
    print("=" * 60)

    # 初始化数据库
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    from adc_linker_agent.domain.database import LinkerDatabase

    db = LinkerDatabase()
    print(f"Current DB: {len(db)} scaffolds\n")

    # ─── Phase 1: 收集 CID ───
    all_cids: set[int] = set()

    print("Phase 1: Searching PubChem...")
    print("-" * 40)

    # 1a. 子结构搜索
    print(f"\n[Substructure search] {len(SUBSTRUCTURE_QUERIES)} queries")
    for name, smi, _mechanism in SUBSTRUCTURE_QUERIES:
        cids = search_substructure(smi, max_cids=args.max_per_search)
        print(f"  {name}: {len(cids)} CIDs")
        all_cids.update(cids)

    # 1b. 化合物名称搜索
    print(f"\n[Compound name search] {len(COMPOUND_NAME_QUERIES)} queries")
    for name, keyword in COMPOUND_NAME_QUERIES:
        cids = search_keyword(keyword, max_cids=args.max_per_search)
        print(f"  {name}: {len(cids)} CIDs")
        all_cids.update(cids)

    # 1c. 补充子结构搜索
    print(f"\n[Extra substructure search] {len(EXTRA_SUBSTRUCTURE_QUERIES)} queries")
    for name, smi, _mechanism in EXTRA_SUBSTRUCTURE_QUERIES:
        cids = search_substructure(smi, max_cids=args.max_per_search)
        print(f"  {name}: {len(cids)} CIDs")
        all_cids.update(cids)

    print(f"\nTotal unique CIDs: {len(all_cids)}")

    # ─── Phase 2: 获取性质 ───
    cid_list = list(all_cids)[: args.max_total]
    print(f"\nPhase 2: Fetching properties for {len(cid_list)} compounds...")
    compounds = get_compound_properties(cid_list)
    print(f"Got properties for {len(compounds)} compounds")

    # ─── Phase 3: 验证 + 导入 ───
    print("\nPhase 3: Validating and importing...")
    imported = 0
    skipped = 0
    reasons: dict[str, int] = {}

    for comp in compounds:
        smi = comp.get("smiles", "")
        cid = comp.get("cid", "")
        if not smi:
            skipped += 1
            reasons["no_smiles"] = reasons.get("no_smiles", 0) + 1
            continue

        valid, reason = validate_for_adc(smi, db=db)
        if not valid:
            skipped += 1
            reasons[reason] = reasons.get(reason, 0) + 1
            continue

        mechanism = classify_mechanism(smi)
        if mechanism == "unknown":
            skipped += 1
            reasons["unknown_mechanism"] = reasons.get("unknown_mechanism", 0) + 1
            continue

        iupac = comp.get("iupac", "")
        name = iupac[:50] if iupac else f"PubChem_CID{cid}"

        if not args.dry_run:
            db.add_scaffold(
                name=f"pubchem_{name[:45]}",
                smiles=smi,
                mechanism=mechanism,
                description=f"PubChem CID {cid}: {comp.get('formula', '')}",
                source="pubchem",
                source_id=f"CID{cid}",
            )
        imported += 1

        if imported % 20 == 0:
            print(f"  Imported {imported}...")

    print("\nResults:")
    print(f"  Imported: {imported}")
    print(f"  Skipped: {skipped}")
    print(f"  Skip reasons: {reasons}")

    if not args.dry_run:
        db.save()
        print(f"\nDatabase saved: {len(db)} total scaffolds")
        print(db.stats())

    print("\nDone.")


if __name__ == "__main__":
    import sys

    main()
