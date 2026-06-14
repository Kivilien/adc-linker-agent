# 自主迭代系统

ADC Linker Agent 平台的自主进化系统，参考 Claude Code 自迭代模式设计。

## 架构

```
Layer 1: 安全网 (CI/CD)
  └─ GitHub Actions: push → ruff + pytest + coverage
  └─ Status badge 可视化

Layer 2: 感知层 (反馈收集)
  └─ UI 反馈按钮 (👍/👎) + 反馈表单
  └─ POST /agent/feedback API
  └─ 审计日志 (logs/audit.jsonl + logs/feedback.jsonl)

Layer 3: 决策层 (自主迭代)
  └─ 周度 CronCreate 审计任务
  └─ 8 模式自动扫描 → 发现问题 → dev-agent 修复
  └─ feedback.jsonl 分析 → 识别高频问题 → 提案
```

## 数据流

```
用户交互 → feedback.jsonl / audit.jsonl
                    ↓
         CronCreate 定时任务 (每周一 9:07)
                    ↓
         分析引擎: scripts/audit.py
         - 8 模式静态扫描
         - 反馈趋势分析
         - 错误率分析
                    ↓
         优先级排序 → 分类:
         - L0: 自动修复 (typo, 死代码, E501)
         - L1: 半自动 (dev-agent → PR → 人工 merge)
         - L2: 提案 (写 state/proposals.md → 等用户确认)
                    ↓
         GitHub Actions 验证
                    ↓
         审计报告: logs/audit-report-YYYY-MM-DD.md
```

## 反馈系统

用户在每次 Agent 响应后可提交反馈：

- **👍** — 回答有帮助，直接记录
- **👎** — 展开分类选择 (信息不准确 / 表达不清晰 / 响应太慢 / 其他) + 自由文本

所有反馈写入 `logs/feedback.jsonl`（与 `audit.jsonl` 同目录），格式：

```json
{
  "timestamp": "2026-06-14T09:30:00",
  "thread_id": "ui_1234567890",
  "message_index": 2,
  "rating": "down",
  "category": "incorrect",
  "comment": "LogP 计算值与预期偏差较大"
}
```

API 端点: `POST /agent/feedback`

## 审计脚本

`scripts/audit.py` 独立运行，执行：

1. **8 模式静态扫描** (framework-bug-patterns.md):
   - 配置漂移、注册缺口、死代码、文档漂移
   - 错误静默、无界增长、依赖无上界、API 信息泄漏

2. **反馈趋势分析**: 
   - 统计上周差评分类分布
   - 提取代表性评论文本

3. **错误率分析**:
   - 汇总 API 错误率
   - 按来源 IP 分组

用法:
```bash
python scripts/audit.py              # 全量审计（包含日志分析）
python scripts/audit.py --quick       # 仅静态扫描
python scripts/audit.py --json        # JSON 输出（CI 消费）
python scripts/audit.py --since-days 14  # 分析最近 14 天
```

## 定时任务

通过 Claude Code CronCreate 注册：

```
Cron: "7 9 * * 1" (每周一 9:07 AM)
Durable: true (跨会话持久)
```

任务内容: 运行 `scripts/audit.py --quick` → 读取反馈 → 分类问题 → 自动修复 L0 → 生成报告。

查看任务: `/tasks` 命令。

## CI/CD

### 主 CI (`ci.yml`)

触发: push / PR 到 main

步骤: ruff → mypy → pytest --cov

### 周度审计 (`weekly-audit.yml`)

触发: 每周一 9:07 CST + 手动 (`workflow_dispatch`)

步骤: 全量测试 + 生成审计报告到 GitHub Step Summary

## 修复策略分级

| 级别 | 示例 | 动作 | 审批 |
|------|------|------|------|
| L0 | typo, E501, dead imports, 版本号漂移 | 自动 commit | 无需 |
| L1 | 配置漂移, 注册缺口, 文档漂移 | dev-agent → PR | 人工 merge |
| L2 | 架构问题, 新功能需求 | 写提案到 `state/proposals.md` | 用户确认 |

## 如何干预

- **暂停自主修复**: 删除 CronCreate 任务 (`CronDelete`)
- **跳过某类问题**: 编辑 `scripts/audit.py` 中 SCANNERS 列表
- **调整阈值**: 修改常量 (`_RATE_LIMIT_MAX` 等)
- **手动触发审计**: `python scripts/audit.py` 或 GitHub Actions `workflow_dispatch`

## 相关文件

| 文件 | 用途 |
|------|------|
| `.github/workflows/ci.yml` | 主 CI 工作流 |
| `.github/workflows/weekly-audit.yml` | 周度审计工作流 |
| `scripts/audit.py` | 独立审计脚本 |
| `logs/audit.jsonl` | API 审计日志 |
| `logs/feedback.jsonl` | 用户反馈日志 |
| `~/.claude/memory/framework-bug-patterns.md` | 8 种缺陷模式定义 |
