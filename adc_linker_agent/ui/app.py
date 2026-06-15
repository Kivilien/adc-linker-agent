"""
ADC Linker Agent — Streamlit 聊天界面（架构 v2）

架构 v2 关键变更:
  - 双通道渲染: LLM 综合（文本）+ shared_context（结构化组件）
  - 文献卡片始终从 shared_context.literature_data 渲染
  - 设计报告从 shared_context.design_report 渲染
  - 错误面板从 shared_context.errors 渲染
  - 使用 stream_mode="values" 获取增量状态更新

启动方式:
  streamlit run adc_linker_agent/ui/app.py
"""

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import streamlit as st
from langchain_core.messages import HumanMessage

from adc_linker_agent.agent.graph import get_agent
from adc_linker_agent.agent.state import make_shared_context
from adc_linker_agent.ui.components import (
    render_design_report,
    render_feedback_row,
    render_literature_cards,
    render_message_content,
    render_sidebar,
    render_streaming_status,
    render_tool_call,
)
from adc_linker_agent.utils.audit import write_ui_audit
from adc_linker_agent.utils.config import get_config
from adc_linker_agent.utils.validators import MEDICAL_DISCLAIMER

logger = logging.getLogger(__name__)

# ─── 会话持久化 ───

SESSION_FILE = Path(__file__).parent.parent.parent / ".streamlit_session.json"


def _save_session(messages: list[dict], thread_id: str) -> None:
    """保存会话到 JSON 文件，Streamlit 重启后恢复"""
    with contextlib.suppress(Exception):
        SESSION_FILE.write_text(json.dumps({
            "messages": messages[-20:],
            "thread_id": thread_id,
        }, ensure_ascii=False))


def _load_session() -> tuple[list[dict], str]:
    """从 JSON 文件恢复会话"""
    try:
        if SESSION_FILE.exists():
            data = json.loads(SESSION_FILE.read_text())
            return data.get("messages", []), data.get("thread_id", "")
    except Exception:
        logger.warning("Failed to load session from file", exc_info=True)
    return [], ""


def _clear_session_file() -> None:
    """删除会话文件"""
    with contextlib.suppress(Exception):
        SESSION_FILE.unlink(missing_ok=True)


# ─── 页面配置 ───

