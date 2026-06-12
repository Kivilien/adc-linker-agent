"""
MCP Server —— ADC Linker Agent 工具服务器

这是整个 MCP 协议服务的主入口。FastMCP 自动处理:
  - JSON-RPC 消息解析和路由
  - stdio 传输（Claude Desktop / mcp-cli 标准连接方式）
  - 工具发现（tools/list 请求 → 自动返回所有注册工具的 schema）

启动方式:
  python -m adc_linker_agent.mcp_tools.server

设计原则:
  - server.py 只做"注册"——把所有工具函数挂到 FastMCP 实例上
  - 工具实现在各自的 tool_*.py 文件中，方便单独测试
  - 单个 FastMCP 实例 = 单一 MCP 服务 = 所有工具共享同一传输

参考:
  - MCP 规范: https://modelcontextprotocol.io/
  - FastMCP 文档: https://github.com/jlowin/fastmcp
"""

from mcp.server.fastmcp import FastMCP

from .tool_design import design_linker as _design_linker
from .tool_linker import search_linker_scaffolds as _search_linker_scaffolds
from .tool_ph import predict_ph_stability as _predict_ph_stability
from .tool_ph import predict_ph_stability_all_phases as _predict_ph_stability_all_phases
from .tool_property import calculate_properties as _calculate_properties
from .tool_property import check_lipinski as _check_lipinski
from .tool_validate import validate_smiles as _validate_smiles

# ─── 创建 MCP 服务器实例 ───
mcp = FastMCP(
    name="ADC Linker Agent — Molecular Tools",
    instructions=(
        "You are an ADC (Antibody-Drug Conjugate) linker design assistant. "
        "Use these tools to validate SMILES strings, calculate molecular properties, "
        "predict pH-dependent stability, search known linker scaffolds, "
        "and design linker candidates. "
        "ALWAYS call validate_smiles before other tools when the user provides a SMILES. "
        "When evaluating linker candidates, check both properties AND pH stability "
        "across all physiological phases (blood → lysosome)."
    ),
)

# ─── 注册所有 MCP 工具 ───
# mcp.tool() 不带参数 → 使用函数自身的 name/docstring 作为工具的 name/description

mcp.tool()(_validate_smiles)
mcp.tool()(_calculate_properties)
mcp.tool()(_check_lipinski)
mcp.tool()(_predict_ph_stability)
mcp.tool()(_predict_ph_stability_all_phases)
mcp.tool()(_search_linker_scaffolds)
mcp.tool()(_design_linker)


# ─── 入口点 ───

def main():
    """运行 MCP 服务器（stdio 传输模式）"""
    print(
        "ADC Linker Agent — MCP Server starting on stdio...",
        file=__import__("sys").stderr,
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
