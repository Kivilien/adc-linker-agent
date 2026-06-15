"""
PubChem 搜索工具 —— MCP Tool

为 LLM agent 提供按需 PubChem 搜索能力。
支持子结构搜索和化合物性质查询。

注册到:
  - mcp_tools/server.py (MCP 端点)
  - agent/tools.py (LangChain 工具)
"""

import json
import time
import urllib.error
import urllib.request
from typing import Any

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
REQUEST_DELAY = 0.3


def _pubchem_request(url: str, timeout: int = 20) -> dict[str, Any] | None:
    """PubChem PUG REST 请求。"""
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "ADC-Linker-Agent/1.0 (research tool)")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        return {"error": f"HTTP {e.code}", "url": url[:100]}
    except Exception as e:
        return {"error": str(e)}


def search_pubchem_linkers(
    query_type: str,
    query_value: str,
    max_results: int = 20,
) -> dict:
    """
    搜索 PubChem 中的 ADC 连接子相关化合物。

    Use this tool when:
    - The user asks "find similar linkers in PubChem"
    - You need to discover novel linker structures
    - You want to check if a compound exists in PubChem

    Args:
        query_type: 搜索类型。可选:
            - "substructure": 子结构搜索 (query_value = SMILES)
            - "name": 化合物名称搜索 (query_value = 化合物名)
            - "property": 按 CID 获取性质 (query_value = "CID1,CID2,...")
        query_value: 搜索值 (SMILES / 名称 / CID 列表)
        max_results: 最大结果数 (默认 20)

    Returns:
        dict:
        - cids: 匹配的 PubChem CID 列表
        - compounds: 化合物性质列表 (SMILES, MW, IUPAC)
        - total_found: 匹配的化合物总数
    """
    cids: list[int] = []
    total_found = 0

    # ─── Step 1: Search for CIDs ───
    if query_type == "substructure":
        url = (
            f"{PUBCHEM_BASE}/compound/fastsubstructure/smiles/"
            f"{urllib.request.quote(query_value)}/cids/JSON"
            f"?MaxRecords={max_results}"
        )
        time.sleep(REQUEST_DELAY)
        data = _pubchem_request(url)
        if data and "IdentifierList" in data:
            cids = data["IdentifierList"].get("CID", [])
            total_found = len(cids)

    elif query_type == "name":
        url = (
            f"{PUBCHEM_BASE}/compound/name/"
            f"{urllib.request.quote(query_value)}/cids/JSON"
            f"?MaxRecords={max_results}"
        )
        time.sleep(REQUEST_DELAY)
        data = _pubchem_request(url)
        if data and "IdentifierList" in data:
            cids = data["IdentifierList"].get("CID", [])
            total_found = len(cids)

    elif query_type == "property":
        # query_value 应为逗号分隔的 CID
        cids = [int(c.strip()) for c in query_value.split(",") if c.strip().isdigit()]
        total_found = len(cids)

    else:
        return {"error": f"Unknown query_type: {query_type}. Use substructure, name, or property."}

    if not cids:
        return {"cids": [], "compounds": [], "total_found": 0}

    # ─── Step 2: Fetch properties ───
    cids = cids[:max_results]  # 截断
    cid_str = ",".join(str(c) for c in cids)
    url = (
        f"{PUBCHEM_BASE}/compound/cid/{cid_str}/property/"
        f"ConnectivitySMILES,MolecularWeight,MolecularFormula,IUPACName/JSON"
    )
    time.sleep(REQUEST_DELAY)
    data = _pubchem_request(url)

    compounds: list[dict] = []
    if data and "PropertyTable" in data:
        for props in data["PropertyTable"].get("Properties", []):
            smi = props.get("ConnectivitySMILES", "")
            if smi:
                compounds.append(
                    {
                        "cid": props.get("CID"),
                        "smiles": smi,
                        "molecular_weight": float(props.get("MolecularWeight", 0)),
                        "formula": props.get("MolecularFormula", ""),
                        "iupac_name": props.get("IUPACName", ""),
                    }
                )

    return {
        "cids": cids,
        "compounds": compounds,
        "total_found": total_found,
    }


def get_pubchem_properties(cids: list[int]) -> list[dict]:
    """
    按 CID 列表批量获取化合物性质。

    Args:
        cids: PubChem CID 列表 (最多 100)

    Returns:
        化合物性质列表 [{"cid", "smiles", "molecular_weight", "formula", "iupac_name"}, ...]
    """
    if len(cids) > 100:
        cids = cids[:100]

    cid_str = ",".join(str(c) for c in cids)
    url = (
        f"{PUBCHEM_BASE}/compound/cid/{cid_str}/property/"
        f"ConnectivitySMILES,MolecularWeight,MolecularFormula,IUPACName/JSON"
    )
    time.sleep(REQUEST_DELAY)
    data = _pubchem_request(url)

    results: list[dict] = []
    if data and "PropertyTable" in data:
        for props in data["PropertyTable"].get("Properties", []):
            smi = props.get("ConnectivitySMILES", "")
            if smi:
                results.append(
                    {
                        "cid": props.get("CID"),
                        "smiles": smi,
                        "molecular_weight": float(props.get("MolecularWeight", 0)),
                        "formula": props.get("MolecularFormula", ""),
                        "iupac_name": props.get("IUPACName", ""),
                    }
                )
    return results
