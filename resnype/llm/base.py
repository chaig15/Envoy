"""Abstract base classes for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolCall:
    """Unified tool call representation across all providers."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Unified response format across all providers."""

    content: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"  # "stop", "tool_use", "length"
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class Message:
    """Unified message format for conversations."""

    role: str  # "user", "assistant", "system", "tool"
    content: str
    tool_call_id: Optional[str] = None  # For tool results
    tool_calls: Optional[list[ToolCall]] = (
        None  # For assistant messages with tool calls
    )


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        system: Optional[str] = None,
    ) -> LLMResponse:
        """
        Send a chat completion request.

        Args:
            messages: Conversation history
            tools: Optional list of tool definitions
            system: Optional system prompt

        Returns:
            LLMResponse with content and/or tool calls
        """
        pass

    @abstractmethod
    def format_tools(self, tools: list[dict]) -> list[dict]:
        """
        Convert unified tool schema to provider-specific format.

        Args:
            tools: Tools in unified format (Anthropic-style with input_schema)

        Returns:
            Tools in provider-specific format
        """
        pass
