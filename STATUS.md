# ADC Linker Agent — 项目状态

## Phase 2: Demo → 可信研究工具

### Week 4 (2026-06-13) — 盲评反馈补全 ✅

#### 4.1 PhSimulator 规则扩展（7→14 条）
- 新增 `mechanism_type` 字段：`pH_sensitive` | `enzymatic` | `redox`
- 新增 `trigger_description` + `enzyme_name` 字段（人类可读 + 酶标注）
- **酶催化**（3 条）：val_dipeptide (Cathepsin B)、glucuronide (β-glucuronidase)、beta_lactam (β-lactamase)
- **氧化还原**（2 条）：disulfide (GSH 还原)、azo (偶氮还原酶)
- **酸敏感扩展**（2 条）：orthoester (超快水解)、phosphoramidate (P-N 断裂)
- `_generate_recommendation()` 按机制分类输出：🔴 酸敏感 / 🟢 酶催化 / 🟡 氧化还原
- `_is_covered_by_library()` 新增 disulfide 覆盖映射 + 模糊匹配
- `data/ph_labile_groups.yaml` 新增 `mechanism_type` + 所有新规则
- +18 测试（4 类 8 场景 + 混合机制 + 规则库规模验证）

#### 4.2 Specialist 重试 + 上下文管理
- `specialists.py` 新增容错基础设施：
  - `_call_model_with_retry()` — LLM 调用指数退避重试（2s→4s→8s，最多 3 次）
  - `_execute_tool_with_retry()` — 工具执行重试，区分瞬时错误（网络/超时/限流 重试）和永久错误（无效 SMILES 不重试）
  - `_trim_context()` — token 超过 100k 时裁剪保留 system + 最后 8 条消息
  - `_estimate_tokens()` — 粗略 token 估算（2 chars ≈ 1 token）
- `create_specialist_node()` 循环内集成：LLM 重试 + 上下文裁剪 + 失败降级返回
- `_execute_tool_calls` 改用 `_execute_tool_with_retry`

#### 4.3 tool_design.py DRY 重构
- 消除 `result.candidates` 二次手动遍历
- `generate_report()` 单次遍历后，从 `report.detailed_cards` + `report.candidates` 派生 `candidates_data`
- Top-3 候选人完整数据（detailed_card），超出部分基础数据（CandidateSummary）
- `_build_detailed_card()` 补充 `ph_stability.summary` 字段

**质量门禁**: ruff 零错误 | pytest 323 passed (305→323, +18)

---

### 会话交接 — 2026-06-13 16:00
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 状态: Week 4 完成 + Prompt 风格 + 历史消息修复 ✅
- 改动:
  - 4 个 Specialist Prompt 重写：Few-shot 示例替代文字指令，去除装饰、表格仅用于对比、异常才解释
  - app.py 历史消息注入移除：MemorySaver 通过 thread_id 维护上下文，旧消息重复注入导致批量误处理
  - 调研: ACS Cent. Sci. 2025 最佳实践 + ChemCrow ReAct 模式
- 当前服务: FastAPI 8000 ✅ | Streamlit 8501 ✅
- 待续: 用户平台实测反馈

---

### Week 1 (2026-06-12) — 安全加固 + 可见度提升 ✅

#### 1.1 毒性检测 PAINS/Brenk
- `domain/properties.py` — 新增 `check_toxicity_alerts()` (PAINS 480条 + Brenk 105条，RDKit FilterCatalog)
- `agent/tools.py` — 新增 `check_toxicity` tool (ALL_TOOLS 8→9)
- `agent/specialists.py` — TOOL_MAP + PROPERTY_TOOLS + LINKER prompt 整合毒性检查
- `domain/linker_designer.py` — Candidate 新增 toxicity_alerts/has_toxicity_alerts/risk_flags；评分毒性惩罚 ×0.4
- `ui/components.py` — 新增 `render_toxicity_alerts()` + `render_risk_flags()`

#### 1.2 医学免责声明 + 输入验证
- 新增 `utils/validators.py` — SMILES 上限 2048、查询上限 10000、恶意重复检测、MEDICAL_DISCLAIMER
- `ui/app.py` — 每次助手回复底部渲染免责声明
- `api/models.py` — AgentQueryResponse 新增 disclaimer 字段
- `api/routes.py` — 内存速率限制(30 req/60s) + 输入校验

