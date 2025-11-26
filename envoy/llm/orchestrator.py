"""LLM orchestrator that handles natural language interactions."""

import logging
from datetime import date, time, timedelta
from typing import Any, Optional

from envoy.db.models import User
from envoy.db.queries import ConversationQueries, SnipeQueries, WatchQueries
from envoy.llm.base import LLMProvider, LLMResponse, Message, ToolCall
from envoy.llm.providers import get_provider
from envoy.llm.tools import SYSTEM_PROMPT, TOOLS
from envoy.resy import ResyClient

logger = logging.getLogger(__name__)

# Max conversation history to keep per user
MAX_HISTORY = 20


class LLMOrchestrator:
    """
    Orchestrates LLM interactions with tool calling.

    Handles:
    - Natural language understanding
    - Tool execution
    - Conversation memory (persisted to DB)
    - Multi-turn interactions
    """

    def __init__(self, provider: Optional[LLMProvider] = None):
        self.provider = provider or get_provider()

    @staticmethod
    def _serialize_messages(messages: list[Message]) -> list[dict]:
        """Convert Message objects to JSON-serializable dicts."""
        result = []
        for msg in messages:
            data = {
                "role": msg.role,
                "content": msg.content,
            }
            if msg.tool_call_id:
                data["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                data["tool_calls"] = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in msg.tool_calls
                ]
            result.append(data)
        return result

    @staticmethod
    def _deserialize_messages(data: list[dict]) -> list[Message]:
        """Convert JSON dicts back to Message objects."""
        result = []
        for item in data:
            tool_calls = None
            if item.get("tool_calls"):
                tool_calls = [
                    ToolCall(
                        id=tc["id"],
                        name=tc["name"],
                        arguments=tc["arguments"],
                    )
                    for tc in item["tool_calls"]
                ]
            result.append(
                Message(
                    role=item["role"],
                    content=item["content"],
                    tool_call_id=item.get("tool_call_id"),
                    tool_calls=tool_calls,
                )
            )
        return result

    async def handle_message(
        self,
        telegram_id: int,
        user_message: str,
        user: User,
    ) -> str:
        """
        Process a natural language message and return a response.

        Args:
            telegram_id: User's Telegram ID
            user_message: The message text
            user: User model with auth info

        Returns:
            Response text to send back
        """
        # Load conversation history from DB
        history_data = await ConversationQueries.load(telegram_id)
        history = self._deserialize_messages(history_data)

        # Add user message
        history.append(Message(role="user", content=user_message))

        try:
            # Send to LLM
            response = await self.provider.chat(
                messages=history[-MAX_HISTORY:],
                tools=TOOLS,
                system=SYSTEM_PROMPT,
            )

            logger.debug(
                f"LLM response: finish_reason={response.finish_reason}, "
                f"tool_calls={len(response.tool_calls)}, "
                f"usage={response.usage}"
            )

            # Handle tool calls if any
            if response.tool_calls:
                # Add assistant message with tool calls to history
                history.append(
                    Message(
                        role="assistant",
                        content=response.content or "",
                        tool_calls=response.tool_calls,
                    )
                )

                # Execute tools and collect results
                tool_results = []
                for tool_call in response.tool_calls:
                    result = await self._execute_tool(
                        tool_call.name,
                        tool_call.arguments,
                        user,
                        telegram_id,
                    )
                    tool_results.append((tool_call, result))

                    # Add tool result to history
                    history.append(
                        Message(
                            role="tool",
                            content=str(result),
                            tool_call_id=tool_call.id,
                        )
                    )

                # Get final response after tool execution
                final_response = await self.provider.chat(
                    messages=history[-MAX_HISTORY:],
                    tools=TOOLS,
                    system=SYSTEM_PROMPT,
                )

                # Add final assistant response to history
                final_text = final_response.content or "Done!"
                history.append(Message(role="assistant", content=final_text))

            else:
                # No tool calls, just a text response
                final_text = response.content or "I'm not sure how to help with that."
                history.append(Message(role="assistant", content=final_text))

            # Save history to DB (keep last MAX_HISTORY messages)
            trimmed_history = history[-MAX_HISTORY:]
            model_name = getattr(self.provider, "model", None)
            await ConversationQueries.save(
                telegram_id,
                self._serialize_messages(trimmed_history),
                model=model_name,
            )

            return final_text

        except Exception as e:
            logger.exception(f"LLM orchestrator error: {e}")
            return f"Sorry, something went wrong: {str(e)}"

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        user: User,
        telegram_id: int,
    ) -> str:
        """
        Execute a tool and return the result as a string.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            user: User model
            telegram_id: User's Telegram ID

        Returns:
            Result string to feed back to LLM
        """
        logger.info(f"Executing tool: {tool_name} with args: {arguments}")

        try:
            if tool_name == "search_restaurant":
                return await self._search_restaurant(arguments["query"])

            elif tool_name == "create_snipe":
                return await self._create_snipe(user, arguments)

            elif tool_name == "create_watch":
                return await self._create_watch(user, arguments)

            elif tool_name == "list_snipes":
                return await self._list_snipes(telegram_id)

            elif tool_name == "list_watches":
                return await self._list_watches(telegram_id)

            elif tool_name == "cancel_snipe":
                return await self._cancel_snipe(arguments["snipe_id"], telegram_id)

            elif tool_name == "cancel_watch":
                return await self._cancel_watch(arguments["watch_id"], telegram_id)

            else:
                return f"Unknown tool: {tool_name}"

        except Exception as e:
            logger.exception(f"Tool execution error: {e}")
            return f"Error executing {tool_name}: {str(e)}"

    async def _search_restaurant(self, query: str) -> str:
        """Search for restaurants."""
        client = ResyClient()
        try:
            venues = await client.search_venues(query, limit=5)

            if not venues:
                return f"No restaurants found for '{query}'"

            results = []
            for v in venues:
                results.append(
                    f"- {v.name} (ID: {v.id}): {v.neighborhood or 'Unknown area'}, "
                    f"{v.cuisine or 'Restaurant'}, ${v.price_range or '?'} price range"
                )

            return f"Found {len(venues)} restaurants:\n" + "\n".join(results)

        finally:
            await client.close()

    async def _create_snipe(self, user: User, args: dict) -> str:
        """Create a snipe."""
        target_date = date.fromisoformat(args["target_date"])
        days_advance = args["days_advance"]
        release_date = target_date - timedelta(days=days_advance)

        # Parse release time
        release_time_str = args.get("release_time", "09:00")
        try:
            hour, minute = map(int, release_time_str.split(":"))
            release_time_obj = time(hour, minute)
        except (ValueError, AttributeError):
            release_time_obj = time(9, 0)

        # Check release date is in the future
        if release_date < date.today():
            return (
                f"Release date {release_date} has already passed. Cannot create snipe."
            )

        snipe = await SnipeQueries.create(
            user_id=user.id,
            venue_id=args["venue_id"],
            venue_name=args["venue_name"],
            target_date=target_date,
            release_date=release_date,
            party_size=args["party_size"],
            release_time=release_time_obj,
        )

        return (
            f"Snipe created successfully!\n"
            f"- Venue: {snipe.venue_name}\n"
            f"- Target date: {snipe.target_date}\n"
            f"- Party size: {snipe.party_size}\n"
            f"- Snipe runs: {snipe.release_date} at {release_time_obj.strftime('%H:%M')} EST"
        )

    async def _create_watch(self, user: User, args: dict) -> str:
        """Create a watch."""
        watch_date = date.fromisoformat(args["date"])

        # Map time preference to actual times
        time_pref = args.get("time_preference", "any")
        time_earliest = None
        time_latest = None

        if time_pref == "early":
            time_earliest = time(17, 0)
            time_latest = time(18, 30)
        elif time_pref == "prime":
            time_earliest = time(19, 0)
            time_latest = time(20, 0)
        elif time_pref == "late":
            time_earliest = time(21, 0)
            time_latest = time(23, 0)

        watch = await WatchQueries.create(
            user_id=user.id,
            venue_id=args["venue_id"],
            venue_name=args["venue_name"],
            watch_date=watch_date,
            party_size=args["party_size"],
            time_earliest=time_earliest,
            time_latest=time_latest,
        )

        time_str = time_pref if time_pref != "any" else "any time"
        return (
            f"Watch created successfully!\n"
            f"- Venue: {watch.venue_name}\n"
            f"- Date: {watch.date}\n"
            f"- Party size: {watch.party_size}\n"
            f"- Time preference: {time_str}"
        )

    async def _list_snipes(self, telegram_id: int) -> str:
        """List user's snipes."""
        snipes = await SnipeQueries.get_user_snipes(telegram_id)

        if not snipes:
            return "No pending snipes."

        results = []
        for s in snipes:
            results.append(
                f"- ID {s.id}: {s.venue_name}, {s.target_date}, "
                f"{s.party_size} guests, runs {s.release_date} at {s.release_time.strftime('%H:%M')}"
            )

        return f"Pending snipes ({len(snipes)}):\n" + "\n".join(results)

    async def _list_watches(self, telegram_id: int) -> str:
        """List user's watches."""
        watches = await WatchQueries.get_user_watches(telegram_id)

        if not watches:
            return "No active watches."

        results = []
        for w in watches:
            time_str = "any time"
            if w.time_earliest and w.time_latest:
                time_str = f"{w.time_earliest.strftime('%H:%M')}-{w.time_latest.strftime('%H:%M')}"
            results.append(
                f"- ID {w.id}: {w.venue_name}, {w.date}, {w.party_size} guests, {time_str}"
            )

        return f"Active watches ({len(watches)}):\n" + "\n".join(results)

    async def _cancel_snipe(self, snipe_id: int, telegram_id: int) -> str:
        """Cancel a snipe."""
        success = await SnipeQueries.cancel(snipe_id, telegram_id)
        if success:
            return f"Snipe {snipe_id} cancelled."
        return (
            f"Could not cancel snipe {snipe_id}. It may not exist or already executed."
        )

    async def _cancel_watch(self, watch_id: int, telegram_id: int) -> str:
        """Cancel a watch."""
        success = await WatchQueries.deactivate(watch_id, telegram_id)
        if success:
            return f"Watch {watch_id} cancelled."
        return f"Could not cancel watch {watch_id}. It may not exist."

    async def clear_history(self, telegram_id: int) -> None:
        """Clear conversation history for a user."""
        await ConversationQueries.clear(telegram_id)
