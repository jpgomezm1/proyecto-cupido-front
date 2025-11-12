# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Proyecto Cupido** is an intelligent WhatsApp-based real estate matching system for Bancolombia real estate agents. It automates property search, captures properties from Wasi links, matches buyers with sellers, and provides complete traceability of the commercial process.

### Core Functionality
- AI-powered property search via natural language queries in WhatsApp
- Automatic property capture from Wasi links shared in group
- Buyer-seller matching with automated notifications
- Complete transaction traceability for commission tracking
- Dual inventory: Pulppo properties + agent-captured properties

## Development Environment Setup

### Python Environment
```bash
# Activate virtual environment
.\venv\Scripts\Activate.ps1  # Windows
source venv/bin/activate      # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### Required Environment Variables (.env)
```bash
# PostgreSQL (Neon)
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require

# Claude AI
ANTHROPIC_API_KEY=sk-ant-api03-...

# WhatsApp (UltraMSG)
ULTRAMSG_INSTANCE_ID=instance123456
ULTRAMSG_TOKEN=token_here
GRUPO_CUPIDO_ID=573001234567-1234567890@g.us  # Group chat ID
```

### Database Setup
```bash
# The schema is in schema_cupido.sql
# Apply it manually to your Neon PostgreSQL database
```

## Common Commands

### Run the System
```bash
# Terminal 1: Start webhook server
python webhook_server.py

# Terminal 2: Expose publicly with ngrok
ngrok http 5000

# Configure webhook URL in UltraMSG dashboard:
# https://your-ngrok-url.ngrok.io/webhook
```

### Testing
```bash
# Test complete search flow
python test_busqueda_completo.py

# Test WhatsApp integration
python test_whatsapp.py

# Quick functionality test
python quick_test.py

# Verify database setup
python check_db_setup.py

# Test search engine
python ejemplo_busqueda.py

# Verify search functionality
python verificar_busqueda.py
```

### Property Management
```bash
# Load Pulppo properties (from scraping)
python cargar_pulppo.py

# Load additional varied properties
python cargar_variadas.py

# Scrape properties from Wasi
python scrapper_wasi.py

# Validate images
python validar_imagenes.py
```

### Utilities
```bash
# Get WhatsApp group ID
python get_grupo_id.py

# Analyze logs
python analizar_logs.py

# Database diagnostics
python diagnostico_db.py

# Test database connection
python test_database.py

# Test AI model
python test_modelo.py
```

## Architecture

### Component Flow
```
WhatsApp (UltraMSG)
    ↓ webhook
webhook_server.py (Flask)
    ↓
whatsapp_bot.py (WhatsAppBot)
    ↓
cupido_manager.py (CupidoManager) ← Business Logic
    ↓                    ↓
scrapper_wasi.py    busqueda_propiedades.py (PropertySearchAgent)
                         ↓ Claude AI
                    database.py (DatabaseManager)
                         ↓
                    PostgreSQL (Neon)
```

### Key Files

**Core System:**
- `whatsapp_bot.py` - WhatsApp interface, message formatting, session management
- `cupido_manager.py` - Business logic: message type detection, workflow orchestration
- `database.py` - PostgreSQL operations, CRUD, traceability logging
- `busqueda_propiedades.py` - AI-powered search using Claude, criteria extraction, ranking
- `scrapper_wasi.py` - Web scraper for extracting property data from Wasi links
- `webhook_server.py` - Flask server that receives WhatsApp webhooks

**Database Schema:**
- `schema_cupido.sql` - Complete database schema with traceability tables

**Configuration:**
- `.env` - Environment variables (credentials, API keys)
- `requirements.txt` - Python dependencies

## Database Schema

### Core Tables
1. **agentes** - Real estate agents (phone, name, stats)
2. **propiedades** - Properties (Pulppo + agent-captured from Wasi)
3. **solicitudes_mercado** - Search requests from agents
4. **interacciones** - Matches (agent selects properties)
5. **eventos_log** - Complete audit log
6. **configuracion_sistema** - System settings

### Key Relationships
- Properties link to capturing agent via `agente_captador_telefono`
- Solicitudes link to agent via `agente_telefono`
- Interacciones link buyer (`agente_comprador_telefono`) to seller (`agente_vendedor_telefono`)
- All events logged in `eventos_log` for traceability

### Important Fields
- `fuente` in propiedades: 'Pulppo' or 'Wasi_Captado'
- `origen` in solicitudes_mercado: 'Grupo' or 'Chat_Privado'
- `estado` in interacciones: tracks match lifecycle

## Workflow Logic

### 1. Property Capture (from Group)
- Agent shares Wasi link in Cupido group → `cupido_manager._extraer_link_wasi()`
- Bot scrapes property data → `scrapper_wasi.py`
- Saves to DB with `fuente='Wasi_Captado'` and agent phone
- Confirms via private message to agent

### 2. Property Search (from Group or Private)
- Agent writes natural language query → `busqueda_propiedades.PropertySearchAgent.search()`
- Claude AI extracts criteria → `_extract_search_criteria()`
- SQL query built and executed → `_build_sql_query()`
- Results ranked by relevance → `_rank_results()`
- Results sent **privately** to agent (even if query was in group)
- Search logged in `solicitudes_mercado`

### 3. Property Selection
- Agent responds with "1", "1 y 3", "todas", "ninguna"
- System identifies selected properties
- Provides contact info:
  - Wasi_Captado: agent's phone who captured it
  - Pulppo: +573183351733 (Pulppo contact)
- Notifies property owner if Wasi_Captado
- Match logged in `interacciones`

### 4. AI Search Ranking
Properties scored by:
- Location match: +10 pts
- Property type: +5 pts
- Price optimal (<90% of max): +8 pts
- Exact bedrooms: +7 pts
- Required amenity: +6 pts each
- Many amenities (>15): +4 pts
- **Pulppo bonus (production)**: +15 pts (prioritizes company inventory)

## Development Guidelines

### When Working with Database
- Always use `DatabaseManager()._get_db()` for new connections
- Close connections with `db.disconnect()`
- All agent phones must match format: `+573XXXXXXXXX` (10 digits after +57)
- Group IDs end with `@g.us`
- Store dates as `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`

### When Working with WhatsApp Bot
- Messages from groups include `data['from']` (participant) and `data['chatId']` (group)
- Private messages: `data['from']` = `data['chatId']`
- Use `GRUPO_CUPIDO_ID` to detect if message is from Cupido group
- Always respond privately to searches (even from group)
- Format: WhatsApp supports markdown-like syntax (*bold*, _italic_, line breaks)

### When Working with Search Logic
- Claude extracts criteria into structured JSON
- SQL query handles fuzzy matching with ILIKE
- Ranking happens in Python after DB query
- Session management via `user_sessions` dict (consider Redis for production)
- Support flexible queries: "busco apto", "necesito casa", etc.

### When Working with Scraper
- Wasi URLs: `https://info.wasi.co/*` or `https://wasi.co/*`
- Extract all property details, amenities, images
- Handle both single properties and listing pages
- Store complete data for search matching

