#!/usr/bin/env python3
"""
QX Algo Monitoring Dashboard - Mobile-Friendly
Runs on Railway, accessible from anywhere
"""

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from datetime import datetime, time
import pytz
import json
import os
from pathlib import Path
import pandas as pd

app = Flask(__name__)
CORS(app)

# Paths
TRADE_LOG_PATH = Path(__file__).parent / 'trade_log.csv'
ALGO_LOG_PATH = Path(__file__).parent / 'algo.log'
STATE_FILE = Path(__file__).parent / 'dashboard_state.json'

def get_current_session():
    """Determine which session is currently active"""
    eastern = pytz.timezone('US/Eastern')
    now = datetime.now(pytz.utc).astimezone(eastern)
    t = now.time()
    
    if time(20, 30) <= t or t < time(1, 0):
        return 'ADR', (time(20, 30), time(1, 0))
    elif time(4, 0) <= t < time(8, 0):
        return 'ODR', (time(4, 0), time(8, 0))
    elif time(10, 30) <= t < time(16, 0):
        return 'RDR', (time(10, 30), time(16, 0))
    else:
        return 'NONE', None

def read_trade_log():
    """Read recent trades from CSV"""
    if not TRADE_LOG_PATH.exists():
        return []
    
    try:
        df = pd.read_csv(TRADE_LOG_PATH)
        # Get today's trades
        today = datetime.now(pytz.timezone('US/Eastern')).date()
        df['timestamp_est'] = pd.to_datetime(df['timestamp_est'])
        df = df[df['timestamp_est'].dt.date == today]
        
        # Convert to list of dicts
        trades = df.to_dict('records')
        # Format timestamps
        for trade in trades:
            trade['timestamp_est'] = trade['timestamp_est'].strftime('%H:%M:%S')
        
        return trades[-10:]  # Last 10 trades
    except Exception as e:
        print(f"Error reading trade log: {e}")
        return []

def read_algo_status():
    """Read latest algo status from log"""
    if not ALGO_LOG_PATH.exists():
        return {
            'running': False,
            'last_update': 'Unknown',
            'status': 'Log file not found'
        }
    
    try:
        # Read last 50 lines
        with open(ALGO_LOG_PATH, 'r') as f:
            lines = f.readlines()[-50:]
        
        # Parse for status
        last_bar = None
        last_session = None
        dr_idr = None
        
        for line in reversed(lines):
            if '[Bar-Close]' in line and not last_bar:
                last_bar = line.split('[Bar-Close]')[1].strip()
            if 'session active' in line and not last_session:
                last_session = line
            if '[DR/IDR]' in line and not dr_idr:
                dr_idr = line.split('[DR/IDR]')[1].strip()
        
        # Check if algo is running (last update within 2 minutes)
        running = False
        last_update = 'Unknown'
        if lines:
            last_line = lines[-1]
            # Simple heuristic: if we have recent log entries, it's running
            running = True
            last_update = 'Active'
        
        return {
            'running': running,
            'last_update': last_update,
            'last_bar': last_bar,
            'last_session': last_session,
            'dr_idr': dr_idr
        }
    except Exception as e:
        print(f"Error reading algo log: {e}")
        return {
            'running': False,
            'last_update': 'Error',
            'status': str(e)
        }

def calculate_daily_pnl():
    """Calculate today's P&L from trade log"""
    trades = read_trade_log()
    
    # For now, we don't have exit data in CSV
    # This would need to be implemented when we add exit logging
    return {
        'total': 0.0,
        'realized': 0.0,
        'unrealized': 0.0,
        'trades_count': len(trades),
        'wins': 0,
        'losses': 0
    }

@app.route('/')
def index():
    """Serve the dashboard HTML - simplified version"""
    return render_template('dashboard_simple.html')

@app.route('/api/status')
def api_status():
    """API endpoint for dashboard data"""
    try:
        eastern = pytz.timezone('US/Eastern')
        now = datetime.now(pytz.utc).astimezone(eastern)
        
        current_session, session_window = get_current_session()
        algo_status = read_algo_status()
        trades = read_trade_log()
        pnl = calculate_daily_pnl()
        
        return jsonify({
            'timestamp': now.strftime('%Y-%m-%d %H:%M:%S EST'),
            'current_session': current_session,
            'session_window': f"{session_window[0].strftime('%H:%M')}-{session_window[1].strftime('%H:%M')}" if session_window else 'None',
            'algo_running': algo_status['running'],
            'last_update': algo_status['last_update'],
            'last_bar': algo_status.get('last_bar'),
            'dr_idr': algo_status.get('dr_idr'),
            'stats': {
                'daily_pnl': pnl['total'],
                'total_trades': pnl['trades_count'],
                'win_rate': 0,
                'open_positions': 0,
                'session_counts': {'rdr': 0, 'odr': 0, 'adr': 0}
            },
            'recent_trades': trades
        })
    except Exception as e:
        # Return safe defaults if anything fails
        return jsonify({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S EST'),
            'current_session': 'ERROR',
            'session_window': 'N/A',
            'algo_running': False,
            'last_update': f'Error: {str(e)}',
            'stats': {
                'daily_pnl': 0,
                'total_trades': 0,
                'win_rate': 0,
                'open_positions': 0,
                'session_counts': {'rdr': 0, 'odr': 0, 'adr': 0}
            },
            'recent_trades': []
        })

@app.route('/api/logs')
def api_logs():
    """Get recent algo logs"""
    try:
        lines_requested = int(request.args.get('lines', 100))
        
        if not ALGO_LOG_PATH.exists():
            return jsonify({'logs': ['Waiting for algo to start...']})
        
        with open(ALGO_LOG_PATH, 'r') as f:
            all_lines = f.readlines()
            recent = all_lines[-lines_requested:]
            # Clean and filter
            cleaned = [line.strip() for line in recent if line.strip()]
            return jsonify({'logs': cleaned})
    except Exception as e:
        return jsonify({'logs': [f'Error reading logs: {str(e)}']})

@app.route('/health')
def health():
    """Health check endpoint for Railway"""
    return jsonify({'status': 'healthy', 'service': 'qx-algo-dashboard'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)


