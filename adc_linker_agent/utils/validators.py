"""
输入验证工具

集中的输入校验函数，防止恶意或异常输入导致安全问题。
"""

MAX_SMILES_LENGTH = 2048
MAX_QUERY_LENGTH = 10000


def validate_smiles_input(smiles: str) -> str | None:
    """
    校验 SMILES 输入。

    Returns:
        错误信息字符串，或 None（通过）
    """
    if not smiles or not smiles.strip():
        return "SMILES 字符串为空"

    if len(smiles) > MAX_SMILES_LENGTH:
        return f"SMILES 字符串过长（{len(smiles)} > {MAX_SMILES_LENGTH} 字符上限）"

    # 检测潜在的无限循环/恶意模式（极长重复单元）
    if len(smiles) > 200:
        # 检查是否有连续重复的模式
        half = len(smiles) // 2
        if smiles[:half] == smiles[half:2 * half]:
            return "检测到重复模式，可能是恶意输入"

    return None


def validate_query_input(query: str) -> str | None:
    """
    校验查询输入。

    Returns:
        错误信息字符串，或 None（通过）
    """
    if not query or not query.strip():
        return "查询为空"

    if len(query) > MAX_QUERY_LENGTH:
        return f"查询过长（{len(query)} > {MAX_QUERY_LENGTH} 字符上限）"

    return None


# 医学免责声明（用于所有输出）
MEDICAL_DISCLAIMER = """
---
⚠️ **医学免责声明**: 本平台为 AI 辅助研究工具，所有分子性质计算和设计建议
基于计算化学规则引擎（RDKit, PhSimulator）和科学文献检索（Europe PMC）。
**这些结果仅供研究参考，不可用于临床诊断或治疗决策。**
在设计化合物合成、进行生物实验或做出任何安全相关决策前，
必须由合格的专业药物化学家和药理学家独立审核验证。
""".strip()
