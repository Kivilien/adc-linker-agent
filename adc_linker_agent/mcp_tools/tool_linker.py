"""
连接子骨架搜索工具 —— MCP Tool

查询已知 ADC 连接子骨架库，数据源通过 LinkerDatabase 统一管理。
"""

from adc_linker_agent.domain.database import LinkerDatabase
from adc_linker_agent.domain.properties import MolPropertyCalculator

# ─── 数据库单例 ───

_db: LinkerDatabase | None = None


def _get_db() -> LinkerDatabase:
    """获取 LinkerDatabase 单例（延迟初始化）。"""
    global _db
    if _db is None:
        _db = LinkerDatabase()
    return _db


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
    db = _get_db()

    scaffolds = db.search(
        mechanism=mechanism,
        mw_min=min_molecular_weight,
        mw_max=max_molecular_weight,
    )

    results: list[dict] = []
    for scaffold in scaffolds:
        # ─── 计算性质（优先查缓存）──
        cached = db.get_cached_properties(scaffold["smiles"])
        if cached:
            props = {
                "smiles": scaffold["smiles"],
                "logp": cached["logp"],
                "qed": cached["qed"],
                "sas": cached["sas"],
                "tpsa": cached["tpsa"],
                "molecular_weight": cached["molecular_weight"],
                "hbd": cached["hbd"],
                "hba": cached["hba"],
                "rotatable_bonds": cached["rotatable_bonds"],
            }
        else:
            try:
                props = calc.calculate_all(scaffold["smiles"])
            except ValueError:
                continue

        # ─── 输出字段适配 ───
        trigger = scaffold.get("trigger_detail") or scaffold.get("enzyme", "")
        drugs_list = scaffold.get("drugs_using", [])
        if isinstance(drugs_list, str):
            drugs_list = [d.strip() for d in drugs_list.split("|") if d.strip()]

        results.append(
            {
                "name": scaffold["name"],
                "smiles": scaffold["smiles"],
                "mechanism": scaffold["mechanism"],
                "trigger": trigger,
                "description": scaffold["description"],
                "drugs_using": drugs_list,
                "properties": props,
            }
        )

    return results
