#!/usr/bin/env python3
"""
文献 SMILES 提取脚本。

从 Europe PMC 搜索 ADC 连接子相关文献，提取 SMILES 结构，
验证后导入连接子骨架库。

用法:
  uv run python scripts/import_literature.py
  uv run python scripts/import_literature.py --max-results 100 --dry-run
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ─── SMILES 正则 ───

# 匹配 SMILES 字符串的宽松模式
# SMILES: 字母、数字、括号、=、#、@、/、\、.、-、+、[] 等
SMILES_PATTERN = re.compile(
    r"(?:^|\s|[\(\)\[\]\s,.;:])"
    r"("
    r"[A-Za-z0-9\[\]\(\)=#@/\\\.\-\+]+"
    r"(?:\[[A-Za-z0-9@\-,;:\+\*\\/]+\]"
    r"[A-Za-z0-9\[\]\(\)=#@/\\\.\-\+]*)*"
    r")"
    r"(?:\s|[\(\)\[\]\s,.;:]|$)"
)

# 已知的非 SMILES 模式（过滤假阳性）
NOT_SMILES = re.compile(
    r"^("
    r"\d+$|"  # 纯数字
    r"[A-Z][a-z]+$|"  # 单词
    r"http|"  # URL
    r"doi|"  # DOI
    r"Fig|"  # 图表编号
    r"Table|"  # 表格编号
    r")",
    re.IGNORECASE,
)

# 最小有效 SMILES 长度
MIN_SMILES_LEN = 6
MAX_SMILES_LEN = 2000


# ─── Europe PMC API ───

EPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
REQUEST_DELAY = 0.5  # Europe PMC 要求每秒最多 2 次请求


def search_epmc(query: str, max_results: int = 50) -> list[dict[str, Any]]:
    """搜索 Europe PMC 文献。"""
    url = (
        f"{EPMC_BASE}/search?"
        f"query={urllib.request.quote(query)}"
        f"&resultType=core"
        f"&pageSize={max_results}"
        f"&format=json"
    )
    time.sleep(REQUEST_DELAY)
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "ADC-Linker-Agent/1.0 (research)")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get("resultList", {}).get("result", [])
    except Exception as e:
        print(f"  EPMC error: {e}")
        return []


def get_full_text(pmcid: str) -> str | None:
    """获取 PMC 全文（XML 格式）。"""
    url = f"{EPMC_BASE}/search?query=PMCID:{pmcid}&resultType=core&format=json"
    time.sleep(REQUEST_DELAY)
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "ADC-Linker-Agent/1.0 (research)")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            results = data.get("resultList", {}).get("result", [])
            if results:
                return results[0].get("fullTextUrl", {}).get("value")
    except Exception:
        pass
    return None


# ─── SMILES 提取 ───


def extract_smiles_from_text(text: str) -> list[str]:
    """从文本中提取 SMILES 字符串。"""
    if not text:
        return []

    candidates = SMILES_PATTERN.findall(text)
    results: list[str] = []

    for c in candidates:
        c = c.strip()
        if len(c) < MIN_SMILES_LEN or len(c) > MAX_SMILES_LEN:
            continue
        if NOT_SMILES.match(c):
            continue
        results.append(c)

    return results


def extract_smiles_from_abstract(abstract: str) -> list[str]:
    """从摘要中提取 SMILES，只保留 RDKit 验证通过的。"""
    candidates = extract_smiles_from_text(abstract)
    valid: list[str] = []

    try:
        from rdkit import Chem

        for smi in candidates:
            mol = Chem.MolFromSmiles(smi)
            if mol is not None:
                # 原子数范围
                n = mol.GetNumAtoms()
                if 8 <= n <= 200:
                    valid.append(Chem.MolToSmiles(mol))
    except ImportError:
        pass

    return valid


# ─── 验证 ───


def validate_linker_smiles(smiles: str, db) -> tuple[bool, str]:
    """验证是否为有效 ADC 连接子。"""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors

        from adc_linker_agent.domain.properties import check_toxicity_alerts
    except ImportError:
        return False, "RDKit missing"

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return False, "Invalid SMILES"

    n = mol.GetNumAtoms()
    if n < 8:
        return False, f"Too few atoms ({n})"
    if n > 200:
        return False, f"Too many atoms ({n})"

    mw = Descriptors.MolWt(mol)
    if mw < 80 or mw > 2000:
        return False, f"MW out of range ({mw:.0f})"

    # 检查 PAINS（只有假阳性警报才算严重）
    tox = check_toxicity_alerts(smiles)
    if any(a.get("category") == "pains" for a in tox.get("alerts", [])):
        return False, "PAINS alert"

    # 去重
    if smiles in db:
        return False, "Duplicate"

    return True, "OK"


# ─── 分类 ───


def classify_from_text(text: str) -> str:
    """从文本内容推断裂解机制。"""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["cathepsin", "dipeptide", "val-cit", "enzyme", "protease"]):
        return "enzymatic"
    if any(kw in text_lower for kw in ["disulfide", "glutathione", "gsh", "redox", "reduction"]):
        return "redox"
    if any(
        kw in text_lower
        for kw in [
            "hydrazone",
            "acetal",
            "ketal",
            "ph-sensitive",
            "acid-labile",
            "ph labile",
            "carbonate",
            "ester",
            "imine",
        ]
    ):
        return "pH_sensitive"
    if any(kw in text_lower for kw in ["non-cleavable", "smcc", "maleimide", "peg", "spacer"]):
        return "non_cleavable"
    return "unknown"


# ─── 查询定义 ───

SEARCH_QUERIES = [
    # ADC 连接子综述
    "ADC linker cleavable design review",
    "antibody drug conjugate linker chemistry",
    "cathepsin B cleavable linker dipeptide",
    "acid labile linker hydrazone ADC",
    "disulfide linker glutathione responsive ADC",
    "self-immolative spacer PABC ADC",
    "maleimide conjugation ADC linker",
    "beta-glucuronidase cleavable linker",
    # 特定 linker 类型
    "Val-Cit-PABC linker synthesis",
    "SMCC linker antibody conjugation",
    "SPDP disulfide linker",
    "PEG linker ADC pharmacokinetics",
    # 新型 linker
    "click chemistry ADC linker",
    "bioorthogonal ADC linker conjugation",
    "pH-responsive linker tumor microenvironment",
    "hypoxia-activated linker ADC",
    "pyrophosphatase cleavable linker",
    "sulfatase cleavable linker ADC",
]


# ─── 主流程 ───


def main():
    parser = argparse.ArgumentParser(description="Extract ADC linker SMILES from literature")
    parser.add_argument(
        "--max-results", type=int, default=50, help="Max papers per query (default: 50)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Search and extract but don't save")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    from adc_linker_agent.domain.database import LinkerDatabase

    db = LinkerDatabase()

    print("=" * 60)
    print("Literature SMILES Extraction")
    print("=" * 60)
    print(f"Current DB: {len(db)} scaffolds\n")

    all_smiles: dict[str, dict] = {}  # smiles -> metadata

    # Phase 1: 搜索文献
    print("Phase 1: Searching Europe PMC...")
    print("-" * 40)

    for query in SEARCH_QUERIES:
        print(f"\nQuery: {query[:60]}...")
        papers = search_epmc(query, max_results=args.max_results)
        print(f"  Found {len(papers)} papers")

        for paper in papers:
            title = paper.get("title", "")
            abstract = paper.get("abstractText", "")
            source = paper.get("source", "")
            doi = paper.get("doi", "")
            pmcid = paper.get("pmcid", "")

            text_to_scan = f"{title}. {abstract}"
            smiles_list = extract_smiles_from_abstract(text_to_scan)

            for smi in smiles_list:
                if smi not in all_smiles:
                    all_smiles[smi] = {
                        "doi": doi,
                        "pmcid": pmcid,
                        "title": title[:100],
                        "source": source,
                        "context": abstract[:200] if abstract else "",
                    }

    print(f"\nTotal unique SMILES extracted: {len(all_smiles)}")

    # Phase 2: 验证 + 导入
    print("\nPhase 2: Validating and importing...")
    imported = 0
    skipped = 0
    reasons: dict[str, int] = {}

    for smi, meta in all_smiles.items():
        valid, reason = validate_linker_smiles(smi, db=db)
        if not valid:
            skipped += 1
            reasons[reason] = reasons.get(reason, 0) + 1
            continue

        mechanism = classify_from_text(meta["context"])
        if mechanism == "unknown":
            # 尝试从 SMILES 自身推断
            from scripts.import_pubchem import classify_mechanism

            mechanism = classify_mechanism(smi)

        doi = meta.get("doi", "")
        title = meta.get("title", "Unknown")

        if not args.dry_run:
            db.add_scaffold(
                name=f"lit_{title[:45]}",
                smiles=smi,
                mechanism=mechanism,
                description=f"Literature: {title[:80]}",
                source="literature",
                source_id=f"DOI:{doi}" if doi else f"PMCID:{meta.get('pmcid', '')}",
            )
        imported += 1

        if imported % 10 == 0:
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
    main()
