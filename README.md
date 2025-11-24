# Resnype

A Telegram bot that monitors Resy for reservation availability and enables one-click booking.

## Features

- **Search restaurants** on Resy directly from Telegram
- **Watch for availability** - set alerts for specific dates, times, and party sizes
- **Instant notifications** when a table becomes available
- **One-click booking** via inline buttons
- **Smart batching** - efficiently checks multiple watches with minimal API calls

## Quick Start

### Prerequisites

- Docker and Docker Compose
- A Telegram Bot Token (get one from [@BotFather](https://t.me/botfather))
- A Resy account

### Setup

1. Clone and configure:
```bash
cd resnype
cp .env.example .env
```

2. Edit `.env` with your values:
```bash
# Generate an encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

3. Start the bot:
```bash
docker-compose up -d
```

## Usage

### Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and setup instructions |
| `/login` | Connect your Resy account |
| `/search <restaurant>` | Search for restaurants |
| `/watch` | Create a new availability watch |
| `/watches` | List your active watches |
| `/help` | Show all commands |

### Creating a Watch

1. Use `/search` to find a restaurant
2. Click "Watch" on the restaurant you want
3. Select date, party size, and preferred time range
4. The bot will notify you when a table becomes available
5. Click "Book Now" to instantly reserve

## Development

### Local Setup with uv

```bash
# Install dependencies
uv sync

# Run locally (needs PostgreSQL)
uv run python -m resnype.main
```

### Project Structure

```
resnype/
├── resnype/
│   ├── main.py           # Entry point
│   ├── config.py         # Settings
│   ├── handlers/         # Telegram command handlers
│   ├── resy/             # Resy API client
│   ├── services/         # Background monitoring
│   └── db/               # Database operations
├── migrations/           # SQL schema
├── Dockerfile
└── docker-compose.yml
```

## License

MIT
