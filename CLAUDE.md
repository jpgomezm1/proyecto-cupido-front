# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Proyecto Cupido** is an intelligent WhatsApp-based real estate matching system for Bancolombia real estate agents. It automates property search, captures properties from Wasi/Tu360 links, matches buyers with sellers, and provides complete traceability.

## Quick Start - WhatsApp Bot System

### 1. Start the Flask Server

```bash
cd proyecto-cupido-front

# Activate virtual environment
source venv/bin/activate      # Linux/Mac/WSL
.\venv\Scripts\Activate.ps1   # Windows PowerShell

# Start the server
python run.py
# Server runs on http://localhost:5050
```

### 2. Expose with ngrok

```bash
# In a new terminal
ngrok http 5050

# You'll get a URL like: https://abc123.ngrok-free.app
# Copy this URL - you'll need it for UltraMSG
```

### 3. Configure UltraMSG Webhook

1. Go to [UltraMSG Dashboard](https://user.ultramsg.com/)
2. Navigate to your instance settings
3. Set the Webhook URL to: `https://YOUR-NGROK-URL/webhook`
4. Enable "Webhook enabled" option
5. Select events: `message_received`

### 4. Test the System

Send a WhatsApp message to your UltraMSG number:
- **"hola"** - Get welcome message
- **"ayuda"** - Get help menu
- **"Busco apto en Laureles, 2 habitaciones, hasta 500 millones"** - Search properties
- Share a Wasi/Tu360 link - Capture property

### System Flow

```
WhatsApp Message → UltraMSG → ngrok → /webhook (Flask)
                                          ↓
                                   WhatsAppBot.handle_incoming_message()
                                          ↓
                                   CupidoManager.detectar_tipo_mensaje()
                                    ↓                    ↓
                            [Wasi/Tu360 Link]      [Search Query]
                                    ↓                    ↓
                            WasiScraper         PropertySearchAgent
                                    ↓                    ↓
                            Save to DB           Claude AI → SQL → Results
                                          ↓
                                   Send WhatsApp Response
```

### Logs Location

Logs are saved to `logs/` directory:
- `cupido.log` - All system logs (JSON format)
- `search.log` - Search-specific logs
- `scraper.log` - Scraping-specific logs
- `whatsapp.log` - WhatsApp interaction logs

## Project Structure

```
proyecto-cupido-front/
├── src/                          # Main application code
│   ├── main.py                   # Flask entry point, webhook server
│   ├── api/                      # REST API endpoints
│   │   ├── properties.py         # Property CRUD, scraping endpoints
│   │   └── analytics.py          # Analytics & metrics endpoints
│   ├── core/                     # Business logic
│   │   ├── whatsapp_bot.py       # WhatsApp message handling
│   │   ├── cupido_manager.py     # Workflow orchestration
│   │   └── search_agent.py       # AI-powered property search (Claude)
│   ├── db/                       # Database layer
│   │   └── database.py           # PostgreSQL operations
│   └── scrapers/                 # Web scrapers
│       ├── wasi.py               # Wasi.co scraper
│       ├── tu360.py              # Tu360 scraper
│       └── utils.py              # Scraper utilities
├── db/                           # Database schemas
│   ├── schema.sql                # Base property schema
│   ├── schema_cupido.sql         # Extended schema with traceability
│   └── migrations/               # SQL migrations
├── tests/                        # Test files
│   ├── test_search.py            # Search functionality tests
│   ├── test_database.py          # Database tests
│   ├── test_whatsapp.py          # WhatsApp integration tests
│   └── ...
├── scripts/                      # Utility scripts
│   ├── check_db_setup.py         # Database verification
│   └── get_grupo_id.py           # Get WhatsApp group ID
├── logs/                         # Application logs
├── run.py                        # Application entry point
├── .env                          # Environment variables
├── .env.example                  # Environment template
└── requirements.txt              # Python dependencies
```

## Development Setup

```bash
# Activate virtual environment
.\venv\Scripts\Activate.ps1  # Windows
source venv/bin/activate      # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### Required Environment Variables (.env)
```bash
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
ANTHROPIC_API_KEY=sk-ant-api03-...
ULTRAMSG_INSTANCE_ID=instance123456
ULTRAMSG_TOKEN=token_here
GRUPO_CUPIDO_ID=573001234567-1234567890@g.us
```

## Running the Application

```bash
# Start the Flask server
python run.py

# Or directly
python -m src.main

# Expose with ngrok for WhatsApp webhooks
ngrok http 5050
```

## API Endpoints

### Properties API (`/api`)
- `GET /api/properties` - List properties with filters
- `GET /api/properties/<slug>` - Get property by slug
- `GET /api/property-images/<id>` - Get property images
- `GET /api/filter-options` - Get filter options with counts
- `POST /api/scrape-wasi` - Scrape property from Wasi URL
- `POST /api/scrape-tu360` - Scrape property from Tu360 URL

### Analytics API (`/api/analytics`)
- `GET /api/analytics/overview` - System metrics
- `GET /api/analytics/searches` - Search statistics
- `GET /api/analytics/captures` - Capture statistics
- `GET /api/analytics/captures/recent` - Recent captures
- `GET /api/analytics/interactions` - Interaction statistics

## Testing

```bash
# Run all tests
python -m pytest tests/

# Run specific test
python -m pytest tests/test_search.py

# Quick database check
python scripts/check_db_setup.py
```

## Architecture Flow

```
WhatsApp (UltraMSG) → webhook → src/main.py
                                    ↓
                           src/core/whatsapp_bot.py
                                    ↓
                          src/core/cupido_manager.py
                           ↓                    ↓
              src/scrapers/wasi.py    src/core/search_agent.py
                                              ↓ Claude AI
                                      src/db/database.py
                                              ↓
                                      PostgreSQL (Neon)
```

## Key Components

### WhatsApp Bot (`src/core/whatsapp_bot.py`)
- Receives messages via webhook
- Routes to search or capture workflow
- Formats responses for WhatsApp

### Cupido Manager (`src/core/cupido_manager.py`)
- Detects message type (search query vs Wasi link)
- Orchestrates property capture from links
- Manages agent sessions and selections

### Search Agent (`src/core/search_agent.py`)
- Uses Claude AI to extract search criteria
- Builds SQL queries with fuzzy matching
- Ranks results by relevance

### Scrapers (`src/scrapers/`)
- Extract property data from Wasi.co and Tu360
- Normalize data to common schema
- Save to database with source tracking

## Database Schema

Core tables in `db/schema_cupido.sql`:
- `propiedades` - Property listings
- `agentes` - Real estate agents
- `solicitudes_mercado` - Search requests
- `interacciones` - Buyer-seller matches
- `eventos_log` - Audit trail

## Development Guidelines

1. **Imports**: Use absolute imports from `src.` prefix
2. **Database**: Always use `DatabaseManager` context manager
3. **API responses**: Return `{"success": bool, "data": ..., "error": ...}`
4. **Logging**: Use print statements for now (logs go to `logs/`)
5. **Tests**: Add tests for new functionality in `tests/`

## Common Issues

### "Module not found"
Ensure you're running from the project root directory.

### "Database connection error"
Check `DATABASE_URL` in `.env` and run `python scripts/check_db_setup.py`.

### "Claude API error"
Verify `ANTHROPIC_API_KEY` is valid and has quota.
