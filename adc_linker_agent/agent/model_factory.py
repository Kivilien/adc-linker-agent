"""
LLM 模型工厂

统一创建 Anthropic 或 OpenAI 兼容（DeepSeek）的 LLM 实例。
处理 DeepSeek 不支持 response_format json_schema 的兼容性问题。

使用方式:
    from adc_linker_agent.agent.model_factory import create_model

    model = create_model(temperature=0.2)
    model_with_tools = create_model(tools=[...])
    structured_model = create_model(output_schema=MyPydanticModel)
    # 无论哪种 provider，统一调用: model.invoke(messages)
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import PydanticOutputParser

from adc_linker_agent.utils.config import get_config


class _StructuredOutputWrapper:
    """
    包装器：将 (prompt → model → parser) chain 包装为
    与普通 ChatModel 兼容的 invoke(messages) 接口。

    用于 DeepSeek（不支持原生 structured output）。
    """

    def __init__(self, base_model: BaseChatModel, output_schema: type):
        self._model = base_model
        self._parser = PydanticOutputParser(pydantic_object=output_schema)
        self._format_instructions = self._parser.get_format_instructions()

    def invoke(self, messages: list) -> object:
        """模拟 ChatModel.invoke(messages) 接口"""
        # 在最后一条 system message 后追加格式说明，
        # 或如果没有 system message，插入一条
        modified = list(messages)

        # 找到最后一个 system message 并追加格式说明
        last_system_idx = -1
        for i, m in enumerate(modified):
            if isinstance(m, SystemMessage):
                last_system_idx = i

        format_msg = (
            f"\n\nYou MUST respond with ONLY a valid JSON object. "
            f"No markdown, no explanation, no extra text.\n"
            f"Format:\n{self._format_instructions}"
        )

        if last_system_idx >= 0:
            modified[last_system_idx] = SystemMessage(
                content=str(modified[last_system_idx].content) + format_msg
            )
        else:
            modified.insert(0, SystemMessage(content=format_msg))

        response = self._model.invoke(modified)
        return self._parser.invoke(response)


def create_model(
    temperature: float = 0.2,
    max_tokens: int = 4096,
    tools: list | None = None,
    output_schema: type | None = None,
):
    """
    创建 LLM 模型实例。返回的对象统一支持 .invoke(messages) 接口。

    自动检测 LLM_PROVIDER:
      - "deepseek" → ChatOpenAI（OpenAI 兼容 API）
      - "anthropic" → ChatAnthropic

    Args:
        temperature: 温度参数
        max_tokens: 最大输出 token 数
        tools: 可选的工具列表
        output_schema: 可选的 Pydantic 模型（用于结构化输出）

    Returns:
        ChatModel 或 compatible wrapper，统一 .invoke(messages) 接口
    """
    config = get_config()

    if config.llm_provider == "deepseek":
        from langchain_openai import ChatOpenAI

        base_model = ChatOpenAI(
            model=config.llm_model,
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        from langchain_anthropic import ChatAnthropic

        base_model = ChatAnthropic(
            model=config.llm_model,
            api_key=config.anthropic_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # 绑定工具
    if tools:
        base_model = base_model.bind_tools(tools)

    # 结构化输出
    if output_schema:
        if config.llm_provider == "deepseek":
            # DeepSeek 不支持 response_format json_schema
            # 使用 PydanticOutputParser + prompt 替代
            return _StructuredOutputWrapper(base_model, output_schema)
        else:
            # Anthropic 支持原生 structured output
            base_model = base_model.with_structured_output(output_schema)

    return base_model
