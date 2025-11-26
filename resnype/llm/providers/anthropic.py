"""Anthropic (Claude) provider implementation."""

import logging
from typing import Optional

from resnype.llm.base import LLMProvider, LLMResponse, Message, ToolCall

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """Provider for Anthropic Claude models."""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package required. Run: uv add anthropic")

        self.client = anthropic.AsyncAnthropic()
        self.model = model

    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        system: Optional[str] = None,
    ) -> LLMResponse:
        """Send a chat completion request to Claude."""
        # Convert messages to Anthropic format
        api_messages = []
        for msg in messages:
            if msg.role == "system":
                continue  # System handled separately

            if msg.role == "tool":
                # Tool results in Anthropic format
                api_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id,
                                "content": msg.content,
                            }
                        ],
                    }
                )
            elif msg.tool_calls:
                # Assistant message with tool calls
                content = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                api_messages.append({"role": "assistant", "content": content})
            else:
                api_messages.append({"role": msg.role, "content": msg.content})

        # Build request
        kwargs = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": api_messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self.format_tools(tools)

        logger.debug(
            f"Anthropic request: model={self.model}, messages={len(api_messages)}"
        )

        response = await self.client.messages.create(**kwargs)

        # Parse response
        tool_calls = []
        content = None

        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )
            elif block.type == "text":
                content = block.text

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason="tool_use" if tool_calls else "stop",
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )

    def format_tools(self, tools: list[dict]) -> list[dict]:
        """Anthropic uses input_schema format (our unified format)."""
        # Our unified format matches Anthropic, so just return as-is
        return tools
