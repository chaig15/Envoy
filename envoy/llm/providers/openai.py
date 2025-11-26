"""OpenAI provider implementation (also works for OpenAI-compatible APIs)."""

import json
import logging
from typing import Optional

from envoy.llm.base import LLMProvider, LLMResponse, Message, ToolCall

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """
    Provider for OpenAI models and OpenAI-compatible APIs.

    Works with:
    - OpenAI (GPT-4, GPT-4o, etc.)
    - Ollama (local)
    - vLLM (local)
    - OpenRouter (cloud)
    - LMStudio (local)
    - Any OpenAI-compatible endpoint
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("openai package required. Run: uv add openai")

        # Explicitly pass api_key to prevent fallback to OPENAI_API_KEY env var
        # If api_key is None and base_url is set, use empty string to force no fallback
        if base_url and not api_key:
            api_key = (
                ""  # Prevent fallback to OPENAI_API_KEY when using custom base_url
            )
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.base_url = base_url

    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        system: Optional[str] = None,
    ) -> LLMResponse:
        """Send a chat completion request."""
        # Convert messages to OpenAI format
        api_messages = []

        if system:
            api_messages.append({"role": "system", "content": system})

        for msg in messages:
            if msg.role == "system":
                continue  # Already handled above

            if msg.role == "tool":
                api_messages.append(
                    {
                        "role": "tool",
                        "content": msg.content,
                        "tool_call_id": msg.tool_call_id,
                    }
                )
            elif msg.tool_calls:
                # Assistant message with tool calls
                api_messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
            else:
                api_messages.append({"role": msg.role, "content": msg.content})

        # Build request
        kwargs = {
            "model": self.model,
            "messages": api_messages,
        }
        if tools:
            kwargs["tools"] = self.format_tools(tools)

        logger.debug(
            f"OpenAI request: model={self.model}, base_url={self.base_url}, messages={len(api_messages)}"
        )

        response = await self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        # Parse tool calls
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}
                    logger.warning(
                        f"Failed to parse tool arguments: {tc.function.arguments}"
                    )

                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=arguments,
                    )
                )

        return LLMResponse(
            content=choice.message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage={
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens
                if response.usage
                else 0,
            },
        )

    def format_tools(self, tools: list[dict]) -> list[dict]:
        """Convert unified schema to OpenAI function calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get(
                        "input_schema", {"type": "object", "properties": {}}
                    ),
                },
            }
            for tool in tools
        ]
