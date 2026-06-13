"""
审计日志模块

以 JSONL 格式记录所有 API 请求，用于安全审计和合规追溯。

每条日志包含:
  - timestamp: ISO 8601 时间戳
  - client_ip: 请求来源 IP
  - thread_id: 对话线程 ID
  - query: 用户查询（截断至 200 字符）
  - status: "ok" | "auth_denied" | "rate_limited" | "validation_error" | "error"
  - elapsed_ms: 处理耗时
  - tool_calls: 工具调用次数
  - user_agent: 客户端 User-Agent

设计决定:
  - 使用文件追加写入而非数据库：单机 demo 场景，零依赖
  - JSONL 格式：每行一条独立 JSON，支持 grep/jq 快速查询
  - 不记录完整查询内容（截断 200 字符）以降低隐私风险
  - 写入失败不阻塞请求（静默降级）
"""

import json
import os
from datetime import UTC, datetime


def write_audit_log(
    *,
    client_ip: str = "unknown",
    thread_id: str = "default",
    query: str = "",
    status: str = "ok",
    elapsed_ms: float = 0.0,
    tool_calls: int = 0,
    user_agent: str = "",
    log_path: str = "",
) -> None:
    """
    追加一条审计日志。

    Args:
        client_ip: 请求来源 IP
        thread_id: 对话线程 ID
        query: 用户查询（自动截断至 200 字符）
        status: 状态标签（ok/auth_denied/rate_limited/validation_error/error）
        elapsed_ms: 处理耗时（毫秒）
        tool_calls: 工具调用次数
        user_agent: 客户端 User-Agent 头
        log_path: 日志文件路径（默认从 config 读取）
    """
    if not log_path:
        from adc_linker_agent.utils.config import get_config

        log_path = str(get_config().audit_log_path)

    # 确保日志目录存在
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    entry = {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "client_ip": client_ip,
        "thread_id": thread_id,
        "query": query[:200],
        "query_truncated": len(query) > 200,
        "status": status,
        "elapsed_ms": round(elapsed_ms, 1),
        "tool_calls": tool_calls,
        "user_agent": user_agent[:200],
    }

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        # 写入失败静默降级，不阻塞请求
        pass