st.set_page_config(
    page_title="ADC Linker Agent",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🧬 ADC 连接子智能设计 Agent")
st.caption(
    "Antibody-Drug Conjugate Linker Design Assistant | "
    "Multi-Agent System | LangGraph + RDKit"
)

# ─── 侧边栏 ───

mode = render_sidebar()
st.session_state._mode = mode

# ─── 初始化 session state ───

if "messages" not in st.session_state:
    saved_messages, saved_thread = _load_session()
    if saved_messages:
        # 有历史会话 → 暂存，等用户决定
        st.session_state.messages = []
        st.session_state.thread_id = f"ui_{int(time.time())}"
        st.session_state._pending_restore = True
        st.session_state._saved_messages = saved_messages
        st.session_state._saved_thread = saved_thread
    else:
        # 无历史 → 全新开始
        st.session_state.messages = []
        st.session_state.thread_id = f"ui_{int(time.time())}"
        st.session_state._pending_restore = False
if "tool_history" not in st.session_state:
    st.session_state.tool_history = []

# ─── API Key 检查 ───

config = get_config()
has_api_key = config.has_api_key

if not has_api_key:
    st.warning(
        "⚠️ 未配置 LLM API Key。\n\n"
        "在项目根目录创建 `.env` 文件并添加:\n"
        "```\n"
        "# DeepSeek:\n"
        "DEEPSEEK_API_KEY=sk-...\n"
        "LLM_PROVIDER=deepseek\n\n"
        "# 或 Anthropic:\n"
        "ANTHROPIC_API_KEY=sk-ant-...\n"
        "```\n"
        "然后重启 Streamlit。"
    )

# ─── 会话恢复提示 ───

if st.session_state.get("_pending_restore"):
    saved_msgs = st.session_state.get("_saved_messages", [])
    saved_thread = st.session_state.get("_saved_thread", "")

    # 用 container 展示恢复提示
    with st.container(border=True):
        st.markdown(
            f"**检测到上次对话**（{len(saved_msgs)} 条消息）"
        )

        # 展示最后一条用户消息作为预览
        last_user_msg = ""
        for m in reversed(saved_msgs):
            if m.get("role") == "user":
                last_user_msg = m.get("content", "")[:80]
                break
        if last_user_msg:
            st.caption(f"上次查询: _{last_user_msg}_")

        c1, c2, c3 = st.columns([1, 1, 4])
        with c1:
            if st.button("继续对话", type="primary", use_container_width=True):
                st.session_state.messages = saved_msgs
                st.session_state.thread_id = saved_thread
                st.session_state._pending_restore = False
                st.rerun()
        with c2:
            if st.button("开始新对话", use_container_width=True):
                _clear_session_file()
                st.session_state.messages = []
                st.session_state.thread_id = f"ui_{int(time.time())}"
                st.session_state._pending_restore = False
                st.rerun()

# ─── 显示历史消息 ───

for msg in st.session_state.messages:
    role = msg.get("role", "user")
    content = msg.get("content", "")

    with st.chat_message(role):
        tool_calls = msg.get("tool_calls", [])
        for tc in tool_calls:
            render_tool_call(
                name=tc.get("name", "unknown"),
                args=tc.get("args", {}),
                result=tc.get("result"),
            )

        if role == "assistant":
            # 检查是否有渲染数据
            report = msg.get("design_report")
            lit = msg.get("literature_data")

            if report:
                if isinstance(report, dict):
                    from adc_linker_agent.domain.report import DesignReport
                    report = DesignReport.from_dict(report)
                render_design_report(report)
            if lit:
                render_literature_cards(lit)
            if content and content.strip():
                render_message_content(content)
            # 历史消息中只对最后一条助手消息显示反馈按钮
            is_last = msg is st.session_state.messages[-1]
            if is_last:
                msg_idx = len([
                    m for m in st.session_state.messages
                    if m["role"] == "assistant"
                ]) - 1
                render_feedback_row(msg_idx)
        else:
            st.markdown(content)


# ─── Agent 状态标签 ───

_AGENT_LABELS: dict[str, str] = {
    "supervisor": "🧠 分析中...",
    "property_agent": "🔬 计算分子性质...",
    "ph_agent": "🧪 评估 pH 稳定性...",
    "linker_agent": "🔗 设计连接子...",
    "literature_agent": "📚 检索文献...",
}


# ─── Agent 执行（stream_mode="values"） ───


async def _run_agent(
    graph: Any, state: dict, graph_config: dict
) -> tuple[dict, list[dict], float]:
    """
    使用 stream_mode="values" 执行 Agent。

    相比旧的 astream_events:
      - 不需要手动拼接 LLM token 流
      - 每个 step 后得到完整 state（包含 shared_context）
      - 最后的 state 包含所有累积数据

    Returns:
        (final_state, tool_calls, elapsed_ms)
    """
    start_time = time.perf_counter()
    status_placeholder = st.empty()

    final_state: dict = {}

    async for state_update in graph.astream(
        state, graph_config, stream_mode="values"
    ):
        final_state = state_update

        # 显示当前执行的 Agent
        next_agent = state_update.get("next", "")
        if next_agent in _AGENT_LABELS:
            render_streaming_status(
                placeholder=status_placeholder,
                agent_name=next_agent,
                agent_label=_AGENT_LABELS[next_agent],
            )
        elif next_agent == "__synthesize__":
            render_streaming_status(
                placeholder=status_placeholder,
                agent_name="synthesizer",
                agent_label="📝 综合结果...",
            )
        elif next_agent == "FINISH":
            render_streaming_status(
                placeholder=status_placeholder,
                agent_name="done",
                agent_label="✅ 完成",
            )

    status_placeholder.empty()
    elapsed = (time.perf_counter() - start_time) * 1000

    # 提取工具调用信息（从 messages 中找 tool 消息）
    tool_calls = []
    messages = final_state.get("messages", [])
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    "name": tc.get("name", "unknown"),
                    "args": tc.get("args", {}),
                    "result": None,  # Tool results are in separate messages
                })

    return final_state, tool_calls, elapsed


