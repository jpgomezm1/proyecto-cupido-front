web: bash -c 'if [ "$FYNDER_ROLE" = "mcp" ]; then exec uvicorn src.mcp_server.run_http:app --host 0.0.0.0 --port $PORT --workers ${MCP_WORKERS:-2}; else exec newrelic-admin run-program gunicorn src.main:app --bind 0.0.0.0:$PORT --workers 2 --worker-class gthread --threads 6 --timeout 90; fi'
worker: newrelic-admin run-program python worker.py
