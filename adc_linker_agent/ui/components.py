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


def render_ph_all_phases(results: dict):
    """
    渲染全生理阶段 pH 稳定性结果。

    用列布局展示 ADC 递送路径中每阶段的稳定性。
    """
    phase_order = [
        ("blood", "🩸 血液 pH 7.4"),
        ("tumor_microenvironment", "🦠 肿瘤微环境 pH 6.5"),
        ("early_endosome", "📦 早期内吞体 pH 6.0"),
        ("late_endosome", "📦 晚期内吞体 pH 5.5"),
        ("lysosome", "🧪 溶酶体 pH 5.0"),
        ("stomach", "🍽️ 胃 pH 2.0"),
    ]

    cols = st.columns(3)
    for i, (phase_key, phase_label) in enumerate(phase_order):
        if phase_key not in results:
            continue
        r = results[phase_key]
        is_stable = r.get("is_stable", True)
        with cols[i % 3]:
            if is_stable:
                st.success(f"**{phase_label}**\n\n✅ 稳定")
            else:
                st.error(f"**{phase_label}**\n\n🔴 不稳定")

    # 理想模式提示
    blood_ok = results.get("blood", {}).get("is_stable", False)
    lysosome_unstable = not results.get("lysosome", {}).get("is_stable", True)
    if blood_ok and lysosome_unstable:
        st.info("✅ 理想 ADC 连接子模式：血液稳定 + 溶酶体裂解")
    elif not blood_ok:
        st.error("⚠️ 警告：连接子在血液中不稳定，会提前释放毒素！")
    elif not lysosome_unstable:
        st.warning("⚠️ 注意：连接子在溶酶体中不裂解，可能无效！")


def render_linker_card(linker: dict):
    """
    渲染单个连接子骨架卡片。
    """
    name = linker.get("name", "Unknown")
    mechanism = linker.get("mechanism", "?")
    description = linker.get("description", "")
    drugs = linker.get("drugs_using", [])
    props = linker.get("properties", {})

    mechanism_emoji = {
        "pH_sensitive": "🔴",
        "enzymatic": "🟢",
        "redox": "🟡",
        "non_cleavable": "⚫",
    }

    with st.container(border=True):
        emoji = mechanism_emoji.get(mechanism, "❓")
        st.subheader(f"{emoji} {name}")

        # 机制标签
        st.caption(f"**机制**: {mechanism} | **触发**: {linker.get('trigger', 'N/A')}")

        # 临床参考
        if drugs:
            st.caption(f"**临床参考**: {', '.join(drugs[:3])}")

        with st.expander("详情"):
            st.write(description)
            st.caption(f"SMILES: `{linker.get('smiles', 'N/A')}`")

        # 关键性质
        if props:
            mw = props.get("molecular_weight", "?")
            logp = props.get("logp", "?")
            qed = props.get("qed", "?")
            st.caption(f"MW: {mw} Da | LogP: {logp} | QED: {qed}")


def render_tool_call(name: str, args: dict, result: str | None = None):
    """
    在可展开面板中渲染工具调用详情。
    """
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
        st.caption("ADC Linker Agent v0.1.0 | 187 tests passing")

    return mode
