# Fynder MCP

Servidor **MCP (Model Context Protocol)** que expone la inteligencia
inmobiliaria de Fynder como herramientas para Claude. Pensado para que un agente
converse con Claude ("¿por qué no rota mi apto de Laureles?", "compárame estas 3
propiedades", "¿hay demanda en El Poblado?") y Claude responda con datos reales
de la base de Fynder.

Es **solo para usuarios con acceso al chat** (agentes), nunca para el admin. La
identidad y el scoping se resuelven contra `chat_users` / `chat_user_sessions`.

## Arquitectura

```
Agente en Claude.ai/Desktop ──Bearer token──▶ Fynder MCP (Streamable HTTP)
                                                   │ identity_service → teléfono
                                                   ▼
                     src/services/  (property · market · diagnosis · write)
                                                   ▼
                         DatabaseManager (Neon)  ·  PropertySearchAgent
```

- `src/services/` — lógica de dominio reutilizable, sin Flask, testeable sola.
- `src/mcp_server/server.py` — 33 herramientas FastMCP.
- `src/mcp_server/run_stdio.py` — local (Claude Desktop).
- `src/mcp_server/run_http.py` — remoto (Claude.ai), ASGI + auth por bearer.

## Herramientas

| Categoría | Tools |
|-----------|-------|
| Búsqueda/ficha | `search_properties` (paginable con `offset`), `get_property` (incluye `imagenes_urls`) |
| Mercado | `get_zone_stats`, `get_demand_stats`, `get_supply_demand_balance` |
| Comparación | `find_comparables`, `compare_properties`, `estimate_price` |
| Diagnóstico | `diagnose_property`, `find_buyers_for_property`, `compradores_para_inmueble` (búsqueda inversa: link de Wasi/Lobbie, link o código de Fynder, o descripción → pedidos que encajan, con score y razones) |
| Inventario | `list_my_properties` |
| Contactos y plan (lo que se cobra) | `ver_contacto`, `ver_contacto_pedido`, `mi_plan`, `mis_desbloqueos`, `reportar_contacto_invalido` |
| Escritura (propose→apply, scoped) | `propose_price_update_tool`, `propose_description_update_tool`, `propose_status_update_tool`, `propose_fields_update_tool`, `apply_change` |

La tabla no es exhaustiva: la lista completa está en `server.py` y en
`tests/test_mcp_server.py` (`EXPECTED_TOOLS`).

Las escrituras solo afectan inmuebles que el agente captó, siguen el patrón
propose→apply (con `confirmation_token` firmado, expira a los 10 min) y quedan en
`eventos_log`.

## Modelo de negocio: desbloqueo de contactos

Buscar y analizar es gratis (con uso justo diario en `search_properties`). El
CONTACTO de quien tiene un inmueble o de quien hizo un pedido se obtiene con
`ver_contacto` / `ver_contacto_pedido` y gasta 1 desbloqueo del plan del agente
(prueba de 2, Básico 7, Medio 15, Pro 30; activación manual). Las reglas viven
en `src/services/suscripcion_service.py`: no se cobra si el inmueble no está
disponible (verificación HTTP en vivo), si no hay contacto usable, si ya estaba
desbloqueado o si es propio; los pedidos solo se desbloquean si quien pidió es
usuario Fynder con términos aceptados. `solicitar_visita` (el equipo de Fynder
coordina) queda como red de seguridad cuando no hay contacto usable.

## Wrapper central de tools

Toda tool registrada con `@mcp.tool(...)` pasa por `_tool_saneada` (server.py),
que:

1. la ejecuta en un hilo (`anyio.to_thread`), para no bloquear el event loop;
2. exige un agente autenticado y lo liga a la llamada (`current_agent()`);
3. con `costo_ia=True`, cuenta la llamada contra el uso justo diario
   (`uso_diario`) y la rechaza al pasarse;
4. sanea la salida (`redact.sanitize`): ningún dato de contacto de agentes, salvo
   un `ContactoRevelado` devuelto por una tool registrada con
   `revela_contacto=True` (solo las de `_TOOLS_QUE_REVELAN`; registrar otra con
   ese flag lanza error);
5. registra el uso en `mcp_tool_calls` (migración 039; solo nombres de
   argumentos, nunca valores).

Al agregar una tool: no repitas el chequeo de auth, y pásale `title` y
`annotations` (`_LECTURA`, `_LECTURA_EXTERNA` o `_escritura(...)`). Si llama a
Claude, márcala `costo_ia=True`. Nunca devuelvas un contacto en un dict normal.

La identidad (`AgentIdentity.telefono_10`) solo trae el teléfono si está
VERIFICADO: un teléfono auto-declarado no da acceso a "mis propiedades", a las
escrituras ni a desbloqueos propios gratis.

## Entorno (venv 3.11)

El SDK de MCP requiere Python ≥ 3.10; el backend corre en 3.9 local. Se usa un
venv separado `venv-mcp` (Python 3.11, igual que Heroku).

```bash
# El box intercepta TLS: instalar con el CA de Windows exportado a PEM.
py -3.11 -m venv venv-mcp
venv-mcp/Scripts/python -m pip install --cert venv-mcp/win-ca-bundle.pem -r requirements.txt
```

Variables requeridas: `DATABASE_URL`, `FYNDER_MCP_SECRET` (o `JWT_SECRET`),
`ANTHROPIC_API_KEY` (para `search_properties`).

## Emitir un token para un agente

```bash
python scripts/mcp_issue_token.py --email agente@fynder.com --label "Claude Desktop"
python scripts/mcp_issue_token.py --list
python scripts/mcp_issue_token.py --revoke <token>
```

## Correr local (Claude Desktop)

```bash
export FYNDER_MCP_TOKEN=<token-del-agente>
python -m src.mcp_server.run_stdio
```

En `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "fynder": {
      "command": "…/venv-mcp/Scripts/python.exe",
      "args": ["-m", "src.mcp_server.run_stdio"],
      "cwd": "…/proyecto-cupido-front",
      "env": { "FYNDER_MCP_TOKEN": "<token>" }
    }
  }
}
```

## Correr remoto (Claude.ai) — deploy aislado de producción

Se despliega como **app/proceso Heroku separado** (no toca el dyno web actual):

```
web: uvicorn src.mcp_server.run_http:app --host 0.0.0.0 --port $PORT   # Procfile.mcp
```

El endpoint MCP queda en `https://<app>/mcp`. En Claude.ai se agrega como
*custom connector* con ese URL y el header `Authorization: Bearer <token>`.

> **Auth (fase piloto):** bearer token opaco por agente (sesión en
> `chat_user_sessions`). La migración a **OAuth 2.1** se hace después sin tocar
> las tools: solo cambia el middleware de `run_http.py`.

## Tests

```bash
venv-mcp/Scripts/python -m pytest tests/test_mcp_*.py -v
```

Los tests de integración son de **solo lectura** (seguros contra producción) y
hacen skip si no hay `DATABASE_URL`.
