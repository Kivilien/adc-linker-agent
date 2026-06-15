#!/usr/bin/env python3
"""
ADC Linker Agent — 自主审计脚本

运行 8 模式缺陷扫描，分析反馈/错误日志，生成优先级排序的修复清单。

用法:
    python scripts/audit.py              # 全量审计
    python scripts/audit.py --quick      # 仅静态扫描，跳过日志分析
    python scripts/audit.py --json       # JSON 输出（供 CI 消费）

数据源:
    - logs/feedback.jsonl  用户反馈
    - logs/audit.jsonl      API 审计日志
    - 源代码（8 模式静态扫描）
"""

import argparse
import contextlib
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"


# ═══════════════════════════════════════════════════════════════
# 日志分析
# ═══════════════════════════════════════════════════════════════


def _read_jsonl(path: Path, since: datetime | None = None) -> list[dict]:
    """读取 JSONL 文件，可选时间过滤。"""
    if not path.exists():
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since:
                ts = entry.get("timestamp", "")
                try:
                    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if t < since:
                        continue
                except (ValueError, TypeError):
                    pass
            entries.append(entry)
    return entries


def analyze_feedback(since: datetime | None = None) -> list[dict]:
    """分析 feedback.jsonl 提取高频问题。"""
    path = LOGS_DIR / "feedback.jsonl"
    entries = _read_jsonl(path, since)

    if not entries:
        return []

    down_votes = [e for e in entries if e.get("rating") == "down"]
    categories = Counter(e.get("category", "other") for e in down_votes)
    issues = []

    for cat, count in categories.most_common():
        sample_comments = [
            e.get("comment", "")
            for e in down_votes
            if e.get("category") == cat and e.get("comment")
        ][:3]
        issues.append(
            {
                "source": "feedback",
                "category": cat,
                "count": count,
                "pct": round(count / len(entries) * 100, 1),
                "sample_comments": sample_comments,
            }
        )

    return issues


def analyze_errors(since: datetime | None = None) -> list[dict]:
    """分析 audit.jsonl 提取高频错误。"""
    path = LOGS_DIR / "audit.jsonl"
    entries = _read_jsonl(path, since)

    errors = [e for e in entries if e.get("status") == "error"]
    if not errors:
        return []

    # 按 IP 聚合
    by_ip = Counter(e.get("client_ip", "?") for e in errors)
    return [
        {
            "source": "audit",
            "total_requests": len(entries),
            "error_count": len(errors),
            "error_rate": round(len(errors) / len(entries) * 100, 1),
            "top_ips": by_ip.most_common(3),
        }
    ]


# ═══════════════════════════════════════════════════════════════
# 8 模式静态扫描
# ═══════════════════════════════════════════════════════════════


