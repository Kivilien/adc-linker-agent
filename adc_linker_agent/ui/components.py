"""
Streamlit UI 组件

可复用的 UI 组件，用于渲染 Agent 的各类响应：
  - 分子性质卡片
  - pH 稳定性指示器
  - 连接子骨架卡片
  - 工具调用展开面板
"""

import json

import streamlit as st


def render_property_table(properties: dict):
    """
    渲染分子性质表。

    将 calculate_properties 返回的 dict 渲染为带颜色编码的表格。
    """
    if not properties or "error" in properties:
        st.error(f"计算失败: {properties.get('error', 'Unknown error')}")
        return

    # 性质解释
    col1, col2 = st.columns(2)

    with col1:
        st.metric("分子量 (MW)", f"{properties.get('molecular_weight', 'N/A')} Da")
        st.metric("LogP (亲脂性)", f"{properties.get('logp', 'N/A')}",
                  help="1-3 理想，>5 太亲油")
        st.metric("QED (药物相似性)", f"{properties.get('qed', 'N/A')}",
                  help=">0.5 药物样，<0.3 需优化")
        st.metric("SAS (合成难度)", f"{properties.get('sas', 'N/A')}",
                  help="<4 容易合成，>6 复杂昂贵")

    with col2:
        st.metric("TPSA (极性表面积)", f"{properties.get('tpsa', 'N/A')} Å²",
                  help="80-140 理想")
        st.metric("氢键供体 (HBD)", f"{properties.get('hbd', 'N/A')}",
                  help="<5 (Lipinski)")
        st.metric("氢键受体 (HBA)", f"{properties.get('hba', 'N/A')}",
                  help="<10 (Lipinski)")
        st.metric("可旋转键", f"{properties.get('rotatable_bonds', 'N/A')}")

    # QED 进度条
    qed = properties.get("qed", 0)
    if isinstance(qed, (int, float)):
        st.progress(
            min(qed, 1.0),
            text=f"QED Score: {qed:.3f} {'✅ 药物样' if qed >= 0.5 else '⚠️ 需优化'}",
        )


def render_ph_stability(result: dict):
    """
    渲染单个 pH 稳定性结果。

    用颜色指示器标记稳定/不稳定状态。
    """
    is_stable = result.get("is_stable", True)
    ph = result.get("target_ph", "?")
    labile = result.get("labile_groups_found", [])
    stable = result.get("stable_groups_found", [])

    if is_stable:
        st.success(f"🟢 pH {ph}: 稳定")
    else:
        st.error(f"🔴 pH {ph}: 不稳定")

    if labile:
        st.caption(f"⚠️ 不稳定基团: {', '.join(labile)}")
    if stable:
        st.caption(f"✅ 稳定基团: {', '.join(stable)}")

    recommendation = result.get("recommendation", "")
    if recommendation:
        with st.expander("详细建议"):
            st.write(recommendation)


def render_tool_call(
    name: str,
    args: dict,
    result: str | None = None,
    compact: bool = False,
):
    """
    渲染工具调用详情。

    compact=True: 简洁行模式（用于父折叠面板内批量展示）
    compact=False: 独立折叠面板（用于单个工具展示）
    """
    if compact:
        arg_preview = ", ".join(
            f"{k}={json.dumps(v, ensure_ascii=False)}"
            for k, v in list(args.items())[:3]
        )
        st.caption(f"🔹 **{name}**({arg_preview[:80]})")
    else:
        with st.expander(f"🔧 {name}", expanded=False):
            st.caption("**参数**")
            st.code(json.dumps(args, ensure_ascii=False, indent=2), language="json")
            if result:
                st.caption("**结果**")
                try:
                    result_json = json.loads(result)
                    st.json(result_json)
                except (json.JSONDecodeError, TypeError):
                    st.text(result)


