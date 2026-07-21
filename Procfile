web: bash -c 'if [ "$FYNDER_ROLE" = "mcp" ]; then exec uvicorn src.mcp_server.run_http:app --host 0.0.0.0 --port $PORT; else exec newrelic-admin run-program gunicorn src.main:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120; fi'
worker: newrelic-admin run-program python worker.py
