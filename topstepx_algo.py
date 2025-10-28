import os
import time
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
from QX_Algo.signal_module import QXSignalGenerator
from QX_Algo.topstepx_client import authenticate, search_accounts, search_contracts, place_order

# === CONFIG ===
ES_DATA_PATH = os.path.join(os.path.dirname(__file__), 'ESDATA.csv')
METRICS_PATH = os.path.join(os.path.dirname(__file__), 'retrace_ext_metrics.csv')
BAR_INTERVAL_MINUTES = 5
ACCOUNT_NAME = 'PRACTICEJUL2215188144'  # Change if needed
CONTRACT_NAME = 'ESU5'  # E-Mini S&P 500, update as needed

# === Load Data ===
def load_es_data(csv_path):
    df = pd.read_csv(csv_path, parse_dates=['timestamp'])
    df = df.set_index('timestamp').tz_localize('America/New_York')
    df = df.sort_index()
    return df

def load_metrics(csv_path):
    return pd.read_csv(csv_path)

# === Main Algo ===
def main():
    print('Loading ES data...')
    es_data = load_es_data(ES_DATA_PATH)
    print('Loading retrace/extension metrics...')
    metrics = load_metrics(METRICS_PATH)
    print('Initializing QXSignalGenerator...')
    # For demo, use dummy mode tables and global_sd
    time_bins = pd.date_range('00:00', '23:59', freq='1min').strftime('%H:%M')
    mode_retrace_sd = pd.DataFrame({'threshold': np.random.uniform(0.5, 1.5, len(time_bins))}, index=time_bins)
    mode_ext_sd = pd.DataFrame({'threshold': np.random.uniform(1.0, 2.0, len(time_bins))}, index=time_bins)
    global_sd = es_data['close'].diff().std()
    signal_gen = QXSignalGenerator(mode_retrace_sd, mode_ext_sd, global_sd)

    # Authenticate and get account/contract
    print('Authenticating with TopstepX...')
    token = authenticate()
    accounts = search_accounts(token)
    account_id = None
    for acc in accounts:
        if acc.get('name') == ACCOUNT_NAME:
            account_id = acc['id']
            break
    if not account_id:
        raise Exception(f'Account {ACCOUNT_NAME} not found!')
    contracts = search_contracts(token, live=False)
    contract_id = None
    for c in contracts:
        if c.get('name') == CONTRACT_NAME or 'E-Mini S&P 500' in c.get('description', ''):
            contract_id = c['id']
            break
    if not contract_id:
        raise Exception(f'Contract {CONTRACT_NAME} not found!')
    print(f'Using account_id={account_id}, contract_id={contract_id}')

    # === State for risk management ===
    daily_loss = 0
    daily_trades = 0
    last_trade_result = None
    risk_cycle = [1.5, 2, 1]  # percent
    risk_idx = 0
    wins_in_row = 0
    losses_in_row = 0
    max_daily_loss = 900
    max_trades_per_session = 2
    session_date = None

    # === Main Loop ===
    print('Starting trading loop...')
    while True:
        now = datetime.now(pytz.timezone('America/New_York'))
        today = now.date()
        # Reset daily counters at new session
        if session_date != today:
            daily_loss = 0
            daily_trades = 0
            session_date = today
            print(f'--- New session: {today} ---')

        # Get latest bar
        latest_bar = es_data.iloc[-1:]
        # TODO: In production, fetch new bars from live data feed

        # Compute boundaries and confirmations
        signal_gen.compute_boundaries(es_data)
        confirmations = signal_gen.detect_confirmations(es_data)

        # For each session, check for new confirmation
        for session in ['rdr', 'odr', 'adr']:
            conf_col = f'{session}_confirmation_time'
            bias_col = f'{session}_confirmation_bias'
            conf_times = confirmations[conf_col].dropna()
            if not conf_times.empty:
                conf_time = conf_times.index[-1]
                bias = confirmations.loc[conf_time, bias_col]
                # Get time interval (e.g., 10:30-11:00)
                conf_time_str = conf_time.strftime('%H:%M')
                # Find the matching time_interval in metrics
                weekday = conf_time.strftime('%A')
                # Find the closest time_interval in metrics
                metrics_row = metrics[(metrics['weekday'] == weekday) &
                                       (metrics['session'].str.lower() == session) &
                                       (metrics['bias'] == bias) &
                                       (metrics['time_interval'].str.startswith(conf_time_str[:2]))]
                if metrics_row.empty:
                    print(f'No metrics found for {weekday}, {session}, {bias}, {conf_time_str}')
                    continue
                retrace_median = metrics_row.iloc[0]["retrace_median"]
                ext_median = metrics_row.iloc[0]["max_extension_median"]
                # === ENTRY/EXIT LOGIC ===
                entry_price = None  # TODO: Calculate from retrace_median and DR/IDR
                stop_loss = None    # TODO: 5 points or 2 beyond range
                take_profit = None  # TODO: ext_median
                # === RISK MANAGEMENT ===
                # TODO: Calculate position size based on risk_cycle, wins/losses, and account balance
                # TODO: Enforce max_daily_loss and max_trades_per_session
                # === ORDER PLACEMENT ===
                # TODO: Place order via place_order(account_id, contract_id, ...)
                print(f"Signal: {session.upper()} {bias} at {conf_time_str} | Entry: {entry_price} | SL: {stop_loss} | TP: {take_profit}")
                # TODO: Track open trades, monitor for exit conditions, update daily_loss and daily_trades

        # Sleep until next bar
        time.sleep(BAR_INTERVAL_MINUTES * 60)

if __name__ == '__main__':
    main() 