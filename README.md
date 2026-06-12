# ADC Linker Intelligent Design Agent

AI-powered multi-agent system for antibody-drug conjugate (ADC) linker design.

## Overview

This project builds an enterprise-grade AI agent platform that assists medicinal chemists
in designing linkers for antibody-drug conjugates — the "fuse" that controls when and where
a cytotoxic payload is released inside cancer cells.

Built with MCP (Model Context Protocol) + LangGraph + Claude, the system integrates
cheminformatics tools (RDKit) with a multi-agent architecture (Supervisor + Specialists)
to provide natural-language-driven molecular design capabilities.

## Quick Start

```bash
# Prerequisites: Python 3.11+, uv
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"

# Copy and configure environment
cp .env.template .env
# Edit .env with your ANTHROPIC_API_KEY
```

## Project Structure

```
adc_linker_agent/
├── domain/       # Domain models & molecular property calculation
├── mcp_tools/     # MCP protocol tool definitions
├── agent/         # LangGraph multi-agent orchestration
├── api/           # FastAPI REST endpoints
├── ui/            # Streamlit chat interface
└── utils/         # Configuration & logging
```

## Status

- [x] Week 1: Project skeleton + domain models
- [ ] Week 2: RDKit property calculation
- [ ] Week 3: MCP tool server
- [ ] Week 4: Single-agent system
- [ ] Week 5: Multi-agent architecture
- [ ] Week 6: Web UI + API
- [ ] Week 7: pH-aware linker design
- [ ] Week 8: Polish & demo

## License

MIT