def render_message_content(content: str):
    """
    智能渲染消息内容。

    尝试从内容中检测并格式化：
    - JSON 性质数据 → 表格
    - pH 结果 → 稳定性指示器
    - 普通文本 → Markdown
    """
    # 尝试检测是否是 JSON
    if content.strip().startswith("{") and content.strip().endswith("}"):
        try:
            data = json.loads(content)
            if "logp" in data and "qed" in data:
                render_property_table(data)
                return
            elif "is_stable" in data and "labile_groups_found" in data:
                render_ph_stability(data)
                return
        except (json.JSONDecodeError, TypeError):
            pass

    # 默认：Markdown 渲染
    st.markdown(content)


def render_molecule_structure(smiles: str, caption: str = "", size: tuple = (400, 250)):
    """
    渲染分子结构图。

    用 RDKit 生成 PNG 图片并在 Streamlit 中展示。
    降级方案：SVG 渲染。
    """
    from adc_linker_agent.domain.molecule import render_molecule_image, render_molecule_svg

    if not smiles:
        return

    # 方案 A: PNG
    png_bytes = render_molecule_image(smiles, size=size)
    if png_bytes:
        st.image(png_bytes, caption=caption or smiles, use_container_width=True)
        return

    # 方案 B: SVG 降级
    svg_str = render_molecule_svg(smiles, size=size)
    if svg_str:
        st.image(svg_str, caption=caption or smiles, use_container_width=True)
        return

    st.code(smiles, language=None)


def render_toxicity_alerts(alerts: list[dict], has_alerts: bool):
    """
    渲染毒性警报组件。

    有警报时显示红色警告框，列出每条警报的详情。
    无警报时显示绿色通过标记。
    """
    if has_alerts and alerts:
        with st.container(border=True):
            st.error(f"🚨 检测到 {len(alerts)} 个毒性/假阳性警报")

            pains_alerts = [a for a in alerts if a.get("filter") == "pains"]
            brenk_alerts = [a for a in alerts if a.get("filter") == "brenk"]

            if pains_alerts:
                st.caption(
                    f"⚠️ **PAINS 假阳性警报** ({len(pains_alerts)} 个): "
                    "这类化合物在筛选中频繁出现假阳性——不可作为药物开发。"
                )
                for a in pains_alerts[:5]:
                    st.caption(f"  • {a.get('description', 'Unknown')}")

            if brenk_alerts:
                st.caption(
                    f"⚠️ **Brenk 毒性警报** ({len(brenk_alerts)} 个): "
                    "含潜在毒性、不稳定或代谢反应性子结构。"
                )
                for a in brenk_alerts[:5]:
                    st.caption(f"  • {a.get('description', 'Unknown')}")
    elif not alerts:
        st.success("✅ 未检出已知毒性/假阳性警报结构")


def render_risk_flags(risk_flags: list[str]):
    """渲染风险标志列表"""
    if risk_flags:
        with st.container(border=True):
            st.warning("⚠️ 风险标志")
            for flag in risk_flags:
                st.caption(f"  • {flag}")


def render_streaming_status(
    placeholder,
    agent_name: str = "",
    agent_label: str = "",
    tool_name: str = "",
):
    """
    流式状态指示器。

    根据当前执行的 Agent 或工具更新 Streamlit placeholder。
    用于 astream_events 实时状态展示。

    Args:
        placeholder: st.empty() 占位符
        agent_name: 当前 Agent 名称（如 "linker_agent"）
        agent_label: Agent 显示标签（如 "🔗 LinkerAgent 设计连接子"）
        tool_name: 当前工具名称（如 "design_linker"）
    """
    if tool_name:
        placeholder.info(f"🔧 调用工具: **{tool_name}**")
    elif agent_label:
        placeholder.info(agent_label)
    elif agent_name:
        placeholder.info(f"🔄 {agent_name} 工作中...")