def _run_grep(pattern: str, path: str = ".") -> int:
    """运行 grep 返回匹配行数。"""
    try:
        result = subprocess.run(
            ["grep", "-r", "--include=*.py", "-l", pattern, str(PROJECT_ROOT / path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = result.stdout.strip().split("\n")
        return len([line for line in lines if line])
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return -1


def _py_files() -> list[Path]:
    """返回所有 Python 源文件。"""
    return list((PROJECT_ROOT / "adc_linker_agent").rglob("*.py"))


def scan_config_drift() -> list[dict]:
    """模式 1: 配置漂移 — os.getenv 未被消费。"""
    findings = []
    source_dir = PROJECT_ROOT / "adc_linker_agent"
    # 找到所有 config.py 中的 env var 读取
    config_file = source_dir / "utils" / "config.py"
    if not config_file.exists():
        return findings
    config_code = config_file.read_text()
    import re

    env_vars = re.findall(r'os\.getenv\("([^"]+)"', config_code)
    for var in env_vars:
        # 检查在非 config.py 代码中是否有引用
        refs = _run_grep(f"config\\.{var.lower()}", "adc_linker_agent")
        if refs <= 1:  # 只有 config.py 自身引用
            findings.append(
                {
                    "pattern": "config_drift",
                    "severity": "low",
                    "detail": f"环境变量 {var} 在配置中定义但代码中仅 {refs} 处引用",
                }
            )
    return findings


def scan_registration_gaps() -> list[dict]:
    """模式 2: 注册缺口 — 多入口工具注册不一致。"""
    findings = []
    # 比较 agent/tools.py 和 mcp_tools/server.py 的工具数
    try:
        from adc_linker_agent.agent.tools import ALL_TOOLS

        agent_count = len(ALL_TOOLS)
    except ImportError:
        agent_count = -1
    try:
        # 检查 mcp_tools 模块的工具函数数
        import adc_linker_agent.mcp_tools.server as mcp_server

        mcp_funcs = [
            name
            for name in dir(mcp_server)
            if name.startswith("_") and callable(getattr(mcp_server, name, None))
        ]
        mcp_count = len(mcp_funcs)
    except ImportError:
        mcp_count = -1

    if agent_count > 0 and mcp_count > 0 and agent_count != mcp_count:
        findings.append(
            {
                "pattern": "registration_gap",
                "severity": "high",
                "detail": f"Agent 工具数 ({agent_count}) ≠ MCP 工具数 ({mcp_count})",
            }
        )

    # 检查 domain/__init__.py 导出完整性
    try:
        import adc_linker_agent.domain as domain_mod

        public = [n for n in dir(domain_mod) if not n.startswith("_")]
        src_files = list((PROJECT_ROOT / "adc_linker_agent" / "domain").glob("*.py"))
        expected = set()
        for f in src_files:
            if f.name.startswith("_"):
                continue
            code = f.read_text()
            # 找到所有 def/class 顶层定义
            import re

            names = re.findall(r"^(?:def|class)\s+(\w+)", code, re.MULTILINE)
            expected.update(n for n in names if not n.startswith("_"))
        missing = expected - set(public)
        if missing:
            findings.append(
                {
                    "pattern": "registration_gap",
                    "severity": "medium",
                    "detail": f"domain/__init__.py 缺少导出: {', '.join(sorted(missing))}",
                }
            )
    except ImportError:
        pass

    return findings


def scan_dead_code() -> list[dict]:
    """模式 3: 死代码 — Vulture 扫描（如果可用）。"""
    findings = []
    try:
        result = subprocess.run(
            ["vulture", str(PROJECT_ROOT / "adc_linker_agent"), "--min-confidence", "80"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = [ln.strip() for ln in result.stdout.split("\n") if ln.strip()]
        # 过滤误报：__init__.py 导出、测试相关
        for line in lines[:10]:
            if "test_" in line or "conftest" in line:
                continue
            findings.append(
                {
                    "pattern": "dead_code",
                    "severity": "low",
                    "detail": line[:200],
                }
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # vulture not installed — skip
        pass
    return findings


def scan_doc_drift() -> list[dict]:
    """模式 4: 文档漂移 — README/CLAUDE.md 数字一致性。"""
    findings = []
    try:
        from adc_linker_agent.agent.tools import ALL_TOOLS

        tool_count = len(ALL_TOOLS)
    except ImportError:
        tool_count = 0

    readme = PROJECT_ROOT / "README.md"
    if readme.exists():
        text = readme.read_text()
        import re

        # 查找 README 中的工具数字
        tool_mentions = re.findall(r"(\d+)\s*(?:个?工具|tools)", text, re.IGNORECASE)
        for num_str in tool_mentions:
            if int(num_str) != tool_count and tool_count > 0:
                findings.append(
                    {
                        "pattern": "doc_drift",
                        "severity": "low",
                        "detail": f"README 声称 {num_str} 个工具，实际为 {tool_count}",
                    }
                )

    # 版本号检查
    with contextlib.suppress(ImportError):
        from adc_linker_agent import __version__  # noqa: F401
    claude_md = PROJECT_ROOT / "CLAUDE.md"
    if claude_md.exists() and readme.exists():
        for path in [readme, claude_md]:
            text = path.read_text()
            versions = set(re.findall(r"v(\d+\.\d+\.\d+)", text))
            if len(versions) > 1:
                findings.append(
                    {
                        "pattern": "doc_drift",
                        "severity": "low",
                        "detail": f"{path.name} 包含多个版本号: {versions}",
                    }
                )

    return findings


def scan_error_swallowing() -> list[dict]:
    """模式 5: 错误静默 — except Exception 无 logging。"""
    findings = []
    for py_file in _py_files():
        if "test_" in py_file.name or py_file.name.startswith("_"):
            continue
        code = py_file.read_text()
        # 简单启发式: except Exception 后紧跟 pass 或无 log/raise
        import re

        blocks = re.findall(
            r"except\s+(?:Exception|BaseException)(?:\s+as\s+\w+)?\s*:(.*?)(?=\n\S|\Z)",
            code,
            re.DOTALL,
        )
        for block in blocks:
            block_stripped = block.strip()
            if block_stripped in ("pass", "...") or (
                "log" not in block_stripped
                and "raise" not in block_stripped
                and "audit" not in block_stripped
                and "error" not in block_stripped.lower()
            ):
                findings.append(
                    {
                        "pattern": "error_swallowing",
                        "severity": "medium",
                        "detail": (
                            f"{py_file.relative_to(PROJECT_ROOT)}: except Exception 无错误记录"
                        ),
                    }
                )
    return findings


def scan_unbounded_growth() -> list[dict]:
    """模式 6: 无界增长 — dict/list 无 TTL 清理。"""
    findings = []
    for py_file in _py_files():
        if "test_" in py_file.name:
            continue
        code = py_file.read_text()
        # 查找 defaultdict 或 dict 用作缓存但无清理逻辑
        if "defaultdict" in code or "cache" in code.lower() or "store" in code.lower():
            has_ttl = "TTL" in code or "ttl" in code or "lru_cache" in code or "expire" in code
            if not has_ttl and "class" in code:
                findings.append(
                    {
                        "pattern": "unbounded_growth",
                        "severity": "low",
                        "detail": f"{py_file.relative_to(PROJECT_ROOT)}: 缓存结构可能缺少 TTL",
                    }
                )
    return findings


def scan_dependency_bounds() -> list[dict]:
    """模式 7: 依赖无上界。"""
    findings = []
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if not pyproject.exists():
        return findings
    content = pyproject.read_text()
    import re

    deps = re.findall(r'"([^"]+)>=([^"]+)"', content)
    for dep, version in deps:
        if "<" not in dep and ">" not in dep.replace(">=", ""):
            # 已经处理过了，检查是否有上界
            full_match = re.search(rf'"{dep}>=[^"]*"', content)
            if full_match and "<" not in full_match.group():
                findings.append(
                    {
                        "pattern": "dependency_bounds",
                        "severity": "medium",
                        "detail": f"{dep} 缺少上界约束（当前 >= {version}）",
                    }
                )
    return findings


def scan_api_leakage() -> list[dict]:
    """模式 8: API 信息泄漏 — str(e) 在 HTTPException 中。"""
    findings = []
    routes = PROJECT_ROOT / "adc_linker_agent" / "api" / "routes.py"
    if routes.exists():
        code = routes.read_text()
        if "detail=str(e)" in code:
            findings.append(
                {
                    "pattern": "api_leakage",
                    "severity": "high",
                    "detail": "routes.py: HTTPException 使用 str(e) 可能泄漏内部信息",
                }
            )
        # 同时检查是否仍有 500 使用了 str(e)
        if "status_code=500" in code and "raise HTTPException" in code:
            # 验证是否有 str(e) 在旁边
            import re

            blocks = re.findall(
                r"raise HTTPException\([^)]+500[^)]+\)",
                code,
                re.DOTALL,
            )
            for block in blocks:
                if "str(e)" in block:
                    findings.append(
                        {
                            "pattern": "api_leakage",
                            "severity": "high",
                            "detail": f"routes.py: 500 错误仍使用 str(e): {block[:100]}",
                        }
                    )
    return findings


# ═══════════════════════════════════════════════════════════════
# v1.2: 顾问系统扫描
# ═══════════════════════════════════════════════════════════════

ADVISORS_DIR = Path.home() / ".claude" / "advisors"


def scan_advisor_knowledge_staleness() -> list[dict]:
    """模式 9: 顾问知识新鲜度 — memory.md 超过 30 天未更新。"""
    findings = []
    if not ADVISORS_DIR.exists():
        return findings
    cutoff = datetime.now(UTC) - timedelta(days=30)
    for advisor_dir in ADVISORS_DIR.iterdir():
        if not advisor_dir.is_dir():
            continue
        memory_file = advisor_dir / "memory.md"
        if not memory_file.exists():
            findings.append(
                {
                    "pattern": "advisor_knowledge_staleness",
                    "severity": "low",
                    "detail": f"顾问 {advisor_dir.name}: memory.md 不存在",
                }
            )
            continue
        mtime = datetime.fromtimestamp(memory_file.stat().st_mtime, tz=UTC)
        if mtime < cutoff:
            days_stale = (datetime.now(UTC) - mtime).days
            findings.append(
                {
                    "pattern": "advisor_knowledge_staleness",
                    "severity": "medium",
                    "detail": f"顾问 {advisor_dir.name}: memory.md {days_stale} 天未更新",
                }
            )
        # 检查 web-sources.md
        web_sources = advisor_dir / "web-sources.md"
        if web_sources.exists():
            ws_mtime = datetime.fromtimestamp(web_sources.stat().st_mtime, tz=UTC)
            if ws_mtime < cutoff:
                days_stale = (datetime.now(UTC) - ws_mtime).days
                findings.append(
                    {
                        "pattern": "advisor_knowledge_staleness",
                        "severity": "low",
                        "detail": f"顾问 {advisor_dir.name}: web-sources.md {days_stale} 天未更新",
                    }
                )
    return findings


def scan_advisor_prompt_drift() -> list[dict]:
    """模式 10: 顾问 prompt 漂移 — agent 定义与知识库不一致。"""
    findings = []
    agents_dir = Path.home() / ".claude" / "agents"
    advisor_agents = ["technical-advisor.md", "ui-design-advisor.md", "competitor-power-user.md"]
    for agent_file in advisor_agents:
        agent_path = agents_dir / agent_file
        if not agent_path.exists():
            findings.append(
                {
                    "pattern": "advisor_prompt_drift",
                    "severity": "high",
                    "detail": f"顾问 agent 定义缺失: {agent_file}",
                }
            )
            continue
        agent_content = agent_path.read_text()
        name = agent_file.replace(".md", "")
        memory_path = ADVISORS_DIR / name / "memory.md"
        if not memory_path.exists():
            findings.append(
                {
                    "pattern": "advisor_prompt_drift",
                    "severity": "medium",
                    "detail": f"顾问 {name}: agent 定义存在但 memory.md 缺失",
                }
            )
            continue
        # 检查 agent 定义中引用的路径是否与实际一致
        if f"advisors/{name}/memory.md" not in agent_content:
            findings.append(
                {
                    "pattern": "advisor_prompt_drift",
                    "severity": "low",
                    "detail": f"顾问 {name}: agent 定义中可能缺少正确的 memory 路径引用",
                }
            )
    return findings


def scan_skill_rot() -> list[dict]:
    """模式 11: skill 腐烂 — 导入的 skill 30 天未使用或源仓库已归档。"""
    findings = []
    registry_path = Path.home() / ".agents" / "skills" / "imported" / "registry.yaml"
    if not registry_path.exists():
        return findings
    try:
        import yaml

        with open(registry_path) as f:
            registry = yaml.safe_load(f)
    except Exception:
        return findings
    if not registry or "skills" not in registry:
        return findings
    for skill in registry["skills"]:
        last_used = skill.get("last_used")
        if last_used:
            try:
                used_date = datetime.fromisoformat(str(last_used))
                days_unused = (datetime.now(UTC) - used_date).days
                if days_unused > 30:
                    findings.append(
                        {
                            "pattern": "skill_rot",
                            "severity": "low",
                            "detail": f"Skill {skill['name']}: {days_unused} 天未使用，建议归档",
                        }
                    )
            except (ValueError, TypeError):
                pass
    return findings


SCANNERS = [
    ("config_drift", scan_config_drift),
    ("registration_gaps", scan_registration_gaps),
    ("dead_code", scan_dead_code),
    ("doc_drift", scan_doc_drift),
    ("error_swallowing", scan_error_swallowing),
    ("unbounded_growth", scan_unbounded_growth),
    ("dependency_bounds", scan_dependency_bounds),
    ("api_leakage", scan_api_leakage),
    ("advisor_knowledge_staleness", scan_advisor_knowledge_staleness),
    ("advisor_prompt_drift", scan_advisor_prompt_drift),
    ("skill_rot", scan_skill_rot),
]


# ═══════════════════════════════════════════════════════════════
# 报告
# ═══════════════════════════════════════════════════════════════


def priority(findings: list[dict]) -> list[dict]:
    """按严重程度排序: high → medium → low。"""
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(findings, key=lambda f: order.get(f.get("severity"), 99))


def format_report(findings: list[dict], feedback: list[dict], errors: list[dict]) -> str:
    """生成 Markdown 格式审计报告。"""
    lines = [
        "# ADC Linker Agent 审计报告",
        f"生成时间: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        "## 摘要",
        f"- 代码扫描发现: {len(findings)} 项",
        f"- 用户反馈: {sum(f.get('count', 0) for f in feedback)} 条差评",
        f"- API 错误: {errors[0].get('error_count', 0) if errors else 0} 次",
        "",
    ]

    if feedback:
        lines.append("## 用户反馈")
        for f in feedback:
            lines.append(f"- **{f['category']}**: {f['count']} 次 ({f['pct']}%)")
            for c in f.get("sample_comments", []):
                if c:
                    lines.append(f"  > {c[:100]}")
        lines.append("")

    if errors:
        lines.append("## API 错误")
        for e in errors:
            lines.append(
                f"- 请求: {e['total_requests']}, 错误: {e['error_count']} ({e['error_rate']}%)"
            )
        lines.append("")

    if findings:
        lines.append("## 代码扫描发现")
        lines.append("")
        for f in findings:
            severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(f["severity"], "⚪")
            lines.append(f"- {severity_icon} [{f['pattern']}] {f['detail']}")
        lines.append("")

    # 修复建议
    lines.append("## 修复建议")
    high_count = len([f for f in findings if f["severity"] == "high"])
    med_count = len([f for f in findings if f["severity"] == "medium"])
    low_count = len([f for f in findings if f["severity"] == "low"])
    lines.append(f"- 🔴 {high_count} 项高优先级（需立即关注）")
    lines.append(f"- 🟡 {med_count} 项中优先级（本次迭代修复）")
    lines.append(f"- 🟢 {low_count} 项低优先级（可延后或自动修复）")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="ADC Linker Agent 自主审计")
    parser.add_argument("--quick", action="store_true", help="仅静态扫描，跳过日志分析")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--since-days", type=int, default=7, help="分析最近 N 天的日志")
    args = parser.parse_args()

    # 时间窗口
    since = datetime.now(UTC) - timedelta(days=args.since_days)

    # 运行扫描
    all_findings = []
    for name, scanner in SCANNERS:
        try:
            findings = scanner()
            all_findings.extend(findings)
        except Exception as exc:
            all_findings.append(
                {
                    "pattern": name,
                    "severity": "low",
                    "detail": f"Scanner {name} 执行失败: {exc}",
                }
            )

    sorted_findings = priority(all_findings)

    # 日志分析（除非 --quick）
    feedback = [] if args.quick else analyze_feedback(since)
    errors = [] if args.quick else analyze_errors(since)

    if args.json:
        output = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "summary": {
                "code_findings": len(sorted_findings),
                "feedback_issues": len(feedback),
                "error_entries": errors[0].get("error_count", 0) if errors else 0,
            },
            "findings": sorted_findings,
            "feedback": feedback,
            "errors": errors,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        report = format_report(sorted_findings, feedback, errors)
        print(report)

    # 退出码：有 high 或 medium 问题时返回 1
    has_issues = any(f["severity"] in ("high", "medium") for f in sorted_findings)
    if has_issues:
        sys.exit(1)


if __name__ == "__main__":
    main()
