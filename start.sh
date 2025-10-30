#!/bin/bash
# Start both algo and mobile dashboard on Railway

set -e  # Exit on error

echo "=== Starting QX Algo System ==="
echo "PORT: $PORT"
echo "Python version: $(python --version)"
echo "Current directory: $(pwd)"
echo "Files present:"
ls -la | head -20

# Start algo in background
echo "=== Starting algo in background ==="
python topstepx_market_client.py > algo.log 2>&1 &
ALGO_PID=$!
echo "Algo started with PID: $ALGO_PID"

# Wait a moment to ensure algo starts
sleep 2

# Check if algo is still running
if ps -p $ALGO_PID > /dev/null; then
   echo "✓ Algo is running"
else
   echo "✗ Algo failed to start!"
fi

# Start mobile dashboard in foreground (Railway needs this)
echo "=== Starting dashboard server ==="
echo "Checking for dashboard_server.py..."
if [ -f "dashboard_server.py" ]; then
    echo "✓ dashboard_server.py found"
    echo "Checking for templates..."
    if [ -d "templates" ]; then
        echo "✓ templates directory found"
        ls -la templates/
    else
        echo "✗ templates directory NOT found"
    fi
    
    echo "Starting gunicorn..."
    exec gunicorn dashboard_server:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120 --access-logfile - --error-logfile - --log-level debug
else
    echo "✗ dashboard_server.py NOT found!"
    echo "Available Python files:"
    ls -la *.py || true
    exit 1
fi