def render_sidebar():
    """渲染侧边栏配置。"""
    with st.sidebar:
        st.title("⚙️ 配置")

        from adc_linker_agent.utils.config import get_config
        config = get_config()

        mode = st.radio(
            "Agent 模式",
            options=["multi", "single"],
            format_func=lambda x: "🤖 Multi-Agent (推荐)" if x == "multi" else "🧠 Single Agent",
            help="Multi-Agent: Supervisor+3专长 / Single: ReAct循环",
        )

        st.caption(f"🔌 提供商: **{config.llm_provider}** | 模型: **{config.llm_model}**")

        st.divider()

        st.markdown("""
        ### 💡 试试这些查询

        **性质计算**:
        `计算阿司匹林的所有分子性质`

        **pH 分析**:
        `检查腙键连接子在血液和溶酶体中的稳定性`

        **连接子设计**:
        `搜索所有 pH 敏感的 ADC 连接子骨架`

        **综合任务**:
        `设计一个在 pH 5.5 裂解释放喜树碱的连接子`
        """)

        st.divider()
        st.caption("ADC Linker Agent v1.1.0 | 323 tests passing")

    return mode


def render_design_report(report):
    """
    渲染结构化设计报告。

    将 DesignReport 数据转换为科研报告格式，包括:
      - 报告标题 + 需求摘要
      - 候选对比表
      - Top-3 详细卡片（含结构图、性质仪表盘、pH 路径）
      - 对比分析
      - 毒性汇总 + 警告

    Args:
        report: domain.report.DesignReport 实例
    """
    from adc_linker_agent.utils.validators import MEDICAL_DISCLAIMER

    # ─── 报告标题 ───
    st.markdown("---")
    st.header("📊 ADC 连接子设计报告")
    st.caption(f"生成时间: {report.generated_at} | 需求: {report.request_summary}")

    # ─── 1. 设计概览 ───
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("评估候选", report.total_evaluated)
    col2.metric("过滤排除", report.total_filtered)
    col3.metric("最终候选", report.candidate_count)
    tox_label = "⚠️ 有警报" if report.has_any_toxicity else "✅ 通过"
    col4.metric("毒性筛查", tox_label)

    if not report.candidates:
        st.warning("未找到符合筛选条件的候选。建议放宽 QED 或 SAS 要求。")
        return

    st.divider()

    # ─── 2. 候选对比表 ───
    st.subheader("📋 候选对比表")

    table_data = []
    for c in report.candidates:
        blood = "✅" if c.blood_stable else "🔴"
        lyso = "✅" if c.lysosome_labile else "—"
        tox = f"🚨 {c.toxicity_count}" if c.has_toxicity_alerts else "✅"
        table_data.append({
            "排名": c.rank,
            "名称": c.name,
            "机制": c.mechanism_label,
            "综合分": f"{c.overall_score:.3f}",
            "血液": blood,
            "溶酶体": lyso,
            "QED": f"{c.qed:.3f}",
            "LogP": c.logp,
            "SAS": c.sas,
            "毒性": tox,
        })

    st.dataframe(table_data, use_container_width=True, hide_index=True)

    st.divider()

    # ─── 3. Top-3 详细卡片 ───
    st.subheader("🔍 Top-3 候选详情")

    for card in report.detailed_cards:
        _render_candidate_card(card)

    st.divider()

    # ─── 4. 对比分析 ───
    if report.comparison_dimensions:
        st.subheader("⚖️ 候选对比分析")
        for dim in report.comparison_dimensions:
            with st.expander(dim["dimension"]):
                st.write(dim["detail"])

    st.divider()

    # ─── 5. 毒性汇总 ───
    st.subheader("🛡️ 安全性评估")
    if report.has_any_toxicity:
        st.error(report.toxicity_summary)
    else:
        st.success(report.toxicity_summary)

    # ─── 6. 全局警告 ───
    if report.warnings:
        for w in report.warnings:
            st.warning(w)

    # ─── 7. 失败骨架 ───
    if report.failed_scaffolds:
        with st.expander(f"⚠️ 评估失败的骨架 ({len(report.failed_scaffolds)} 个)"):
            for f in report.failed_scaffolds:
                st.caption(f"• {f.get('name', 'Unknown')}: {f.get('error', 'Unknown error')}")

    # ─── 8. 医学免责声明 ───
    st.divider()
    st.caption(MEDICAL_DISCLAIMER)


