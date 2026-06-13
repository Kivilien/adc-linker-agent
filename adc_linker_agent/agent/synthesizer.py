"""
Synthesizer: 从 shared_context 生成用户可读输出

提供两个综合路径:
  1. LLM 综合 (build_synthesis_prompt): 构建结构化 prompt 供 Synthesizer LLM 使用
  2. 模板降级 (template_synthesize): 零 LLM 依赖，始终可用

这是安全网: 即使 LLM 调用失败，模板降级始终从 shared_context 中的数据
生成有用的输出。特别确保文献结果始终对用户可见（修复"文献搜索结果不显示"bug）。
"""


def build_synthesis_prompt(ctx: dict) -> str:
    """
    从 shared_context 构建结构化 prompt，供 Synthesizer LLM 使用。

    Args:
        ctx: shared_context 字典（包含所有专长 Agent 的计算结果）

    Returns:
        结构化文本，包含所有可用的计算结果和文献证据
    """
    parts = []

    # 执行摘要
    exec_log = ctx.get("execution_log", [])
    if exec_log:
        parts.append("Execution summary: " + " -> ".join(exec_log))

    # 性质数据
    prop = ctx.get("property_data")
    if prop:
        parts.append("\n## Property Data (computed by tools)")
        parts.append(f"SMILES: {prop.get('smiles', 'N/A')}")
        if prop.get("properties"):
            for k, v in prop["properties"].items():
                parts.append(f"  {k}: {v}")
        if prop.get("lipinski"):
            parts.append(f"  Lipinski: {prop['lipinski']}")
        if prop.get("toxicity"):
            parts.append(f"  Toxicity: {prop['toxicity']}")

    # pH 数据
    ph = ctx.get("ph_data")
    if ph:
        parts.append("\n## pH Stability Data (computed by PhSimulator)")
        for phase, result in ph.items():
            if isinstance(result, dict):
                status = "stable" if result.get("is_stable") else "UNSTABLE"
                parts.append(
                    f"  {phase} (pH {result.get('target_ph', '?')}): {status}"
                )
                if result.get("labile_groups_found"):
                    parts.append(
                        f"    labile groups: {result['labile_groups_found']}"
                    )

    # 设计报告
    report = ctx.get("design_report")
    if report:
        parts.append("\n## Design Report")
        parts.append(f"Candidates: {report.get('candidate_count', 0)}")
        for c in report.get("candidates", [])[:5]:
            parts.append(
                f"  #{c.get('rank', '?')} {c.get('name', '?')}: "
                f"score={c.get('overall_score', '?')}"
            )
        if report.get("comparison_text"):
            parts.append(f"Comparison: {report['comparison_text']}")

    # 文献数据
    lit = ctx.get("literature_data")
    if lit:
        parts.append("\n## Literature Evidence (from Europe PMC)")
        parts.append(f"Queries: {lit.get('queries', [])}")
        parts.append(f"Total found: {lit.get('total_found', 0)}")
        for p in lit.get("papers", []):
            parts.append(f"  - {p.get('title', '?')}")
            parts.append(f"    Authors: {p.get('authors', '?')}")
            parts.append(
                f"    Journal: {p.get('journal', '?')} ({p.get('year', '?')})"
            )
            parts.append(f"    DOI: {p.get('doi', '?')}")
            if p.get("abstract"):
                parts.append(f"    Abstract: {p['abstract'][:200]}...")

    # 错误
    errors = ctx.get("errors", [])
    if errors:
        parts.append("\n## Errors Encountered")
        for e in errors:
            parts.append(f"  [{e.get('agent', '?')}] {e.get('error', '?')}")

    parts.append(
        "\nSynthesize the above data into a clear answer for the user."
    )
    return "\n".join(parts)


def template_synthesize(ctx: dict) -> str:
    """
    免 LLM 的模板化综合输出。

    这是安全网: 始终从 shared_context 中的数据生成有用的输出，
    即使 LLM 调用失败。特别确保文献结果始终对用户可见。

    Args:
        ctx: shared_context 字典

    Returns:
        格式化的输出字符串（中文）
    """
    parts = []

    # 文献结果（始终优先展示——这是关键修复）
    lit = ctx.get("literature_data")
    if lit and lit.get("papers"):
        papers = lit["papers"]
        queries = lit.get("queries", [])
        parts.append(f"搜索: {'; '.join(queries)}")
        parts.append(f"找到 {len(papers)} 篇相关论文:\n")
        for i, p in enumerate(papers, 1):
            parts.append(f"{i}. {p.get('title', '未知标题')}")
            if p.get("authors"):
                parts.append(f"   {p['authors']}")
            if p.get("journal") and p.get("year"):
                parts.append(f"   *{p['journal']}* ({p.get('year')})")
            if p.get("doi"):
                parts.append(f"   https://doi.org/{p['doi']}")
            if p.get("abstract"):
                parts.append(f"   {p['abstract'][:200]}")
            parts.append("")

    # 性质结果
    prop = ctx.get("property_data")
    if prop:
        parts.append("分子性质")
        parts.append(f"SMILES: {prop.get('smiles', 'N/A')}")
        if prop.get("properties"):
            for key, val in prop["properties"].items():
                parts.append(f"  {key}: {val}")
        if prop.get("toxicity"):
            t = prop["toxicity"]
            if t.get("has_alerts"):
                parts.append(f"  毒性警报: {t.get('summary', '')}")
            else:
                parts.append("  毒性检查: 通过")

    # pH 结果
    ph = ctx.get("ph_data")
    if ph:
        parts.append("\npH 稳定性分析")
        for phase, result in ph.items():
            if isinstance(result, dict):
                stable = "稳定" if result.get("is_stable") else "不稳定"
                parts.append(
                    f"  {phase} (pH {result.get('target_ph', '?')}): {stable}"
                )

    # 设计报告
    report = ctx.get("design_report")
    if report:
        parts.append(
            f"\n连接子设计结果 ({report.get('candidate_count', 0)} 个候选)"
        )
        for c in report.get("candidates", [])[:3]:
            parts.append(
                f"  {c.get('rank', '?')}. {c.get('name', '?')} "
                f"— 综合评分: {c.get('overall_score', '?')}"
            )

    # 错误
    errors = ctx.get("errors", [])
    if errors:
        parts.append("\n处理中遇到的问题:")
        for e in errors:
            parts.append(f"  [{e.get('agent', '?')}] {e.get('error', '?')}")

    if not parts:
        return "无法生成分析结果。请检查输入或稍后重试。"

    from adc_linker_agent.utils.validators import MEDICAL_DISCLAIMER

    parts.append("")
    parts.append(MEDICAL_DISCLAIMER)
    return "\n".join(parts)
