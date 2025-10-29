#!/bin/bash
# Start both algo and dashboard on Railway

# Start algo in background
python topstepx_market_client.py > algo.log 2>&1 &

# Start dashboard in foreground (Railway needs this)
gunicorn dashboard_app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120 --access-logfile - --error-logfile -

