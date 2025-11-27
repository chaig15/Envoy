"""LLM orchestrator that handles natural language interactions."""

import logging
from datetime import date, time, timedelta
from typing import Any, Optional

from envoy.db.models import User
from envoy.db.queries import ConversationQueries, SnipeQueries, WatchQueries
from envoy.llm.base import LLMProvider, Message, ToolCall
from envoy.llm.providers import get_provider
from envoy.llm.tools import TOOLS, build_system_prompt
from envoy.resy import ResyClient

logger = logging.getLogger(__name__)

# Max conversation history to keep per user
MAX_HISTORY = 20


def _trim_history_safely(messages: list, max_messages: int) -> list:
    """
    Trim conversation history while keeping tool_use/tool_result pairs together.

    This prevents the API error where a tool_result references a tool_use
    that was trimmed from history.
    """
    if len(messages) <= max_messages:
        return messages

    # Start with the most recent messages
    trimmed = messages[-max_messages:]

    # Check if first message is a tool result - if so, we need to include its tool_use
    while trimmed and trimmed[0].role == "tool":
        # Find the tool_call_id
        tool_call_id = trimmed[0].tool_call_id
        if not tool_call_id:
            # No tool_call_id, just remove this orphaned tool result
            trimmed = trimmed[1:]
            continue

        # Look for the corresponding assistant message with tool_calls in the original history
        found_tool_use = False
        for msg in trimmed:
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.id == tool_call_id:
                        found_tool_use = True
                        break
            if found_tool_use:
                break

        if not found_tool_use:
            # Tool_use not in trimmed history, remove this orphaned tool result
            trimmed = trimmed[1:]
        else:
            break

    return trimmed


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

        # Build system prompt with current date context
        today = date.today()
        system_prompt = build_system_prompt(
            current_date=today.strftime("%B %d, %Y"),
            day_of_week=today.strftime("%A"),
        )

        try:
            # Agentic loop: keep calling tools until LLM returns text-only response
            max_iterations = 10  # Safety limit
            iteration = 0

            while iteration < max_iterations:
                iteration += 1

                # Send to LLM (safely trim to avoid orphaned tool results)
                response = await self.provider.chat(
                    messages=_trim_history_safely(history, MAX_HISTORY),
                    tools=TOOLS,
                    system=system_prompt,
                )

                logger.debug(
                    f"LLM response (iter {iteration}): finish_reason={response.finish_reason}, "
                    f"tool_calls={len(response.tool_calls)}, "
                    f"usage={response.usage}"
                )

                # If no tool calls, we're done
                if not response.tool_calls:
                    final_text = (
                        response.content or "I'm not sure how to help with that."
                    )
                    history.append(Message(role="assistant", content=final_text))
                    break

                # Add assistant message with tool calls to history
                history.append(
                    Message(
                        role="assistant",
                        content=response.content or "",
                        tool_calls=response.tool_calls,
                    )
                )

                # Execute all tool calls
                for tool_call in response.tool_calls:
                    result = await self._execute_tool(
                        tool_call.name,
                        tool_call.arguments,
                        user,
                        telegram_id,
                    )

                    # Add tool result to history
                    history.append(
                        Message(
                            role="tool",
                            content=str(result),
                            tool_call_id=tool_call.id,
                        )
                    )

            else:
                # Hit max iterations
                final_text = (
                    "I got stuck in a loop. Please try again with a simpler request."
                )
                history.append(Message(role="assistant", content=final_text))

            # Save history to DB (keep last MAX_HISTORY messages, safely trimmed)
            trimmed_history = _trim_history_safely(history, MAX_HISTORY)
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

            elif tool_name == "update_snipe":
                return await self._update_snipe(arguments, telegram_id)

            elif tool_name == "cancel_snipe":
                return await self._cancel_snipe(arguments["snipe_id"], telegram_id)

            elif tool_name == "cancel_watch":
                return await self._cancel_watch(arguments["watch_id"], telegram_id)

            elif tool_name == "update_watch":
                return await self._update_watch(arguments, telegram_id)

            else:
                return f"Unknown tool: {tool_name}"

        except Exception as e:
            logger.exception(f"Tool execution error: {e}")
            return f"Error executing {tool_name}: {str(e)}"

    async def _search_restaurant(self, query: str) -> str:
        """Search for restaurants."""
        client = ResyClient()
        try:
            venues = await client.search_venues(query)
            venues = venues[:5]  # Limit results

            if not venues:
                return f"No restaurants found for '{query}'"

            results = []
            for v in venues:
                location = v.display_location or "Unknown area"
                results.append(
                    f"- {v.name} (ID: {v.id}): {location}, "
                    f"{v.cuisine or 'Restaurant'}, ${v.price_range or '?'} price range"
                )

            return f"Found {len(venues)} restaurants:\n" + "\n".join(results)

        finally:
            await client.close()

    async def _create_snipe(self, user: User, args: dict) -> str:
        """Create a snipe."""
        target_date = date.fromisoformat(args["target_date"])

        # Determine release date: explicit release_date takes precedence over days_advance
        if "release_date" in args and args["release_date"]:
            release_date = date.fromisoformat(args["release_date"])
        elif "days_advance" in args:
            days_advance = args["days_advance"]
            # Intuitive counting: "6 days before Dec 3" = Nov 27
            release_date = target_date - timedelta(days=days_advance)
        else:
            # Default to 14 days advance for popular spots
            release_date = target_date - timedelta(days=14)

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

        # Get optional table type preference
        table_type = args.get("table_type")

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
        # "any" leaves both as None - sniper will try prime first, then any

        snipe = await SnipeQueries.create(
            user_id=user.id,
            venue_id=args["venue_id"],
            venue_name=args["venue_name"],
            target_date=target_date,
            release_date=release_date,
            party_size=args["party_size"],
            release_time=release_time_obj,
            table_type=table_type,
            time_earliest=time_earliest,
            time_latest=time_latest,
        )

        result = (
            f"Snipe created successfully!\n"
            f"- Venue: {snipe.venue_name}\n"
            f"- Target date: {snipe.target_date}\n"
            f"- Party size: {snipe.party_size}\n"
        )
        if table_type:
            result += f"- Table type: {table_type}\n"

        # Show time preference
        time_pref_display = {
            "early": "early (5-6:30pm)",
            "prime": "prime (7-8pm)",
            "late": "late (9pm+)",
            "any": "any (prime preferred)",
        }.get(time_pref, "any (prime preferred)")
        result += f"- Time preference: {time_pref_display}\n"

        result += f"- Snipe runs: {snipe.release_date} at {release_time_obj.strftime('%H:%M')} EST"

        return result

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

        # Get optional table type preference
        table_type = args.get("table_type")

        watch = await WatchQueries.create(
            user_id=user.id,
            venue_id=args["venue_id"],
            venue_name=args["venue_name"],
            watch_date=watch_date,
            party_size=args["party_size"],
            time_earliest=time_earliest,
            time_latest=time_latest,
            table_type=table_type,
        )

        time_str = time_pref if time_pref != "any" else "any time"
        result = (
            f"Watch created successfully!\n"
            f"- Venue: {watch.venue_name}\n"
            f"- Date: {watch.date}\n"
            f"- Party size: {watch.party_size}\n"
            f"- Time preference: {time_str}"
        )
        if table_type:
            result += f"\n- Table type: {table_type}"
        return result

    async def _list_snipes(self, telegram_id: int) -> str:
        """List user's snipes."""
        snipes = await SnipeQueries.get_user_snipes(telegram_id)

        if not snipes:
            return "No pending snipes."

        results = []
        for s in snipes:
            table_info = f" [{s.table_type}]" if s.table_type else ""
            # Determine time preference display
            if s.time_earliest and s.time_latest:
                time_info = f", {s.time_earliest.strftime('%H:%M')}-{s.time_latest.strftime('%H:%M')}"
            else:
                time_info = ", any time"
            results.append(
                f"- ID {s.id}: {s.venue_name}{table_info}, {s.target_date}, "
                f"{s.party_size} guests{time_info}, runs {s.release_date} at {s.release_time.strftime('%H:%M')}"
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
            table_info = f" [{w.table_type}]" if w.table_type else ""
            results.append(
                f"- ID {w.id}: {w.venue_name}{table_info}, {w.date}, {w.party_size} guests, {time_str}"
            )

        return f"Active watches ({len(watches)}):\n" + "\n".join(results)

    async def _update_snipe(self, args: dict, telegram_id: int) -> str:
        """Update an existing snipe."""
        snipe_id = args["snipe_id"]

        # Parse optional fields
        release_date_val = None
        if "release_date" in args:
            release_date_val = date.fromisoformat(args["release_date"])

        party_size = args.get("party_size")
        table_type = args.get("table_type")

        # Parse time preference
        time_earliest = None
        time_latest = None
        time_pref = args.get("time_preference")
        if time_pref == "early":
            time_earliest = time(17, 0)
            time_latest = time(18, 30)
        elif time_pref == "prime":
            time_earliest = time(19, 0)
            time_latest = time(20, 0)
        elif time_pref == "late":
            time_earliest = time(21, 0)
            time_latest = time(23, 0)
        elif time_pref == "any":
            # Explicitly set to None to clear any existing preference
            time_earliest = None
            time_latest = None

        # Parse release time
        release_time_val = None
        if "release_time" in args:
            try:
                hour, minute = map(int, args["release_time"].split(":"))
                release_time_val = time(hour, minute)
            except (ValueError, AttributeError):
                pass

        updated = await SnipeQueries.update(
            snipe_id=snipe_id,
            telegram_id=telegram_id,
            release_date=release_date_val,
            party_size=party_size,
            table_type=table_type,
            time_earliest=time_earliest if time_pref else None,
            time_latest=time_latest if time_pref else None,
            release_time=release_time_val,
        )

        if not updated:
            return f"Could not update snipe {snipe_id}. It may not exist, already executed, or you don't have permission."

        # Build result message
        result = f"Snipe {snipe_id} updated!\n"
        result += f"- Venue: {updated.venue_name}\n"
        result += f"- Target date: {updated.target_date}\n"
        result += f"- Party size: {updated.party_size}\n"
        if updated.table_type:
            result += f"- Table type: {updated.table_type}\n"
        if updated.time_earliest and updated.time_latest:
            result += f"- Time preference: {updated.time_earliest.strftime('%H:%M')}-{updated.time_latest.strftime('%H:%M')}\n"
        else:
            result += "- Time preference: any (prime preferred)\n"
        result += f"- Snipe runs: {updated.release_date} at {updated.release_time.strftime('%H:%M')} EST"

        return result

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

    async def _update_watch(self, args: dict, telegram_id: int) -> str:
        """Update an existing watch."""
        watch_id = args["watch_id"]

        party_size = args.get("party_size")
        table_type = args.get("table_type")

        # Handle empty string as "clear table type"
        clear_table_type = table_type == ""
        if clear_table_type:
            table_type = None

        # Parse time preference
        time_earliest = None
        time_latest = None
        time_pref = args.get("time_preference")
        if time_pref == "early":
            time_earliest = time(17, 0)
            time_latest = time(18, 30)
        elif time_pref == "prime":
            time_earliest = time(19, 0)
            time_latest = time(20, 0)
        elif time_pref == "late":
            time_earliest = time(21, 0)
            time_latest = time(23, 0)
        elif time_pref == "any":
            # Explicitly set to None to clear any existing preference
            time_earliest = time(0, 0)  # Use sentinel to indicate "clear"
            time_latest = time(23, 59)

        # Only pass time values if time_pref was specified
        updated = await WatchQueries.update(
            watch_id=watch_id,
            telegram_id=telegram_id,
            party_size=party_size,
            table_type=table_type,
            time_earliest=time_earliest if time_pref and time_pref != "any" else None,
            time_latest=time_latest if time_pref and time_pref != "any" else None,
            clear_table_type=clear_table_type,
        )

        if not updated:
            return f"Could not update watch {watch_id}. It may not exist, be inactive, or you don't have permission."

        # Build result message
        result = f"Watch {watch_id} updated!\n"
        result += f"- Venue: {updated.venue_name}\n"
        result += f"- Date: {updated.date}\n"
        result += f"- Party size: {updated.party_size}\n"
        if updated.table_type:
            result += f"- Table type: {updated.table_type}\n"
        if updated.time_earliest and updated.time_latest:
            result += f"- Time preference: {updated.time_earliest.strftime('%H:%M')}-{updated.time_latest.strftime('%H:%M')}"
        else:
            result += "- Time preference: any"

        return result

    async def clear_history(self, telegram_id: int) -> None:
        """Clear conversation history for a user."""
        await ConversationQueries.clear(telegram_id)
