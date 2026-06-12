"""FastAPI REST API — exposes agent capabilities over HTTP.

Endpoints:
    POST /agent/query  — Send query to agent
    GET  /agent/health — Health check
    GET  /agent/tools  — List available tools

Quick start:
    python -m adc_linker_agent.api.server
    # → http://localhost:8000/docs
"""

from adc_linker_agent.api.server import app, main

__all__ = ["app", "main"]
