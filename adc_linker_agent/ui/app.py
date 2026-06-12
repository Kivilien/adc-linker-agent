"""
ADC Linker Agent — Streamlit 聊天界面

启动方式:
  streamlit run adc_linker_agent/ui/app.py

功能:
  - 自然语言聊天界面
  - Multi-Agent 监督者模式（默认）
  - 分子性质卡片、pH 稳定性图、连接子骨架展示
  - 工具调用可展开面板
  - 对话历史管理

注意: 需要 ANTHROPIC_API_KEY 配置在 .env 文件中。
      如未配置，界面可以启动但 Agent 调用会返回错误提示。
"""

import json
import time
from typing import Any

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from adc_linker_agent.agent.graph import get_agent
from adc_linker_agent.ui.components import (
    render_linker_card,
    render_message_content,
    render_ph_all_phases,
    render_ph_stability,
    render_property_table,
    render_sidebar,
    render_tool_call,
)
from adc_linker_agent.utils.config import get_config

# ─── 页面配置 ───

st.set_page_config(
    page_title="ADC Linker Agent",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── 标题 ───

st.title("🧬 ADC 连接子智能设计 Agent")
st.caption(
    "Antibody-Drug Conjugate Linker Design Assistant | "
    "Multi-Agent System | LangGraph + MCP + RDKit"
)

# ─── 侧边栏配置 ───

mode, model = render_sidebar()

# ─── 初始化 session state ───

if "messages" not in st.session_state:
    st.session_state.messages = []
if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"ui_{int(time.time())}"
if "tool_history" not in st.session_state:
    st.session_state.tool_history = []

# ─── API Key 检查 ───

config = get_config()
has_api_key = bool(config.anthropic_api_key)

if not has_api_key:
    st.warning(
        "⚠️ 未配置 ANTHROPIC_API_KEY。\n\n"
        "在项目根目录创建 `.env` 文件并添加:\n"
        "```\nANTHROPIC_API_KEY=sk-ant-...\n```\n"
        "然后重启 Streamlit。\n\n"
        "界面可以浏览，但 Agent 调用需要 API Key。"
    )

# ─── 显示历史消息 ───

for msg in st.session_state.messages:
    role = msg.get("role", "user")
    content = msg.get("content", "")

    with st.chat_message(role):
        # 工具调用展开面板
        tool_calls = msg.get("tool_calls", [])
        for tc in tool_calls:
            render_tool_call(
                name=tc.get("name", "unknown"),
                args=tc.get("args", {}),
                result=tc.get("result"),
            )

        # 智能渲染内容
        if role == "assistant":
            render_message_content(content)
        else:
            st.markdown(content)


# ─── 聊天输入 ───

if prompt := st.chat_input("输入你的 ADC 连接子相关查询..."):
    # 添加用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 调用 Agent
    with st.chat_message("assistant"):
        if not has_api_key:
            st.error(
                "❌ 无法调用 Agent：未配置 API Key。\n\n"
                "请在 `.env` 文件中设置 `ANTHROPIC_API_KEY`。"
            )
            st.session_state.messages.append({
                "role": "assistant",
                "content": "[错误] 未配置 API Key",
                "tool_calls": [],
            })
        else:
            try:
                with st.spinner("Agent 思考中..."):
                    graph, graph_config = get_agent(
                        model_name=model,
                        thread_id=st.session_state.thread_id,
                        mode=mode,  # type: ignore[arg-type]
                    )

                    state = {"messages": [HumanMessage(content=prompt)]}

                    start_time = time.perf_counter()
                    result = graph.invoke(state, graph_config)
                    elapsed = (time.perf_counter() - start_time) * 1000

                # ─── 处理结果 ───
                response_messages = result.get("messages", [])
                tool_calls_collected: list[dict[str, Any]] = []
                assistant_texts: list[str] = []

                for msg in response_messages:
                    msg_type = getattr(msg, "type", "unknown")

                    # 跳过 system 和 user 消息
                    if msg_type in ("system", "human"):
                        continue

                    # 提取 tool_calls
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            tc_info = {
                                "name": tc.get("name", "unknown"),
                                "args": tc.get("args", {}),
                            }
                            tool_calls_collected.append(tc_info)

                            # 查找对应的 ToolMessage
                            tc_id = tc.get("id", "")
                            for m in response_messages:
                                if (
                                    isinstance(m, ToolMessage)
                                    and getattr(m, "tool_call_id", "") == tc_id
                                ):
                                    tc_info["result"] = str(m.content)
                                    break

                    # 收集 assistant 文本
                    if msg_type == "ai" and hasattr(msg, "content"):
                        content = str(msg.content)
                        if content:
                            assistant_texts.append(content)

                # 渲染工具调用
                for tc in tool_calls_collected:
                    render_tool_call(
                        name=tc["name"],
                        args=tc["args"],
                        result=tc.get("result"),
                    )

                # 渲染内容
                full_response = "\n\n".join(assistant_texts) if assistant_texts else ""
                if full_response:
                    render_message_content(full_response)
                    st.caption(f"⏱️ {elapsed:.0f}ms | 🔧 {len(tool_calls_collected)} tools called")
                else:
                    st.info("Agent 已完成处理。")
                    st.caption(f"⏱️ {elapsed:.0f}ms | 🔧 {len(tool_calls_collected)} tools called")

                # 保存到历史
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": full_response,
                    "tool_calls": tool_calls_collected,
                })

            except Exception as e:
                error_msg = str(e)
                st.error(f"❌ Agent 调用失败: {error_msg}")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"[错误] {error_msg}",
                    "tool_calls": [],
                })

# ─── 底部操作栏 ───

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("🔄 新对话", help="清除对话历史，开始新会话"):
        st.session_state.messages = []
        st.session_state.thread_id = f"ui_{int(time.time())}"
        st.session_state.tool_history = []
        st.rerun()
with col2:
    if st.button("📋 复制对话", help="复制全部对话到剪贴板"):
        text = "\n\n".join(
            f"{'🧑 用户' if m['role'] == 'user' else '🤖 Agent'}:\n{m['content']}"
            for m in st.session_state.messages
        )
        st.code(text, language=None)
with col3:
    st.caption(f"Thread: `{st.session_state.thread_id[:12]}...`")


# ─── 启动说明（如未配置） ───

if not st.session_state.messages and not has_api_key:
    st.divider()
    st.info("""
    ### 🚀 快速开始

    1. 在项目根目录创建 `.env` 文件
    2. 添加 `ANTHROPIC_API_KEY=sk-ant-...`
    3. 重启 Streamlit：`streamlit run adc_linker_agent/ui/app.py`
    4. 在聊天框输入查询！
    """)