#### 1.3 化学结构式渲染
- `domain/molecule.py` — 新增 `render_molecule_image()` (PNG) + `render_molecule_svg()` (降级)
- `ui/components.py` — 新增 `render_molecule_structure()`

#### 1.4 修复错误吞没
- `domain/linker_designer.py` — `except Exception: continue` → 记录到 `DesignResult.failed_scaffolds`

#### 1.5 工具数适配
- 测试更新: test_tools.py, test_specialists.py, test_server.py

**质量门禁**: ruff 零错误 | pytest 259 passed

---

### 下一步: Phase 2 全部完成 ✅

---

### Week 3 (2026-06-12) — Streaming + 打磨 ✅

#### 3.1 LangGraph Streaming
- `ui/app.py` — `graph.invoke()` → `graph.astream_events()` 流式执行
  - 新增 `_stream_agent_execution()` 异步函数：捕获 Agent 节点转换 + 工具执行 + LLM token 流
  - 新增 `_AGENT_LABELS` 映射：5 个 Agent 的中文状态标签
  - `asyncio.run()` 驱动流式循环，`st.empty()` placeholder 实时更新状态
- `ui/components.py` — 新增 `render_streaming_status()` 组件
  - 接受 placeholder + agent_name + tool_name，动态更新状态指示器
- 可行性测试: DeepSeek API + LangGraph `.astream_events()` — `on_chat_model_stream` / `on_tool_start/end` 全部正常
- 工具调用追踪：`on_tool_start` 记录 input → `on_tool_end` 匹配 run_id 获取 output
- `_report` 检测保留：从 tool_runs 中提取 `design_linker` 的 `_report` 数据

#### 3.2 集成测试 + 演示剧本
- 新增 `tests/test_integration/test_end_to_end.py` — 23 个测试（22 passed, 1 skipped）
- 3 个端到端场景：
  1. **Property + Toxicity Pipeline**: validate → calculate → lipinski → toxicity (6 tests)
  2. **Design → Report Pipeline**: DesignResult → DesignReport 全流程 (7 tests)
  3. **Multi-Agent Graph Structure**: 编译 + 节点 + 边 + 工具分配验证 (8 tests)
  4. **Literature**: 结构化结果验证 (2 tests, 1 skipped for network)
- `README.md` — 新增 3 个演示剧本（Property+Toxicity / Design+Report / Literature）
  - 更新技术栈表、项目结构、学习路径 (Week 9)
  - 测试数: 255→305, 版本: 1.0.0→1.1.0
- `CLAUDE.md` — 新增项目状态 + 关键架构决策
- `components.py` — 侧边栏测试数更新

#### 3.3 文档更新
- `STATUS.md` — 本文件，Week 3 完成记录

**质量门禁**: ruff 新增代码零错误 | pytest 305 passed (283→305, +22)

---

### 安全加固 (2026-06-12) — 盲评反馈后立即修复

#### Review Top 1&3 修复: API 认证 + 审计日志
- 新增 `utils/audit.py` — JSONL 审计日志模块
  - 记录: timestamp, client_ip, thread_id, query(截断200字符), status, elapsed_ms, tool_calls
  - 写入 `logs/audit.jsonl`，写入失败静默降级不阻塞请求
- 新增 `api/auth.py` — `verify_api_key` FastAPI 依赖
  - 检查 `X-API-Key` 请求头
  - 未配置 ADC_API_KEY → 开发模式（认证可选）
  - 已配置 ADC_API_KEY → 强制验证，不匹配返回 401
- `utils/config.py` — 新增 `api_key` + `audit_log_path` 配置项
- `api/routes.py` — `/query` 端点接入认证 + 审计日志
  - validation_error / rate_limited / error 状态也记录 audit
- `api/server.py` — CORS 硬朗: `allow_methods=["GET","POST"]`, `allow_headers=["Content-Type","X-API-Key"]`
- `.env.template` — 新增 `ADC_API_KEY` 配置说明
- `.gitignore` — 新增 `logs/` + `.streamlit_session.json`

