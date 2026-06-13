"""MCP tool definitions — wrapped as Model Context Protocol tools for LLM consumption.

Provides 8 tools:
    - validate_smiles: Validate SMILES strings
    - calculate_properties: Compute 8 molecular descriptors
    - check_lipinski: Check Lipinski's Rule of Five
    - predict_ph_stability: Predict stability at a specific pH
    - predict_ph_stability_all_phases: Predict across all physiological pH phases
    - search_linker_scaffolds: Search known ADC linker scaffolds
    - design_linker: Design ADC linker candidates
    - search_literature: Search Europe PMC for ADC-related papers

Note: check_toxicity (PAINS/Brenk) is available via the LangGraph agent but not
yet registered as a standalone MCP tool.

Usage:
    from adc_linker_agent.mcp_tools.server import mcp
    mcp.run(transport="stdio")
"""

from adc_linker_agent.mcp_tools.server import main, mcp

__all__ = ["mcp", "main"]