### Important Constraints
- Max WhatsApp message: 4096 characters
- Split long results into multiple messages
- Claude API has rate limits - handle gracefully
- PostgreSQL connection can timeout - always reconnect
- Webhook receives duplicate events - implement deduplication

## Testing Best Practices

### Before Running Tests
1. Ensure database is accessible: `python check_db_setup.py`
2. Verify environment variables are set: `python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.getenv('DATABASE_URL')[:20])"`
3. Check Claude AI is working: `python test_modelo.py`

### Test Coverage
- `test_busqueda_completo.py`: Full search scenarios (10 test cases)
- `test_whatsapp.py`: WhatsApp message sending
- `quick_test.py`: Quick sanity checks
- `test_database.py`: Database operations

### Debugging
- Webhook logs stored in `webhook_logs/` directory
- Test logs in `test_logs_YYYYMMDD_HHMMSS/` directories
- Enable verbose mode in scraper: `VERBOSE_MODE=True` in .env

## Production Considerations

### Scalability
- Current session storage is in-memory (`user_sessions` dict)
- For production, migrate to Redis or database-backed sessions
- Consider background job queue (Celery) for scraping tasks

### Pulppo Integration
- Current: Hardcoded Pulppo properties for demo
- Production: Sync with Pulppo API every N hours
- Implement webhook receiver for real-time Pulppo updates
- Dynamic contact per property (not hardcoded +573183351733)

### Security
- Validate webhook signatures from UltraMSG
- Implement rate limiting per agent
- Sanitize all inputs before SQL queries (currently uses parameterized queries ✓)
- Rotate API keys regularly

### Monitoring
- Track search response times (`solicitudes_mercado.tiempo_respuesta_ms`)
- Monitor match rates: `SELECT COUNT(*) FROM interacciones WHERE estado='Seleccionado'`
- Alert on API failures (Claude, UltraMSG, Database)

## Key Design Decisions

1. **Privacy**: Search results always sent privately, even when query is in group
2. **Traceability**: Every action logged in `eventos_log` for commission auditing
3. **Dual Inventory**: Pulppo properties + agent-captured properties coexist
4. **Pulppo Priority**: Production mode adds +15 score bonus to Pulppo inventory
5. **Agent Attribution**: Properties remember who captured them via `agente_captador_telefono`
6. **Group vs Private**: System detects context and responds accordingly

## Common Issues & Solutions

### "No se procesan mensajes del grupo"
- Verify `GRUPO_CUPIDO_ID` in .env matches actual group ID
- Use `python get_grupo_id.py` to get correct ID

### "Error al conectar con la base de datos"
- Check `DATABASE_URL` format: `postgresql://user:pass@host/db?sslmode=require`
- Verify Neon database is accessible
- Run `python check_db_setup.py`

### "Claude API error"
- Check `ANTHROPIC_API_KEY` is valid
- Verify API quota/rate limits
- Model fallback order in `busqueda_propiedades.py:FALLBACK_MODELS`

### "Webhook no recibe mensajes"
- Verify ngrok is running and webhook URL is configured in UltraMSG
- Check webhook logs in `webhook_logs/`
- Ensure Flask server is running on port 5000

## Future Enhancements

1. **Web Dashboard** - UI for metrics, inventory management, agent administration
2. **Multi-source Integration** - Fincaraiz, Properati, etc.
3. **ML Matching** - Better ranking with machine learning
4. **Predictive Analytics** - Forecast demand patterns
5. **Mobile App** - Native iOS/Android client
