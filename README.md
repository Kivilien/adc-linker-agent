# 🧬 ADC 连接子智能设计 AI Agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/badge/lint-ruff-green.svg)](https://github.com/astral-sh/ruff)
[![Tests](https://img.shields.io/badge/tests-255%20passed-brightgreen.svg)](.)
[![Version](https://img.shields.io/badge/version-1.0.0-orange.svg)](.)

Enterprise-grade Multi-Agent AI system for Antibody-Drug Conjugate (ADC) linker design.
Built with LangGraph, MCP, and RDKit. Case study: Suzhou Yili Bio-Pharmaceutical.

---

## 📖 Overview

ADC Linker Agent helps medicinal chemists design ADC linkers through natural language interaction.
Input a query like _"Design a linker that cleaves at pH 5.5 to release camptothecin"_,
and the Multi-Agent system returns ranked candidates with full property analysis.

### What makes a good ADC linker?

| Criterion | Requirement | Why |
|-----------|------------|-----|
| Blood stability | Stable at pH 7.4 | Linker must NOT release toxin in bloodstream |
| Lysosome lability | Cleaves at pH 5.0-5.5 | Linker MUST release toxin inside cancer cells |
| Drug-likeness | QED > 0.5, LogP 1-3 | Good pharmacokinetics |
| Synthesis | SAS < 4 | Cost-effective GMP production |

---

## 🏗 Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Streamlit UI / FastAPI                     │
├──────────────────────────────────────────────────────────────┤
│                   Multi-Agent Supervisor                      │
│  ┌─────────────┐  ┌──────────┐  ┌──────────────────────┐    │
│  │ PropertyAgent│  │ PHAgent  │  │ LinkerDesignAgent    │    │
│  │ (3 tools)    │  │ (2 tools)│  │ (7 tools, all)       │    │
│  └──────┬───────┘  └────┬─────┘  └──────────┬───────────┘    │
│         └────────────────┼──────────────────┘                │
├──────────────────────────┼───────────────────────────────────┤
│                     MCP Server (7 tools)                      │
├──────────────────────────┼───────────────────────────────────┤
│                Domain Layer (RDKit)                           │
│  MolPropertyCalculator · PhSimulator · LinkerDesigner        │
└──────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Chemoinformatics | RDKit 2022.9 | Molecular property calculation |
| Tool Protocol | MCP (Model Context Protocol) | LLM ↔ Tool standard interface |
| Agent Orchestration | LangGraph 1.2 | Stateful multi-agent graph |
| LLM | Claude (Anthropic) | Agent reasoning engine |
| API | FastAPI | REST endpoints |
| UI | Streamlit | Chat interface |
| Testing | pytest 255 tests | Unit + integration |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

### Install

```bash
git clone <repo-url> adc-linker-agent
cd adc-linker-agent
uv sync                          # Install all dependencies
```

### Configure

Create `.env` in project root:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

### Run

**Streamlit Chat UI** (recommended):
```bash
streamlit run adc_linker_agent/ui/app.py
# → http://localhost:8501
```

**FastAPI Server**:
```bash
python -m adc_linker_agent.api.server
# → http://localhost:8000/docs
```

**MCP Server** (for Claude Desktop / mcp-cli):
```bash
python -m adc_linker_agent.mcp_tools.server
```

**Tests**:
```bash
pytest tests/ -v                    # 255 tests
pytest tests/ --cov=adc_linker_agent  # with coverage
```

---

## 🛠 Tools

| # | Tool | Description |
|---|------|------------|
| 1 | `validate_smiles` | Validate SMILES strings, return canonical form + formula |
| 2 | `calculate_properties` | 8 descriptors (LogP, QED, SAS, TPSA, MW, HBD, HBA, rot. bonds) |
| 3 | `check_lipinski` | Lipinski Rule of Five for oral drug-likeness |
| 4 | `predict_ph_stability` | pH-dependent stability at a specific pH |
| 5 | `predict_ph_stability_all_phases` | Full ADC delivery path (blood→tumor→endosome→lysosome) |
| 6 | `search_linker_scaffolds` | Query 17-linker scaffold database |
| 7 | `design_linker` | Optimization loop: filter→evaluate→score→rank |

---

## 📂 Project Structure

```
adc-linker-agent/
├── adc_linker_agent/
│   ├── domain/              # Core domain logic
│   │   ├── molecule.py      # Pydantic models
│   │   ├── properties.py    # 8 molecular descriptors
│   │   ├── ph_simulator.py  # pH stability rule engine
│   │   └── linker_designer.py  # Design optimization loop
│   ├── mcp_tools/           # MCP protocol tools (7)
│   │   ├── server.py        # FastMCP entry point
│   │   └── tool_*.py        # Individual tool definitions
│   ├── agent/               # LangGraph agent system
│   │   ├── state.py         # AgentState + MultiAgentState
│   │   ├── tools.py         # LangChain @tool wrappers
│   │   ├── specialists.py   # 3 specialist agents
│   │   └── graph.py         # Single & Multi-agent graphs
│   ├── api/                 # FastAPI REST API
│   └── ui/                  # Streamlit chat UI
├── data/
│   └── linker_scaffolds.csv # 17 linker scaffolds
├── tests/                   # 255 tests across 6 layers
├── notebooks/               # Jupyter teaching notebooks
└── pyproject.toml
```

---

## 🎓 Learning Path

| Week | Topic | Tests |
|------|-------|-------|
| 1 | ADC basics + project scaffold | 25 |
| 2 | RDKit molecular properties + pH simulator | 57 |
| 3 | MCP protocol tool server | 107 |
| 4 | LangGraph single agent (ReAct) | 147 |
| 5 | Multi-agent supervisor + 3 specialists | 187 |
| 6 | Streamlit UI + FastAPI | 219 |
| 7 | pH-aware linker design engine | 255 |
| 8 | Polish, ruff clean, v1.0.0 | 255 |

---

## 📊 Demo Queries

```
# Property calculation
计算阿司匹林的所有分子性质

# pH stability analysis
检查腙键连接子在血液和溶酶体中的稳定性

# Scaffold search
搜索所有 pH 敏感的 ADC 连接子骨架

# Linker design (optimization loop)
设计一个在 pH 5.5 裂解释放喜树碱的连接子

# Comprehensive task
我需要一个 LogP 1-3、血液稳定、溶酶体裂解的连接子
```

---

## 🔬 Case Study: Yili Bio-Pharmaceutical

Inspired by Suzhou Yili Bio's TMALIN® platform:
- **Tumor Microenvironment Activation**: Dual cleavage at pH 6.5 + pH 5.0
- **High DAR**: Supports DAR=8 with high homogeneity
- **Potent Payload**: Toxin activity 5-10× higher than Dxd

Our TMALIN-like dual-cleavage linker scaffold models this approach.

---

*Built by a CS sophomore learning AI agents + medicinal chemistry*
