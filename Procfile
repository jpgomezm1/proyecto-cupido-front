web: newrelic-admin run-program gunicorn src.main:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
worker: newrelic-admin run-program python worker.py