# ─── 聊天输入 ───

# ─── 聊天输入 ───

chat_placeholder = (
    "输入目标 pH 或点击侧边栏预设..."
    if st.session_state.get("_mode") == "quick"
    else "输入你的 ADC 连接子相关查询..."
)

if prompt := st.chat_input(chat_placeholder):
    # 用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Agent 响应
    with st.chat_message("assistant"):
        # ─── Quick 模式：无 LLM 直接设计 ───
        if mode == "quick":
            import re

            from adc_linker_agent.domain.linker_designer import (
                LinkerDesigner,
                LinkerDesignRequest,
            )
            from adc_linker_agent.domain.report import generate_report

            handler_start = time.perf_counter()
            try:
                quick_ph = st.session_state.get("quick_ph", 5.0)
                quick_mech_raw = st.session_state.get("quick_mechanism", "All")
                preferred_mech = None if quick_mech_raw == "All" else quick_mech_raw

                # 从用户输入解析 pH 覆盖
                ph_match = re.search(r"pH\s*([\d.]+)", prompt)
                target_ph = float(ph_match.group(1)) if ph_match else quick_ph

                designer = LinkerDesigner()
                request = LinkerDesignRequest(
                    target_ph=target_ph,
                    preferred_mechanism=preferred_mech,
                    max_results=5,
                )
                result = designer.design(request)
                report = generate_report(result)

                render_design_report(report)

                elapsed = (time.perf_counter() - handler_start) * 1000
                st.caption(
                    f"⚡ Quick Design | ⏱️ {elapsed:.0f}ms | "
                    f"No LLM (纯本地计算)"
                )
                st.caption(MEDICAL_DISCLAIMER)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": (
                        f"[Quick Design] pH={target_ph}, "
                        f"mechanism={quick_mech_raw}"
                    ),
                    "tool_calls": [],
                    "design_report": report,
                })
                _save_session(
                    st.session_state.messages,
                    st.session_state.thread_id,
                )

            except Exception as e:
                st.error(f"Quick design failed: {e}")

        elif not has_api_key:
            st.error(
                "❌ 无法调用 Agent：未配置 API Key。\n\n"
                "请在 `.env` 文件中设置 `ANTHROPIC_API_KEY` 或 `DEEPSEEK_API_KEY`。"
            )
            st.session_state.messages.append({
                "role": "assistant",
                "content": "[错误] 未配置 API Key",
                "tool_calls": [],
            })
        else:
            handler_start = time.perf_counter()
            try:
                graph, graph_config = get_agent(
                    thread_id=st.session_state.thread_id,
                    mode=mode,  # type: ignore[arg-type]
                )

                # 初始状态：包含 shared_context
                state = {
                    "messages": [HumanMessage(content=prompt)],
                    "shared_context": make_shared_context(),
                }

                # ─── 执行 Agent ───
                final_state, tool_calls_made, elapsed = asyncio.run(
                    _run_agent(graph, state, graph_config)
                )

                ctx = final_state.get("shared_context", {})

                # ─── 渲染结构化组件（从 shared_context） ───

                has_structured = False

                # 1. 设计报告
                report = ctx.get("design_report")
                if report:
                    if isinstance(report, dict):
                        from adc_linker_agent.domain.report import DesignReport
                        report = DesignReport.from_dict(report)
                    render_design_report(report)
                    has_structured = True

                # 2. 文献结果（核心修复：始终从 shared_context 渲染）
                lit = ctx.get("literature_data")
                if lit and lit.get("papers"):
                    render_literature_cards(lit)
                    has_structured = True

                # 3. LLM 综合文本
                # 获取最后一条 AIMessage（Synthesizer 的输出）
                messages = final_state.get("messages", [])
                synthesis_text = ""
                for msg in reversed(messages):
                    if hasattr(msg, "content") and msg.content:
                        content = msg.content
                        # 跳过纯 JSON 路由决策（旧 supervisor 残留）
                        if content.strip().startswith("{"):
                            continue
                        synthesis_text = content
                        break

                if synthesis_text:
                    render_message_content(synthesis_text)
                    has_structured = True

                # 如果什么输出都没有
                if not has_structured:
                    st.info("Agent 已完成处理，但未返回内容。")

                # 4. 错误面板
                errors = ctx.get("errors", [])
                if errors:
                    with st.expander(
                        f"⚠️ 处理中遇到 {len(errors)} 个问题", expanded=False
                    ):
                        for e in errors:
                            st.warning(
                                f"[{e.get('agent', '?')}] {e.get('error', '?')}"
                            )

                # ─── 工具调用详情（折叠） ───
                if tool_calls_made:
                    with st.expander(
                        f"🔧 工具调用 ({len(tool_calls_made)} 次)",
                        expanded=False,
                    ):
                        for tc in tool_calls_made:
                            render_tool_call(
                                name=tc["name"],
                                args=tc["args"],
                                result=tc.get("result"),
                                compact=True,
                            )

                # ─── 底部信息 ───
                st.caption(
                    f"⏱️ {elapsed:.0f}ms | "
                    f"🔧 {len(tool_calls_made)} tools | "
                    f"Thread: `{st.session_state.thread_id[:12]}...`"
                )
                st.caption(MEDICAL_DISCLAIMER)

                # ─── 审计日志 ───
                write_ui_audit(
                    thread_id=st.session_state.thread_id,
                    query=prompt,
                    status="ok",
                    elapsed_ms=elapsed,
                    tool_calls=len(tool_calls_made),
                )

                # ─── 保存到历史 ───
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": synthesis_text,
                    "tool_calls": tool_calls_made,
                    "design_report": ctx.get("design_report"),
                    "literature_data": ctx.get("literature_data"),
                })

                _save_session(
                    st.session_state.messages,
                    st.session_state.thread_id,
                )

                # ─── 反馈按钮 ───
                assistant_count = len([
                    m for m in st.session_state.messages
                    if m["role"] == "assistant"
                ])
                render_feedback_row(assistant_count - 1)

            except Exception as e:
                error_msg = str(e)
                st.error(f"❌ Agent 调用失败: {error_msg}")

                write_ui_audit(
                    thread_id=st.session_state.thread_id,
                    query=prompt,
                    status="error",
                    elapsed_ms=(time.perf_counter() - handler_start) * 1000,
                )

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"[错误] {error_msg}",
                    "tool_calls": [],
                })

# ─── 底部操作栏 ───

col1, col2, col3 = st.columns(3)
with col1:
    if st.button(
        "🔄 新对话", help="清除对话历史，开始新会话"
    ):
        st.session_state.messages = []
        st.session_state.thread_id = f"ui_{int(time.time())}"
        st.session_state.tool_history = []
        with contextlib.suppress(Exception):
            SESSION_FILE.unlink(missing_ok=True)
        st.rerun()
with col2:
    if st.button("📋 复制对话", help="复制全部对话到剪贴板"):
        text = "\n\n".join(
            f"{'🧑 用户' if m['role'] == 'user' else '🤖 Agent'}:\n"
            f"{m['content']}"
            for m in st.session_state.messages
        )
        st.code(text, language=None)
with col3:
    st.caption(f"Thread: `{st.session_state.thread_id[:12]}...`")

# ─── 启动说明 ───

if not st.session_state.messages and not has_api_key:
    st.divider()
    st.info("""
    ### 快速开始

    1. 复制 `.env.template` → `.env`
    2. 填入 DeepSeek 或 Anthropic API Key
    3. 重启 Streamlit
    4. 聊天框输入查询！
    """)
