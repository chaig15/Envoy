"""Unified tool definitions for LLM function calling."""

# Tool definitions in unified format (Anthropic-style)
# These get converted to provider-specific formats automatically

TOOLS = [
    {
        "name": "search_restaurant",
        "description": "Search for restaurants by name or description. Use this when the user mentions a restaurant they want to find.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Restaurant name or search query (e.g., 'Carbone', 'Italian Greenwich Village')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_snipe",
        "description": "Set up an auto-book snipe for when new reservations are released. Use this when the user wants to book a restaurant at the exact moment reservations become available.",
        "input_schema": {
            "type": "object",
            "properties": {
                "venue_id": {
                    "type": "integer",
                    "description": "Restaurant venue ID (from search results)",
                },
                "venue_name": {
                    "type": "string",
                    "description": "Restaurant name for display",
                },
                "target_date": {
                    "type": "string",
                    "description": "Date user wants reservation FOR (YYYY-MM-DD)",
                },
                "party_size": {
                    "type": "integer",
                    "description": "Number of guests (1-20)",
                },
                "days_advance": {
                    "type": "integer",
                    "description": "How many days before target_date the restaurant releases reservations (e.g., 7, 14, 21, 30). Most popular spots are 14 days. Example: 6 days before Dec 3 = Nov 27.",
                },
                "release_date": {
                    "type": "string",
                    "description": "Explicit release date when snipe should run (YYYY-MM-DD). Use this instead of days_advance when user specifies an exact date. Takes precedence over days_advance if both provided.",
                },
                "release_time": {
                    "type": "string",
                    "description": "Time when reservations open (HH:MM in 24h format, e.g., '09:00'). Default is 09:00 (9am EST).",
                },
                "table_type": {
                    "type": "string",
                    "description": "Specific table/seating type to target (e.g., 'Dining Room', 'Bar', 'Patio', 'Butter Chicken', 'Tasting Menu'). If specified, only books slots matching this type. Case-insensitive partial match.",
                },
                "time_preference": {
                    "type": "string",
                    "enum": ["early", "prime", "late", "any"],
                    "description": "Preferred reservation time: 'early' (5-6:30pm), 'prime' (7-8pm), 'late' (9pm+), 'any' (tries prime first, then any available). Default is 'any'.",
                },
            },
            "required": [
                "venue_id",
                "venue_name",
                "target_date",
                "party_size",
            ],
        },
    },
    {
        "name": "create_watch",
        "description": "Watch for cancellations on a specific date. Use this when the user wants to monitor for openings due to cancellations (not new releases).",
        "input_schema": {
            "type": "object",
            "properties": {
                "venue_id": {
                    "type": "integer",
                    "description": "Restaurant venue ID (from search results)",
                },
                "venue_name": {
                    "type": "string",
                    "description": "Restaurant name for display",
                },
                "date": {
                    "type": "string",
                    "description": "Date to watch (YYYY-MM-DD)",
                },
                "party_size": {
                    "type": "integer",
                    "description": "Number of guests (1-20)",
                },
                "time_preference": {
                    "type": "string",
                    "enum": ["early", "prime", "late", "any"],
                    "description": "Preferred time: 'early' (5-6:30pm), 'prime' (7-8pm), 'late' (9pm+), 'any' (no preference)",
                },
            },
            "required": ["venue_id", "venue_name", "date", "party_size"],
        },
    },
    {
        "name": "list_snipes",
        "description": "List the user's pending snipes. Use when user asks about their snipes or scheduled bookings.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_watches",
        "description": "List the user's active watches. Use when user asks about their watches or what they're monitoring.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "update_snipe",
        "description": "Update an existing pending snipe. Use this to change the release date, party size, time preference, or other details of a snipe.",
        "input_schema": {
            "type": "object",
            "properties": {
                "snipe_id": {
                    "type": "integer",
                    "description": "ID of the snipe to update",
                },
                "release_date": {
                    "type": "string",
                    "description": "New release date when snipe should run (YYYY-MM-DD). This is the date reservations open, NOT the target reservation date.",
                },
                "party_size": {
                    "type": "integer",
                    "description": "New party size (1-20)",
                },
                "table_type": {
                    "type": "string",
                    "description": "New table type to target (e.g., 'Dining Room', 'Bar', 'Butter Chicken')",
                },
                "time_preference": {
                    "type": "string",
                    "enum": ["early", "prime", "late", "any"],
                    "description": "New time preference: 'early' (5-6:30pm), 'prime' (7-8pm), 'late' (9pm+), 'any'",
                },
                "release_time": {
                    "type": "string",
                    "description": "New release time (HH:MM in 24h format, e.g., '09:00')",
                },
            },
            "required": ["snipe_id"],
        },
    },
    {
        "name": "cancel_snipe",
        "description": "Cancel a pending snipe by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "snipe_id": {
                    "type": "integer",
                    "description": "ID of the snipe to cancel",
                }
            },
            "required": ["snipe_id"],
        },
    },
    {
        "name": "cancel_watch",
        "description": "Cancel an active watch by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "watch_id": {
                    "type": "integer",
                    "description": "ID of the watch to cancel",
                }
            },
            "required": ["watch_id"],
        },
    },
]

SYSTEM_PROMPT = """You are Envoy, a personal AI agent that helps users book hard-to-get restaurant reservations.

## Capabilities
- Search for restaurants
- Set up "snipes" to auto-book when new reservations are released
- Set up "watches" to monitor for cancellations
- List, update, and cancel existing snipes/watches

## Important Context
- Most popular NYC restaurants release reservations 7-14 days in advance at 9am EST
- "Snipe" = auto-book at release time (for new openings)
- "Watch" = monitor for cancellations (for already-released dates)
- days_advance uses intuitive counting: "6 days before Dec 3" = Nov 27 (Dec 3 minus 6 days)
- When user specifies an exact release date (e.g., "reservations open Nov 27"), use the release_date parameter directly instead of days_advance

## Workflow
1. When user mentions a restaurant, search for it first to get the venue_id
2. Use that venue_id when creating snipes or watches
3. Ask for clarification only if critical info is missing

## Response Style
- Be concise and helpful
- After tool calls, use EXACT dates/times from the tool result - do not paraphrase or recalculate
- Format confirmations like:
  🎯 Snipe: Carbone, Dec 5, 2 guests → runs Nov 21 at 9am
  👀 Watch: Don Angie, Dec 10, 4 guests, prime time
- If unsure about days_advance, suggest 14 days as default for popular spots

## Examples
- "Get me Carbone for 2 on Dec 15" → Search Carbone, then create_snipe
- "Watch for cancellations at Don Angie Dec 20" → Search Don Angie, then create_watch
- "What am I watching?" → list_watches
"""
