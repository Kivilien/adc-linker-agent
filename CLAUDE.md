# ADC Linker Agent — 编码规范

> 基于 vibe-coding-cn 方法论，适用于本项目所有 agent

## 拼好码（Glue Coding）
- **复用在先**: 能用 RDKit/API/MCP server 的不自己写；能调文献的不自己编
- **编连不在造**: 这个项目本质是胶水代码——连接 RDKit + PhSimulator + Europe PMC + LangGraph
- **加功能前先问三遍**: 有现成工具吗？有 API 吗？有 MCP server 吗？

## Prompt 编写三要素（用于编写系统提示词）
1. **目标**: 做什么（明确）
2. **边界**: 不做什么（同样重要！）
3. **成功标准**: 什么算"完成"（防止模型提前终止）

## 开发流程
1. 明确目标 → 2. 读上下文 → 3. Tier评估 (T3跳过/T2匹配1顾问/T1全顾问) → 4. EnterPlanMode → 5. 顾问咨询(联网+GitHub挖掘) → 6. 最小修改 → 7. ruff + pytest → 8. 验证

## 顾问委员会 (v1.2)
- **技术顾问** (`technical-advisor`): 全栈技术评估，联网查最佳实践，GitHub 挖掘开发类 skill
- **UI设计顾问** (`ui-design-advisor`): UI/UX 设计评估，联网查设计趋势，GitHub 挖掘 UI 组件
- **竞品体验官** (`competitor-power-user`): 模拟 MoleculeForge 用户，功能差距分析，用户视角反馈
- 顾问输出统一格式: 立场 → 评估 → 建议(Must/Should/Nice) → GitHub推荐 → 风险 → 来源
- 知识累积: `~/.claude/advisors/<name>/memory.md` 跨会话学习

## GitHub Skill 挖掘
- `gh search repos "[keyword] skill OR agent OR mcp" --sort=stars`
- 评分 ≥7 → 下载到 `~/.agents/skills/imported/` → 注册到 registry.yaml
- 项目专用 skill 存储: `.claude/skills/registry.yaml`

## 质量门禁（硬门禁，不可跳过）

**每次代码修改后立即执行，不允许攒到最后批量验证：**
```bash
ruff check . --fix && ruff check . && pytest -x --tb=short
```
1. `ruff check . --fix` — 自动修复能修的
2. `ruff check .` — 确认零残留
3. `pytest -x --tb=short` — 首次失败即停

**阻断规则**：任一环节失败 → 立即修复 → 重新验证 → 全部通过才可提交。跳过验证的修改视为未完成。
**附加检查**：`git diff` — 确认无无关改动

## 反模式（禁止）
- 跳过分析直接写代码
- 跳过验证直接提交（最高频质量失败模式之一）
- 修改核心文件不走 staging
- System prompt 只有"做什么"没有"不做什么"
- 工具描述不写参数和返回值格式

## 项目状态 (2026-06-13)

**架构 v2 完成** — 指标:
- 测试: 323 passed
- 工具: 9 个 (含毒性检测 + 文献搜索)
- 专长 Agent: 4 个 (Property + PH + Linker + Literature)
- 报告: 结构化 DesignReport (纯数据聚合，不依赖 LLM)
- 流式执行: `stream_mode="values"` 替代 `astream_events`，捕获完整状态更新
- 配置外部化: pH 官能团 YAML + 评分权重可配
- 安全: PAINS/Brenk 毒性筛查、医学免责声明、速率限制

**关键架构决策**:
- `ui/app.py` 使用 `asyncio.run(_run_agent())` 驱动 graph，state 经 `stream_mode="values"` 捕获
- Specialist 内部仍用同步 `model.invoke()` — stream_mode 捕获节点级状态
- `design_linker` 工具返回 `_report` 键 → app.py 检测后切换结构化报告渲染
- 报告引擎 (`domain/report.py`) 零 LLM 依赖，纯 Python 数据聚合
- 双通道状态: `messages` (LLM 上下文) + `shared_context` (结构化数据, UI 独立渲染)
- 三阶段 Supervisor: Planner → Dispatcher → Synthesizer (含模板降级)
- **用户反馈**: UI 内 👍/👎 按钮 → logs/feedback.jsonl
- **自主审计**: 每周一 9:07 自动运行 `scripts/audit.py` + 8 模式扫描
- **CI/CD**: `.github/workflows/ci.yml` (push/PR) + `.github/workflows/weekly-audit.yml` (定时)
- **文档**: `docs/AUTONOMOUS.md` 自主迭代系统说明
