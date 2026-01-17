# Envoy

A personal AI agent on Telegram that helps you book hard-to-get restaurant reservations on Resy. Envoy combines natural language understanding with automated monitoring and booking capabilities.

## Features

### 🤖 Natural Language Interface (Optional)
- **Chat naturally** - Just tell Envoy what you want: "Get me Carbone for 2 on Dec 15"
- **AI-powered** - Uses LLM (Claude, GPT-4, or others) to understand intent and execute actions
- **Conversation memory** - Remembers context across messages
- **Multi-provider support** - Works with Anthropic, OpenAI, OpenRouter, Ollama, or vLLM

### 🎯 Snipes (Auto-booking)
- **Auto-book at release time** - Set up snipes to automatically book when reservations are released
- **Configurable timing** - Specify release date, time, and party size
- **One-shot execution** - Runs once at the exact release moment

### 👀 Watches (Cancellation Monitoring)
- **Monitor for cancellations** - Set watches to monitor specific dates for openings
- **Time preferences** - Choose early, prime, late, or any time
- **Instant notifications** - Get notified immediately when a table becomes available
- **One-click booking** - Reserve instantly via inline buttons

### 🔍 Search & Discovery
- **Restaurant search** - Find restaurants by name or description
- **Detailed information** - See neighborhood, cuisine, and price range

### ⚡ Smart Features
- **Smart batching** - Efficiently checks multiple watches with minimal API calls
- **Rate limiting** - Respects Resy API limits
- **Encrypted storage** - Resy tokens stored securely
- **Persistent storage** - PostgreSQL database for reliability

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL database (or Docker Compose)
- A Telegram Bot Token (get one from [@BotFather](https://t.me/botfather))
- A Resy account
- (Optional) LLM API key if using natural language mode

### Setup

1. **Clone and install dependencies:**
```bash
git clone <repo-url>
cd envoy
uv sync
```

2. **Set up environment variables:**
```bash
cp .env.example .env
```

Edit `.env` with your values:
```bash
# Required
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
DATABASE_URL=postgresql://user:password@localhost:5432/envoy
ENCRYPTION_KEY=your_encryption_key  # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Optional - for natural language mode
LLM_ENABLED=true
LLM_PROVIDER=anthropic  # or openai, openrouter, ollama, vllm
ANTHROPIC_API_KEY=sk-ant-...  # if using Anthropic
OPENAI_API_KEY=sk-...  # if using OpenAI
OPENROUTER_API_KEY=sk-or-...  # if using OpenRouter
```

3. **Set up database:**
```bash
# Run migrations
psql $DATABASE_URL < migrations/001_initial.sql
psql $DATABASE_URL < migrations/002_snipes.sql
psql $DATABASE_URL < migrations/003_snipes_release_date.sql
psql $DATABASE_URL < migrations/004_conversations.sql
psql $DATABASE_URL < migrations/005_conversations_model.sql
```

4. **Run the bot:**
```bash
# Production
uv run envoy

# Development (with hot reload)
uv run envoy-dev
```

### Docker Setup

```bash
docker-compose up -d
```

## Usage

### Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and setup instructions |
| `/login` | Connect your Resy account |
| `/logout` | Disconnect your Resy account |
| `/search <restaurant>` | Search for restaurants |
| `/watch` | Create a new cancellation watch |
| `/watches` | List your active watches |
| `/snipe` | Create an auto-booking snipe |
| `/snipes` | List your pending snipes |
| `/clear` | Clear conversation context (LLM mode) |
| `/help` | Show all commands |

### Natural Language Mode

When `LLM_ENABLED=true`, you can chat naturally with Envoy:

```
You: Get me Carbone for 2 on Dec 15
Envoy: 🎯 Snipe: Carbone, Dec 15, 2 guests → runs Dec 1 at 9am

You: What snipes do I have?
Envoy: Pending snipes (1):
- ID 1: Carbone, Dec 15, 2 guests, runs Dec 1 at 09:00

You: Watch for cancellations at Don Angie Dec 20
Envoy: 👀 Watch: Don Angie, Dec 20, 2 guests, prime time
```

### Creating a Watch

1. Use `/search` to find a restaurant
2. Click "Watch" on the restaurant you want
3. Select date, party size, and preferred time range
4. The bot will notify you when a table becomes available
5. Click "Book Now" to instantly reserve

### Creating a Snipe

1. Use `/search` to find a restaurant
2. Click "Snipe" on the restaurant
3. Enter target date (when you want the reservation)
4. Enter party size
5. Enter days in advance (usually 14 for popular spots)
6. Optionally set release time (default 9am EST)
7. The bot will automatically book at the release time

**Watch vs Snipe:**
- **Watch** = Monitors for cancellations (ongoing, checks periodically)
- **Snipe** = Auto-books at release time (one-shot, runs once at 9am)

## LLM Providers

Envoy supports multiple LLM providers for natural language understanding:

### Anthropic (Claude)
```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

### OpenAI (GPT-4)
```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

### OpenRouter
```bash
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
```

### Ollama (Local)
```bash
LLM_PROVIDER=ollama
# No API key needed, runs locally
```

### vLLM (Local Server)
```bash
LLM_PROVIDER=vllm
VLLM_BASE_URL=http://localhost:8000/v1
```

## Development

### Project Structure

```
envoy/
├── envoy/
│   ├── main.py              # Entry point
│   ├── config.py            # Settings and configuration
│   ├── encryption.py        # Token encryption utilities
│   ├── handlers/            # Telegram command handlers
│   │   ├── auth.py          # Authentication (login/logout)
│   │   ├── booking.py       # Booking operations
│   │   ├── llm_handler.py   # Natural language handler
│   │   ├── search.py        # Restaurant search
│   │   ├── snipe.py         # Snipe creation/management
│   │   └── watch.py         # Watch creation/management
│   ├── llm/                 # LLM integration
│   │   ├── base.py          # Base provider interface
│   │   ├── orchestrator.py  # Conversation orchestration
│   │   ├── tools.py         # Tool definitions and prompts
│   │   └── providers/       # LLM provider implementations
│   │       ├── anthropic.py
│   │       ├── openai.py
│   │       └── openai_responses.py
│   ├── resy/                # Resy API client
│   │   ├── client.py
│   │   └── models.py
│   ├── services/            # Background services
│   │   ├── monitor.py       # Availability monitoring
│   │   ├── notifier.py      # Notification handling
│   │   └── sniper.py        # Snipe execution
│   └── db/                  # Database operations
│       ├── connection.py    # Database connection pool
│       ├── models.py        # Pydantic models
│       └── queries.py       # Database queries
├── migrations/              # SQL schema migrations
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

### Running Tests

```bash
uv run pytest
```

### Code Quality

```bash
uv run ruff check .
uv run ruff format .
```

## Architecture

- **Telegram Bot**: Handles user interactions via python-telegram-bot
- **LLM Orchestrator**: Manages conversation flow and tool execution
- **Resy Client**: Async HTTP client for Resy API
- **Database**: PostgreSQL with asyncpg for persistence
- **Background Services**: Monitor and Sniper services run continuously
- **Encryption**: Fernet encryption for sensitive Resy tokens
- **Monitoring**: Prometheus and Grafana for monitoring

## License

MIT
