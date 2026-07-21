"""
Capa de servicios de Fynder.

Lógica de dominio reutilizable (búsqueda, estadísticas de mercado, diagnóstico,
comparativas, escrituras) desacoplada del transporte. La consume tanto el
servidor MCP (`src/mcp_server`) como, progresivamente, la API Flask.

Principios:
- Read-only por defecto; las escrituras viven en `write_service` y siempre
  siguen el patrón propose -> apply con scoping por agente.
- Sin dependencias de Flask ni del webhook: se puede importar y testear solo.
- SQL parametrizado siempre (nunca interpolar entrada de usuario).
"""