def _render_candidate_card(card: dict):
    """渲染单个候选的详细卡片"""
    name = card["name"]
    rank = card["rank"]
    mech_label = card.get("mechanism_label", card.get("mechanism", ""))
    smiles = card["smiles"]
    recommendation = card.get("recommendation", "")

    # 卡片容器
    with st.container(border=True):
        # 标题行
        rank_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
        st.subheader(f"{rank_emoji} {name}")
        st.caption(f"**机制**: {mech_label} | **SMILES**: `{smiles}`")

        # 结构式图片
        render_molecule_structure(smiles, caption=name)

        # 分数栏
        scores = card.get("scores", {})
        score_cols = st.columns(5)
        score_cols[0].metric("血液稳定性", f"{scores.get('blood_stability', 0):.2f}")
        score_cols[1].metric("溶酶体裂解", f"{scores.get('lysosome_lability', 0):.2f}")
        score_cols[2].metric("药物相似性", f"{scores.get('drug_likeness', 0):.2f}")
        score_cols[3].metric("合成可行性", f"{scores.get('synthetic', 0):.2f}")
        score_cols[4].metric("⭐ 综合分", f"{scores.get('overall', 0):.3f}")

        # 性质仪表盘
        props = card.get("properties", {})
        prop_cols = st.columns(4)
        for i, (prop_name, prop_data) in enumerate(props.items()):
            if not isinstance(prop_data, dict):
                continue
            value = prop_data.get("value", "—")
            status = prop_data.get("status", "ok")
            ideal = prop_data.get("ideal", "")
            delta = None
            if status == "ideal":
                delta = "✅"
            elif status == "warning":
                delta = "⚠️"
            with prop_cols[i % 4]:
                st.metric(
                    label=f"{prop_name} ({ideal})" if ideal else prop_name,
                    value=value,
                    delta=delta,
                )

        # pH 路径
        ph = card.get("ph_stability", {})
        ph_col1, ph_col2 = st.columns(2)
        with ph_col1:
            if ph.get("blood_stable"):
                st.success("🩸 血液 pH 7.4: ✅ 稳定")
            else:
                st.error("🩸 血液 pH 7.4: 🔴 不稳定")
        with ph_col2:
            if ph.get("lysosome_labile"):
                st.success("🧪 溶酶体 pH 5.0: ✅ 可裂解")
            else:
                st.warning("🧪 溶酶体 pH 5.0: ⚠️ 裂解不充分")

        # 优缺点
        strengths = card.get("strengths", [])
        weaknesses = card.get("weaknesses", [])
        if strengths or weaknesses:
            sw_col1, sw_col2 = st.columns(2)
            with sw_col1:
                if strengths:
                    st.caption("**✅ 优势**")
                    for s in strengths:
                        st.caption(f"  • {s}")
            with sw_col2:
                if weaknesses:
                    st.caption("**⚠️ 不足**")
                    for w in weaknesses:
                        st.caption(f"  • {w}")

        # 毒性警报
        if card.get("has_toxicity_alerts"):
            tox_alerts = card.get("toxicity_alerts", [])
            render_toxicity_alerts(tox_alerts, True)

        # 风险标志
        risk_flags = card.get("risk_flags", [])
        render_risk_flags(risk_flags)

        # 推荐理由
        if recommendation:
            if "🚨" in recommendation:
                st.error(recommendation)
            elif "✅" in recommendation:
                st.success(recommendation)
            elif "⚠️" in recommendation:
                st.warning(recommendation)
            else:
                st.info(recommendation)

        # 临床参考
        drugs = card.get("drugs_using", [])
        if drugs:
            st.caption(f"**📚 临床参考**: {', '.join(drugs[:5])}")


