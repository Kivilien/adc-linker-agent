"""
连接子骨架搜索工具 —— MCP Tool

查询已知 ADC 连接子骨架库。当前（Week 3）为硬编码参考数据，
Week 7 将替换为可搜索的 CSV 数据库 + 模板化生成器。

设计原则:
    - 返回完整的连接子信息（名称、SMILES、裂解机制、临床参考）
    - 支持按机制、分子量范围筛选
    - 自动附加计算好的分子性质，Agent 无需额外调用 calculate_properties
"""

from typing import Optional

from adc_linker_agent.domain.properties import MolPropertyCalculator

# ─── 已知 ADC 连接子骨架库 ───
# 来源：已上市 ADC 药物 + 文献综述
# 这些数据在 Week 7 将迁移到 data/linker_scaffolds.csv

KNOWN_LINKER_SCAFFOLDS: list[dict] = [
    {
        "name": "Val-Cit-PABC",
        "smiles": "CC(C)[C@H](N)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1",
        "mechanism": "enzymatic",
        "enzyme": "Cathepsin B",
        "trigger": "Lysosomal cathepsin B cleavage of Cit-PABC amide bond",
        "description": (
            "Gold-standard enzymatically cleavable dipeptide linker. "
            "Val-Cit sequence is specifically recognized and cleaved by cathepsin B "
            "in lysosomes. PABC acts as a self-immolative spacer that releases the "
            "payload after enzymatic cleavage."
        ),
        "drugs_using": ["Adcetris (brentuximab vedotin)", "Polivy (polatuzumab vedotin)", "Padcev (enfortumab vedotin)"],
    },
    {
        "name": "Hydrazone linker (simple)",
        "smiles": "CC(=O)NN=Cc1ccc(O)cc1",
        "mechanism": "pH_sensitive",
        "trigger": "Acid-catalyzed hydrolysis at pH < 6.0",
        "description": (
            "Classic acid-labile hydrazone linker. The C=N bond is stable at "
            "neutral pH but hydrolyzes rapidly in acidic environments. "
            "Used in first-generation ADCs but has plasma stability issues "
            "(slow hydrolysis at pH 7.4 over days)."
        ),
        "drugs_using": ["Mylotarg (gemtuzumab ozogamicin) — first-gen"],
    },
    {
        "name": "Mc-Val-Cit-PABC (maleimide)",
        "smiles": "O=C1C=CC(=O)N1CCCCCC(=O)N[C@@H](C(C)C)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1",
        "mechanism": "enzymatic",
        "enzyme": "Cathepsin B",
        "trigger": "Maleimide conjugation to antibody cysteine + cathepsin B cleavage",
        "description": (
            "Full ADC linker-payload connector. Maleimide (Mc) attaches to "
            "antibody cysteine thiols via Michael addition. Val-Cit-PABC provides "
            "enzymatic cleavage and self-immolative payload release."
        ),
        "drugs_using": ["Adcetris", "Polivy", "Padcev", "multiple clinical-stage ADCs"],
    },
    {
        "name": "Disulfide linker (SPDP)",
        "smiles": "O=C(ON1C(=O)CCC1=O)CCSSC",
        "mechanism": "redox",
        "trigger": "Reduction by intracellular glutathione (GSH, 1-10 mM)",
        "description": (
            "Reductively cleavable disulfide linker. Stable in bloodstream "
            "(low GSH ~5 μM) but reduced in cytoplasm (high GSH 1-10 mM). "
            "Steric hindrance near disulfide can tune cleavage rate."
        ),
        "drugs_using": ["Research-stage", "Preclinical candidates"],
    },
    {
        "name": "Non-cleavable SMCC linker",
        "smiles": "O=C1C=CC(=O)N1CCCCCC(=O)ON2C(=O)CCC2=O",
        "mechanism": "non_cleavable",
        "trigger": "Complete antibody degradation in lysosome required",
        "description": (
            "Non-cleavable linker using SMCC (succinimidyl-4-(N-maleimidomethyl)"
            "cyclohexane-1-carboxylate). Requires complete proteolytic degradation "
            "of the antibody to release the payload with attached linker and "
            "amino acid residue. Often retains activity despite modification."
        ),
        "drugs_using": ["Kadcyla (ado-trastuzumab emtansine, T-DM1)"],
    },
    {
        "name": "Carbonate ester linker",
        "smiles": "CC(C)OC(=O)Oc1ccc(CC(C)C)cc1",
        "mechanism": "pH_sensitive",
        "trigger": "Hydrolysis at endosomal/lysosomal pH (4.5-6.0)",
        "description": (
            "pH-sensitive carbonate linker. Hydrolyzes via acid-catalyzed or "
            "esterase-mediated mechanism. More stable than hydrazone at neutral pH "
            "but still cleavable in acidic endosomes/lysosomes."
        ),
        "drugs_using": ["Research-stage", "Preclinical evaluation"],
    },
    {
        "name": "Acetal linker",
        "smiles": "CCOC(C)OCC",
        "mechanism": "pH_sensitive",
        "trigger": "Rapid acid-catalyzed hydrolysis at pH < 5.5",
        "description": (
            "Acid-labile acetal linker. Very stable at pH 7.4 (t1/2 > 24h) "
            "but hydrolyzes within minutes at pH 5.0. Suitable for linkers "
            "requiring fast lysosomal payload release."
        ),
        "drugs_using": ["Preclinical candidates"],
    },
    {
        "name": "TMALIN-like dual-cleavage linker",
        "smiles": "CC(C)(C)OC(=O)NCCN(C)C(=O)OCc1ccc(CC(C)C)cc1",
        "mechanism": "pH_sensitive",
        "trigger": "Tumor microenvironment (pH 6.5) + lysosome (pH 5.0) dual cleavage",
        "description": (
            "Inspired by Yili Bio's TMALIN® platform. Features dual cleavage: "
            "first at tumor microenvironment pH (~6.5) to expose membrane-permeable "
            "payload, then complete release in lysosome (pH 5.0). "
            "Supports DAR=8 with high homogeneity."
        ),
        "drugs_using": ["Yili Bio pipeline candidates (参考宜联生物 TMALIN® 平台)"],
    },
]


def search_linker_scaffolds(
    mechanism: Optional[str] = None,
    min_molecular_weight: Optional[float] = None,
    max_molecular_weight: Optional[float] = None,
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

    results: list[dict] = []
    for scaffold in KNOWN_LINKER_SCAFFOLDS:
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

        results.append({
            "name": scaffold["name"],
            "smiles": scaffold["smiles"],
            "mechanism": scaffold["mechanism"],
            "trigger": scaffold.get("trigger", scaffold.get("enzyme", "")),
            "description": scaffold["description"],
            "drugs_using": scaffold.get("drugs_using", []),
            "properties": props,
        })

    return results
