"""OpenAI Responses API provider (newer, recommended by OpenAI)."""

import logging
from typing import Optional

from envoy.llm.base import LLMProvider, LLMResponse, Message, ToolCall

logger = logging.getLogger(__name__)


class OpenAIResponsesProvider(LLMProvider):
    """
    Provider using OpenAI's newer Responses API.

    Benefits over Chat Completions:
    - Single API call (no polling)
    - Built-in tool execution loop
    - Streaming-first design
    - OpenAI's recommended path forward

    Limitations:
    - OpenAI only (no Ollama/OpenRouter compatibility)
    """

    def __init__(self, model: str = "gpt-4o"):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("openai package required. Run: uv add openai")

        self.client = AsyncOpenAI()
        self.model = model

    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        system: Optional[str] = None,
    ) -> LLMResponse:
        """Send a request using the Responses API."""
        # Build input from messages
        # Responses API takes a simpler input format
        input_parts = []

        if system:
            input_parts.append(f"System: {system}\n")

        for msg in messages:
            if msg.role == "user":
                input_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant" and msg.content:
                input_parts.append(f"Assistant: {msg.content}")
            elif msg.role == "tool":
                input_parts.append(f"Tool result ({msg.tool_call_id}): {msg.content}")

        input_text = "\n".join(input_parts)

        # Build request
        kwargs = {
            "model": self.model,
            "input": input_text,
        }

        if tools:
            kwargs["tools"] = self.format_tools(tools)

        logger.debug(f"OpenAI Responses request: model={self.model}")

        response = await self.client.responses.create(**kwargs)

        # Parse response
        tool_calls = []

        # Check for tool calls in the response
        if hasattr(response, "output") and response.output:
            for item in response.output:
                if hasattr(item, "type") and item.type == "function_call":
                    tool_calls.append(
                        ToolCall(
                            id=item.call_id,
                            name=item.name,
                            arguments=item.arguments
                            if isinstance(item.arguments, dict)
                            else {},
                        )
                    )

        # Get text content
        content = getattr(response, "output_text", None)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason="tool_use" if tool_calls else "stop",
            usage={
                "input_tokens": getattr(response.usage, "input_tokens", 0)
                if response.usage
                else 0,
                "output_tokens": getattr(response.usage, "output_tokens", 0)
                if response.usage
                else 0,
            },
        )

    def format_tools(self, tools: list[dict]) -> list[dict]:
        """Convert unified schema to Responses API format."""
        # Responses API uses function format similar to chat completions
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
