"""
Professional Trading Dashboard for TopstepX Algo
Displays real-time metrics, logs, and algo control
"""
import os
import json
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from datetime import datetime, timedelta
import pandas as pd
import subprocess
import signal as sig
import psutil
import pytz

app = Flask(__name__)
CORS(app)

# Paths
TRADE_LOG_PATH = os.path.join(os.path.dirname(__file__), 'trade_log.csv')
ALGO_LOG_PATH = os.path.join(os.path.dirname(__file__), 'algo.log')
ALGO_SCRIPT = 'topstepx_market_client.py'

def get_algo_status():
    """Check if algo is running"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if ALGO_SCRIPT in ' '.join(proc.info['cmdline'] or []):
                return {
                    'running': True,
                    'pid': proc.info['pid'],
                    'uptime': datetime.now() - datetime.fromtimestamp(proc.create_time())
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return {'running': False, 'pid': None, 'uptime': None}

def get_trade_stats():
    """Get trading statistics from trade log"""
    try:
        if not os.path.exists(TRADE_LOG_PATH):
            return {
                'total_trades': 0,
                'daily_pnl': 0,
                'win_rate': 0,
                'session_counts': {'rdr': 0, 'odr': 0, 'adr': 0},
                'open_positions': 0,
                'last_trade': None
            }
        
        df = pd.read_csv(TRADE_LOG_PATH)
        if df.empty:
            return {
                'total_trades': 0,
                'daily_pnl': 0,
                'win_rate': 0,
                'session_counts': {'rdr': 0, 'odr': 0, 'adr': 0},
                'open_positions': 0,
                'last_trade': None
            }
        
        # Filter today's trades
        today = datetime.now(pytz.timezone('US/Eastern')).date()
        df['timestamp_est'] = pd.to_datetime(df['timestamp_est'])
        df['date'] = df['timestamp_est'].dt.date
        today_trades = df[df['date'] == today]
        
        # Session counts
        session_counts = {
            'rdr': len(today_trades[today_trades['session'] == 'rdr']),
            'odr': len(today_trades[today_trades['session'] == 'odr']),
            'adr': len(today_trades[today_trades['session'] == 'adr'])
        }
        
        # Last trade
        last_trade = None
        if not today_trades.empty:
            last = today_trades.iloc[-1]
            last_trade = {
                'time': str(last['timestamp_est']),
                'session': last['session'].upper(),
                'bias': last['bias'],
                'entry': last['entry'],
                'order_id': last.get('order_id', 'N/A')
            }
        
        return {
            'total_trades': len(today_trades),
            'daily_pnl': 0,  # TODO: Calculate from actual fills
            'win_rate': 0,  # TODO: Calculate from actual results
            'session_counts': session_counts,
            'open_positions': 0,  # TODO: Track from algo state
            'last_trade': last_trade
        }
    except Exception as e:
        print(f"Error reading trade stats: {e}")
        return {
            'total_trades': 0,
            'daily_pnl': 0,
            'win_rate': 0,
            'session_counts': {'rdr': 0, 'odr': 0, 'adr': 0},
            'open_positions': 0,
            'last_trade': None
        }

def get_current_session():
    """Get the current active trading session"""
    eastern = pytz.timezone('US/Eastern')
    now = datetime.now(eastern)
    t = now.time()
    
    from datetime import time
    # Session windows
    if time(20, 30) <= t or t < time(1, 0):
        return 'ADR', '20:30-01:00 EST'
    elif time(4, 0) <= t < time(8, 0):
        return 'ODR', '04:00-08:00 EST'
    elif time(10, 30) <= t < time(16, 0):
        return 'RDR', '10:30-16:00 EST'
    else:
        return 'None', 'No active session'

def get_recent_logs(lines=50):
    """Get recent log lines"""
    try:
        if not os.path.exists(ALGO_LOG_PATH):
            return []
        
        with open(ALGO_LOG_PATH, 'r') as f:
            all_lines = f.readlines()
            recent = all_lines[-lines:]
            # Filter out pandas warnings
            filtered = [line.strip() for line in recent 
                       if 'FutureWarning' not in line 
                       and 'model_logic.py' not in line
                       and line.strip()]
            return filtered
    except Exception as e:
        return [f"Error reading logs: {e}"]

@app.route('/')
def index():
    """Main dashboard page - simplified mobile version"""
    return render_template('dashboard_simple.html')

@app.route('/api/status')
def api_status():
    """API endpoint for dashboard status"""
    algo_status = get_algo_status()
    trade_stats = get_trade_stats()
    session, session_time = get_current_session()
    
    eastern = pytz.timezone('US/Eastern')
    current_time = datetime.now(eastern).strftime('%Y-%m-%d %H:%M:%S EST')
    
    return jsonify({
        'timestamp': current_time,
        'algo_running': algo_status['running'],
        'algo_pid': algo_status['pid'],
        'algo_uptime': str(algo_status['uptime']).split('.')[0] if algo_status['uptime'] else 'N/A',
        'current_session': session,
        'session_time': session_time,
        'stats': trade_stats
    })

@app.route('/api/logs')
def api_logs():
    """API endpoint for recent logs"""
    lines = request.args.get('lines', 100, type=int)
    return jsonify({
        'logs': get_recent_logs(lines)
    })

@app.route('/api/control/<action>')
def api_control(action):
    """Control algo (start/stop)"""
    try:
        if action == 'stop':
            status = get_algo_status()
            if status['running']:
                os.kill(status['pid'], sig.SIGTERM)
                return jsonify({'success': True, 'message': 'Algo stopped'})
            return jsonify({'success': False, 'message': 'Algo not running'})
        
        elif action == 'start':
            status = get_algo_status()
            if status['running']:
                return jsonify({'success': False, 'message': 'Algo already running'})
            
            # Start algo in background
            cmd = f"cd {os.path.dirname(__file__)} && source venv/bin/activate && "
            cmd += f"export TOPSTEPX_USERNAME='{os.getenv('TOPSTEPX_USERNAME')}' && "
            cmd += f"export TOPSTEPX_API_KEY='{os.getenv('TOPSTEPX_API_KEY')}' && "
            cmd += f"nohup python {ALGO_SCRIPT} > algo.log 2>&1 &"
            
            subprocess.Popen(cmd, shell=True, executable='/bin/bash')
            return jsonify({'success': True, 'message': 'Algo started'})
        
        else:
            return jsonify({'success': False, 'message': f'Unknown action: {action}'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)


