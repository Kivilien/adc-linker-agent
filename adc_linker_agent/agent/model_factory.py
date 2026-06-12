"""
LLM 模型工厂

统一创建 Anthropic 或 OpenAI 兼容（DeepSeek）的 LLM 实例。
上游代码无需关心具体提供商，只需调用 create_model()。

使用方式:
    from adc_linker_agent.agent.model_factory import create_model

    model = create_model(temperature=0.2)
    model_with_tools = create_model(tools=[...])
    structured_model = create_model(output_schema=MyPydanticModel)
"""


from adc_linker_agent.utils.config import get_config


def create_model(
    temperature: float = 0.2,
    max_tokens: int = 4096,
    tools: list | None = None,
    output_schema: type | None = None,
):
    """
    创建 LLM 模型实例。

    自动检测配置中的 LLM_PROVIDER:
      - "deepseek" → ChatOpenAI（OpenAI 兼容 API）
      - "anthropic" → ChatAnthropic

    Args:
        temperature: 温度参数（0-1，越低越确定性）
        max_tokens: 最大输出 token 数
        tools: 可选的工具列表（调用 bind_tools）
        output_schema: 可选的 Pydantic 模型（调用 with_structured_output）

    Returns:
        BaseChatModel 实例（已绑定工具/结构化输出）
    """
    config = get_config()

    if config.llm_provider == "deepseek":
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            model=config.llm_model,
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        from langchain_anthropic import ChatAnthropic

        model = ChatAnthropic(
            model=config.llm_model,
            api_key=config.anthropic_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # 绑定工具（Tool calling）
    if tools:
        model = model.bind_tools(tools)

    # 绑定结构化输出（用于 Supervisor 路由）
    if output_schema:
        model = model.with_structured_output(output_schema)

    return model