def render_literature_cards(lit_data: dict):
    """
    渲染文献搜索结果卡片。

    从 shared_context.literature_data 直接渲染，不依赖 LLM 文本解析。
    这是架构 v2 的关键修复——文献结果始终可见。

    Args:
        lit_data: {"papers": [...], "queries": [...], "total_found": int}
    """
    papers = lit_data.get("papers", [])
    queries = lit_data.get("queries", [])
    total = lit_data.get("total_found", len(papers))

    if not papers:
        if queries:
            st.info(f"未找到相关文献（搜索: {'; '.join(queries)}）")
        return

    # 标题行
    query_text = "; ".join(queries) if queries else "文献搜索"
    st.markdown(f"**搜索**: {query_text}")
    st.caption(f"找到 {total} 篇相关论文")

    st.divider()

    # 每篇论文一行（简洁风格，像 Claude 的输出）
    for i, p in enumerate(papers, 1):
        title = p.get("title", "未知标题")
        authors = p.get("authors", "")
        journal = p.get("journal", "")
        year = p.get("year", "")
        doi = p.get("doi", "")
        abstract = p.get("abstract", "")

        # 构建引用行
        parts = [f"{i}."]
        if authors:
            parts.append(f"{authors}.")
        parts.append(f"*{title}*")
        if journal and year:
            parts.append(f"{journal}. {year}.")
        elif year:
            parts.append(f"({year})")

        st.markdown(" ".join(parts))

        # DOI 链接
        if doi:
            st.caption(f"https://doi.org/{doi}")

        # 摘要（截断）
        if abstract:
            with st.expander("摘要"):
                st.caption(abstract[:500])

        if i < len(papers):
            st.divider()


# ═══════════════════════════════════════════════════════════════
# 用户反馈组件
# ═══════════════════════════════════════════════════════════════


def render_feedback_row(message_index: int):
    """在助手消息下方渲染 👍/👎 反馈按钮及可展开表单。

    使用 st.session_state 跟踪已评价的消息，防止重复投票。
    差评时展开分类选择 + 自由文本输入。
    """
    import streamlit as st

    feedback_key = f"feedback_{message_index}"
    submitted_key = f"feedback_submitted_{message_index}"

    # 已提交则跳过
    if submitted_key in st.session_state and st.session_state[submitted_key]:
        return

    col1, col2, col3 = st.columns([1, 1, 6])
    with col1:
        if st.button("👍", key=f"up_{message_index}", help="回答有帮助"):
            st.session_state[feedback_key] = "up"
            st.session_state[submitted_key] = True
            st.rerun()
    with col2:
        if st.button("👎", key=f"down_{message_index}", help="回答有问题"):
            st.session_state[feedback_key] = "down"
            st.session_state[submitted_key] = False
            st.rerun()

    # 差评时展示分类 + 备注表单
    if st.session_state.get(feedback_key) == "down" and not st.session_state.get(submitted_key):
        with st.expander("💬 哪里出了问题？", expanded=True):
            category = st.selectbox(
                "问题类型",
                ["incorrect", "unclear", "slow", "other"],
                format_func=lambda x: {
                    "incorrect": "信息不准确",
                    "unclear": "表达不清晰",
                    "slow": "响应太慢",
                    "other": "其他问题",
                }.get(x, x),
                key=f"cat_{message_index}",
            )
            comment = st.text_area(
                "补充说明（可选）",
                key=f"comment_{message_index}",
                max_chars=500,
                placeholder="请描述具体问题…",
            )
            if st.button("提交反馈", key=f"submit_{message_index}"):
                _save_feedback(
                    message_index,
                    st.session_state[feedback_key],
                    category,
                    comment,
                )
                st.session_state[submitted_key] = True
                st.success("感谢反馈！")

    # 好评时展示确认
    if st.session_state.get(feedback_key) == "up" and st.session_state.get(submitted_key):
        st.caption("✓ 感谢反馈！")


def _save_feedback(
    message_index: int,
    rating: str,
    category: str | None,
    comment: str | None,
):
    """将反馈持久化到 logs/feedback.jsonl。"""
    import json
    import time
    from pathlib import Path

    try:
        import streamlit as st

        thread_id = st.session_state.get("thread_id", "unknown")
    except Exception:
        thread_id = "unknown"

    feedback_path = Path(__file__).parent.parent.parent / "logs" / "feedback.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "thread_id": thread_id,
        "message_index": message_index,
        "rating": rating,
        "category": category,
        "comment": comment,
    }
    with open(feedback_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
