"""
MCP Server —— ADC Linker Agent 工具服务器

这是整个 MCP 协议服务的主入口。FastMCP 自动处理:
  - JSON-RPC 消息解析和路由
  - stdio 传输（Claude Desktop / mcp-cli 标准连接方式）
  - 工具发现（tools/list 请求 → 自动返回所有注册工具的 schema）

启动方式:
  python -m adc_linker_agent.mcp_tools.server

测试方式:
  echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \\
    python -m adc_linker_agent.mcp_tools.server

设计原则:
  - server.py 只做"注册"——把所有工具函数挂到 FastMCP 实例上
  - 工具实现在各自的 tool_*.py 文件中，方便单独测试
  - 单个 FastMCP 实例 = 单一 MCP 服务 = 所有工具共享同一传输

餐厅隐喻:
  这个文件是"餐厅总控台"——它知道后厨有哪些菜（工具），
  当客人（LLM）点菜时，把订单路由到正确的灶台（tool_*.py）。

参考:
  - MCP 规范: https://modelcontextprotocol.io/
  - FastMCP 文档: https://github.com/jlowin/fastmcp
"""

from mcp.server.fastmcp import FastMCP

# ─── 创建 MCP 服务器实例 ───
# name 参数对应 MCP 协议的 server.name 字段
# instructions 字段在 Claude Desktop 中作为系统提示的一部分
mcp = FastMCP(
    name="ADC Linker Agent — Molecular Tools",
    instructions=(
        "You are an ADC (Antibody-Drug Conjugate) linker design assistant. "
        "Use these tools to validate SMILES strings, calculate molecular properties, "
        "predict pH-dependent stability, and search known linker scaffolds. "
        "ALWAYS call validate_smiles before other tools when the user provides a SMILES. "
        "When evaluating linker candidates, check both properties AND pH stability "
        "across all physiological phases (blood → lysosome)."
    ),
)

# ─── 导入并注册所有 MCP 工具 ───
# mcp.tool() 不带参数 → 使用函数自身的 name/docstring 作为工具的 name/description
# FastMCP 自动从 type hints 提取参数的 JSON Schema

from .tool_validate import validate_smiles as _validate_smiles
from .tool_property import calculate_properties as _calculate_properties
from .tool_property import check_lipinski as _check_lipinski
from .tool_ph import predict_ph_stability as _predict_ph_stability
from .tool_ph import predict_ph_stability_all_phases as _predict_ph_stability_all_phases
from .tool_linker import search_linker_scaffolds as _search_linker_scaffolds
from .tool_design import design_linker as _design_linker

# 注册：每个工具函数被包装为 MCP Tool
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
    print("ADC Linker Agent — MCP Server starting on stdio...", file=__import__("sys").stderr)
    print("Registered tools: validate_smiles, calculate_properties, check_lipinski, "
          "predict_ph_stability, predict_ph_stability_all_phases, search_linker_scaffolds",
          file=__import__("sys").stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
