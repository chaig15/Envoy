"""LLM provider implementations."""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resnype.llm.base import LLMProvider


def get_provider(
    provider_name: str | None = None,
    model: str | None = None,
) -> "LLMProvider":
    """
    Get an LLM provider instance based on configuration.

    Args:
        provider_name: Override provider from config. Options:
            - "anthropic": Claude models
            - "openai": GPT models (chat completions)
            - "openai_responses": GPT models (newer Responses API)
            - "ollama": Local Ollama models
            - "openrouter": OpenRouter API (access to 100+ models)
            - "vllm": Local vLLM server
        model: Override model from config

    Returns:
        Configured LLMProvider instance
    """
    from resnype.config import get_settings

    settings = get_settings()

    # Use passed values or fall back to config
    provider = provider_name or settings.llm_provider
    model_name = model or settings.llm_model

    if provider == "anthropic":
        from resnype.llm.providers.anthropic import AnthropicProvider

        return AnthropicProvider(model=model_name or "claude-sonnet-4-20250514")

    elif provider == "openai":
        from resnype.llm.providers.openai import OpenAIProvider

        return OpenAIProvider(model=model_name or "gpt-4o")

    elif provider == "openai_responses":
        from resnype.llm.providers.openai_responses import OpenAIResponsesProvider

        return OpenAIResponsesProvider(model=model_name or "gpt-4o")

    elif provider == "ollama":
        from resnype.llm.providers.openai import OpenAIProvider

        return OpenAIProvider(
            model=model_name or "llama3.1:8b",
            base_url="http://localhost:11434/v1",
            api_key="ollama",  # Ollama ignores this but client requires it
        )

    elif provider == "openrouter":
        from resnype.llm.providers.openai import OpenAIProvider

        return OpenAIProvider(
            model=model_name or "anthropic/claude-3.5-sonnet",
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
        )

    elif provider == "vllm":
        from resnype.llm.providers.openai import OpenAIProvider

        return OpenAIProvider(
            model=model_name or "meta-llama/Llama-3.1-8B-Instruct",
            base_url=os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1"),
            api_key="dummy",
        )

    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            "Options: anthropic, openai, openai_responses, ollama, openrouter, vllm"
        )