**质量门禁**: ruff 新增代码零错误 | pytest 305 passed

---

### 会话交接 — 2026-06-12 23:30
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 状态: Phase 2 完成 + 安全加固 ✅
- 下一步: 用户平台测试

### 会话交接 — 2026-06-12 23:45
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 状态: UI 优化完成 ✅
- 改动:
  - 工具调用移至回复底部 + 合并折叠面板，不再打断阅读
  - LLM 输出清洗：去 Supervisor JSON 路由决策和 Agent 元消息
  - 结构化报告优先展示，LLM 分析放折叠区
- 待续: 用户平台实测反馈，Week 3 review 中提到的 PhSimulator 扩展

---

### Week 2 (2026-06-12) — 结构化报告 + 配置外部化 ✅

#### 2.1 结构化报告引擎
- 新增 `domain/report.py` — DesignReport + CandidateSummary 数据类，纯数据聚合
- `generate_report()` 将 DesignResult → 结构化 dict，包含: Header/对比表/Top-3详细卡片/对比分析/毒性汇总/警告
- 新增 `ui/components.py` — `render_design_report()` + `_render_candidate_card()` 渲染函数
- `ui/app.py` — 检测 `design_linker` 工具结果中的 `_report` 数据，切换结构化报告渲染
- `mcp_tools/tool_design.py` — return 中新增 `_report` 序列化数据
- 新增 `tests/test_domain/test_report.py` — 20 个测试（报告生成、性质状态、摘要数据类）

#### 2.2 PhLabileGroup YAML 外部化
- 新增 `data/ph_labile_groups.yaml` — 7 个 pH 敏感官能团从 Python 迁移到 YAML
- `domain/ph_simulator.py` — 新增 `load_labile_groups()` (YAML→降级内置列表) + `_builtin_labile_groups()` 降级函数
- `PhSimulator.__init__` 改为调用 `load_labile_groups()`，修复 `_is_covered_by_library` 从类方法→实例方法
- `utils/config.py` — 新增 `ph_labile_groups_path` 配置
- `pyproject.toml` — 新增 `PyYAML>=6.0` 依赖
- `PH_LABILE_GROUPS` 模块级变量保留向后兼容（自动调用 `load_labile_groups()`）

#### 2.3 评分权重可配置
- `domain/linker_designer.py` — `LinkerDesigner.__init__(weights=...)` 接受自定义权重 dict
- 新增 `DEFAULT_WEIGHTS` 类字典 + `_normalize_weights()` 静态方法（自动补齐+归一化）
- `_score_candidate` 改用 `self.weights` dict 而非类级属性
- `mcp_tools/tool_design.py` — `design_linker()` 新增 `weights` 参数
- `agent/tools.py` — `design_linker` tool 新增 `weights` 参数
- `tests/test_domain/test_linker_designer.py` — 新增 5 个自定义权重测试
- 保留类级别名 WEIGHT_* 向后兼容

**质量门禁**: ruff 新增代码零错误 | pytest 283 passed (259→283, +24)

---

### 会话交接 — 2026-06-12 22:15
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 状态: Week 2 完成，进入 Week 3

### 会话交接 — 2026-06-12 20:58
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-12 21:17
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-12 21:21
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-12 21:27
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-12 21:30
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 14:10
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 14:30
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 14:44
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 15:13
- 会话: a1066c3f-618
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 15:24
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 15:34
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 16:44
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 16:52
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 17:10
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 20:27
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 20:32
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 20:54
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 20:55
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 21:12
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 23:29
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-13 23:31
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 08:21
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 08:23
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 08:26
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 12:12
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 12:55
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 13:38
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 14:18
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 15:23
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 15:33
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 16:12
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 16:18
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 16:25
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 21:34
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 21:45
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 22:14
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 22:19
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 22:22
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 22:33
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-14 22:34
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-15 13:16
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-15 13:22
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-15 13:31
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-15 13:38
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常


### 会话交接 — 2026-06-15 13:50
- 会话: e364c630-fdf
- 工作目录: /Users/lushun/projects/adc-linker-agent
- 上下文状态: 正常
