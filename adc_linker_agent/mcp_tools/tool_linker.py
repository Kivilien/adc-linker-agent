"""
连接子骨架搜索工具 —— MCP Tool

查询已知 ADC 连接子骨架库，数据源为 data/linker_scaffolds.csv（17 个骨架）。
"""

import csv
from pathlib import Path

from adc_linker_agent.domain.properties import MolPropertyCalculator

# ─── CSV 数据加载 ───

_CSV_PATH = Path(__file__).parent.parent.parent / "data" / "linker_scaffolds.csv"


def _load_scaffolds() -> list[dict]:
    """从 CSV 加载所有连接子骨架（17 条记录）。"""
    scaffolds: list[dict] = []
    try:
        with open(_CSV_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("name"):
                    scaffolds.append(dict(row))
    except FileNotFoundError:
        # 保持向后兼容：如果 CSV 不存在用旧硬编码数据
        return _FALLBACK_SCAFFOLDS
    return scaffolds


# 保留旧数据作为降级（CSV 不可用时）
_FALLBACK_SCAFFOLDS: list[dict] = [
    {
        "name": "Val-Cit-PABC",
        "smiles": "CC(C)[C@H](N)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1",
        "mechanism": "enzymatic",
        "enzyme": "Cathepsin B",
        "trigger": "Lysosomal cathepsin B cleavage of Cit-PABC amide bond",
        "description": "Gold-standard enzymatically cleavable dipeptide linker.",
        "drugs_using": "Adcetris; Polivy; Padcev",
    },
    {
        "name": "Hydrazone linker (simple)",
        "smiles": "CC(=O)NN=Cc1ccc(O)cc1",
        "mechanism": "pH_sensitive",
        "trigger": "Acid-catalyzed hydrolysis at pH < 6.0",
        "description": "Classic acid-labile hydrazone linker.",
        "drugs_using": "Mylotarg",
    },
    {
        "name": "Disulfide linker (SPDP)",
        "smiles": "O=C(ON1C(=O)CCC1=O)CCSSC",
        "mechanism": "redox",
        "trigger": "Reduction by intracellular glutathione (GSH, 1-10 mM)",
        "description": "Reductively cleavable disulfide linker.",
        "drugs_using": "Research-stage",
    },
    {
        "name": "Non-cleavable SMCC linker",
        "smiles": "O=C1C=CC(=O)N1CCCCCC(=O)ON2C(=O)CCC2=O",
        "mechanism": "non_cleavable",
        "trigger": "Complete antibody degradation in lysosome required",
        "description": "Non-cleavable linker using SMCC.",
        "drugs_using": "Kadcyla (T-DM1)",
    },
]


def search_linker_scaffolds(
    mechanism: str | None = None,
    min_molecular_weight: float | None = None,
    max_molecular_weight: float | None = None,
) -> list[dict]:
    """
    Search known ADC linker scaffolds by mechanism and molecular weight range.

    Use this tool when:
    - The user asks "what linkers work for enzymatic cleavage?"
    - You need reference linker structures for a specific mechanism
    - You want to compare linker options before designing a new one

    Args:
        mechanism: Filter by cleavage mechanism.
                   One of: "pH_sensitive", "enzymatic", "redox", "non_cleavable"
                   If None, returns all mechanisms.
        min_molecular_weight: Minimum molecular weight in Daltons
        max_molecular_weight: Maximum molecular weight in Daltons

    Returns:
        List of matching linker scaffolds. Each scaffold includes:
        - name, smiles, mechanism, enzyme/trigger, description
        - drugs_using (list of FDA-approved or clinical ADC drugs)
        - properties: calculated LogP, QED, SAS, TPSA, MW, HBD, HBA
    """
    calc = MolPropertyCalculator()

    scaffolds = _load_scaffolds()
    results: list[dict] = []
    for scaffold in scaffolds:
        # ─── 机制筛选 ───
        if mechanism is not None and scaffold["mechanism"] != mechanism:
            continue

        # ─── 计算性质 ───
        try:
            props = calc.calculate_all(scaffold["smiles"])
        except ValueError:
            continue  # 跳过无效 SMILES（不应发生，但防御性编程）

        mw = props["molecular_weight"]

        # ─── 分子量筛选 ───
        if min_molecular_weight is not None and mw < min_molecular_weight:
            continue
        if max_molecular_weight is not None and mw > max_molecular_weight:
            continue

        # ─── CSV → 输出字段适配 ───
        trigger = (
            scaffold.get("trigger")
            or scaffold.get("trigger_detail")
            or scaffold.get("enzyme", "")
        )
        # CSV 中 drugs_using 是 | 分隔的字符串，转为列表
        drugs_raw = scaffold.get("drugs_using", "")
        if isinstance(drugs_raw, str):
            drugs_list = [d.strip() for d in drugs_raw.split("|") if d.strip()]
        elif isinstance(drugs_raw, list):
            drugs_list = drugs_raw
        else:
            drugs_list = []

        results.append({
            "name": scaffold["name"],
            "smiles": scaffold["smiles"],
            "mechanism": scaffold["mechanism"],
            "trigger": trigger,
            "description": scaffold["description"],
            "drugs_using": drugs_list,
            "properties": props,
        })

    return results
