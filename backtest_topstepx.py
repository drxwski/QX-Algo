#!/usr/bin/env python3
"""
TopstepX Algo Backtester
Fetches historical data and simulates algo trading to verify logic
Shows session-by-session results
"""

import os
import pandas as pd
import pytz
from datetime import datetime, timedelta, time
from topstepx_client import authenticate, retrieve_bars, BAR_UNIT_MINUTE, search_contracts
from model_logic import QXRange
from signal_module import QXSignalGenerator

# Constants matching live algo
TICK_SIZE = 0.25
TICK_VALUE = 1.25
POINT_VALUE = 5.0
RISK_PCT = 0.12
VIRTUAL_BALANCE = 2000.0

def fetch_historical_data(contract_id, days_back=7):
    """Fetch historical 5-minute bars from TopstepX"""
    print(f"Fetching {days_back} days of 5-minute bars...")
    
    end_time = datetime.now(pytz.utc)
    start_time = end_time - timedelta(days=days_back)
    
    token = authenticate()
    
    bars_resp = retrieve_bars(
        contract_id=contract_id,
        start_time=start_time,
        end_time=end_time,
        unit=BAR_UNIT_MINUTE,
        unit_number=5,
        limit=2000,
        live=False,
        include_partial_bar=False,
        token=token
    )
    
    bars = bars_resp.get('bars', [])
    if not bars:
        print("No bars returned!")
        return pd.DataFrame()
    
    df = pd.DataFrame(bars)
    df['t'] = pd.to_datetime(df['t'], utc=True)
    df = df.dropna(subset=['t'])
    df['t'] = df['t'].dt.tz_convert('US/Eastern')
    df = df.rename(columns={'t': 'start', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
    df = df.set_index('start')
    df = df.sort_index()
    
    print(f"✓ Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")
    return df

def calculate_position_size(entry, stop, balance):
    """Calculate position size using 12% risk"""
    stop_distance = abs(entry - stop)
    ticks = stop_distance / TICK_SIZE
    risk_per_contract = ticks * TICK_VALUE
    risk_dollars = balance * RISK_PCT
    contracts = max(1, int(risk_dollars // risk_per_contract)) if risk_per_contract > 0 else 1
    return contracts

def simulate_trade(entry, stop, tp, side, contracts, bars_df, entry_time):
    """
    Simulate a trade and return P&L
    side: 'long' or 'short'
    """
    # Get bars after entry
    future_bars = bars_df[bars_df.index > entry_time].head(100)  # Look ahead max 100 bars (~8 hours)
    
    if future_bars.empty:
        return 0, "No data", None
    
    for idx, row in future_bars.iterrows():
        high = row['high']
        low = row['low']
        
        if side == 'long':
            # Check stop
            if low <= stop:
                pnl = (stop - entry) * contracts * POINT_VALUE
                return pnl, f"Stop hit at {stop:.2f}", idx
            # Check TP
            if high >= tp:
                # 75% at target
                pnl_75 = (tp - entry) * int(contracts * 0.75) * POINT_VALUE
                # Assume 25% trails and gets stopped at breakeven
                pnl_25 = 0
                return pnl_75 + pnl_25, f"TP hit at {tp:.2f} (75%)", idx
        else:  # short
            # Check stop
            if high >= stop:
                pnl = (entry - stop) * contracts * POINT_VALUE
                return pnl, f"Stop hit at {stop:.2f}", idx
            # Check TP
            if low <= tp:
                # 75% at target
                pnl_75 = (entry - tp) * int(contracts * 0.75) * POINT_VALUE
                # Assume 25% trails and gets stopped at breakeven
                pnl_25 = 0
                return pnl_75 + pnl_25, f"TP hit at {tp:.2f} (75%)", idx
    
    # Time limit: close at last price
    last_price = future_bars.iloc[-1]['close']
    if side == 'long':
        pnl = (last_price - entry) * contracts * POINT_VALUE
    else:
        pnl = (entry - last_price) * contracts * POINT_VALUE
    
    return pnl, f"Time limit at {last_price:.2f}", future_bars.index[-1]

def run_backtest(df):
    """Run backtest on historical data"""
    print("\n" + "="*80)
    print("RUNNING BACKTEST")
    print("="*80)
    
    # Initialize model
    time_bins = pd.date_range('00:00', '23:59', freq='1min').strftime('%H:%M')
    mode_retrace_sd = pd.DataFrame({'threshold': [1.0]*len(time_bins)}, index=time_bins)
    mode_ext_sd = pd.DataFrame({'threshold': [1.0]*len(time_bins)}, index=time_bins)
    global_sd = 1.0
    
    signal_gen = QXSignalGenerator(mode_retrace_sd, mode_ext_sd, global_sd)
    model = QXRange(mode_retrace_sd, mode_ext_sd, global_sd)
    
    # Compute boundaries and confirmations
    print("\nComputing DR/IDR boundaries...")
    boundaries = model.compute_boundaries(df)
    
    print("Detecting confirmations...")
    confirmations = signal_gen.detect_confirmations(df)
    
    # Find all confirmations
    results = []
    balance = VIRTUAL_BALANCE
    
    for session in ['odr', 'rdr', 'adr']:
        conf_col = f'{session}_confirmation_time'
        bias_col = f'{session}_confirmation_bias'
        
        session_bounds = boundaries[session]
        
        # Group by date
        df['date'] = df.index.date
        for date in df['date'].unique():
            date_mask = df.index.date == date
            day_confirmations = confirmations[date_mask]
            day_bounds = session_bounds[date_mask]
            day_bars = df[date_mask]
            
            # Check if confirmation exists for this session/date
            conf_times = day_confirmations[conf_col].dropna()
            if conf_times.empty:
                continue
            
            # Get first confirmation
            conf_time_idx = conf_times.index[0]
            conf_time = day_confirmations.loc[conf_time_idx, conf_col]
            bias = day_confirmations.loc[conf_time_idx, bias_col]
            
            # Get DR/IDR levels
            valid_bounds = day_bounds.dropna(subset=['dr_high', 'dr_low', 'idr_high', 'idr_low'])
            if valid_bounds.empty:
                continue
            
            dr_high = valid_bounds['dr_high'].iloc[-1]
            dr_low = valid_bounds['dr_low'].iloc[-1]
            idr_high = valid_bounds['idr_high'].iloc[-1]
            idr_low = valid_bounds['idr_low'].iloc[-1]
            
            # Calculate entry/stop/tp
            idr_range = idr_high - idr_low
            stop_loss = idr_low + (0.60 * idr_range)
            
            # Get bars after confirmation to check for entry
            post_conf_bars = day_bars[day_bars.index > conf_time]
            
            if bias == 'bullish':
                entry_price = idr_high - (0.20 * idr_range)
                idr_std = day_bars['close'].std()
                take_profit = idr_high + idr_std
                side = 'long'
                
                # Find when price reaches entry
                entry_bars = post_conf_bars[post_conf_bars['close'] >= entry_price]
                if entry_bars.empty:
                    result = "No entry - price didn't reach entry level"
                    pnl = 0
                    exit_reason = "N/A"
                else:
                    entry_time = entry_bars.index[0]
                    contracts = calculate_position_size(entry_price, stop_loss, balance)
                    pnl, exit_reason, exit_time = simulate_trade(entry_price, stop_loss, take_profit, side, contracts, df, entry_time)
                    result = f"${pnl:.2f}"
                    balance += pnl
            else:  # bearish
                entry_price = idr_low + (0.20 * idr_range)
                idr_std = day_bars['close'].std()
                take_profit = idr_low - idr_std
                side = 'short'
                
                # Find when price reaches entry
                entry_bars = post_conf_bars[post_conf_bars['close'] <= entry_price]
                if entry_bars.empty:
                    result = "No entry - price didn't reach entry level"
                    pnl = 0
                    exit_reason = "N/A"
                else:
                    entry_time = entry_bars.index[0]
                    contracts = calculate_position_size(entry_price, stop_loss, balance)
                    pnl, exit_reason, exit_time = simulate_trade(entry_price, stop_loss, take_profit, side, contracts, df, entry_time)
                    result = f"${pnl:.2f}"
                    balance += pnl
            
            # Record result
            results.append({
                'Date': date,
                'Session': session.upper(),
                'Confirmation': conf_time.strftime('%H:%M:%S'),
                'Bias': bias.upper(),
                'DR High': f"{dr_high:.2f}",
                'DR Low': f"{dr_low:.2f}",
                'IDR High': f"{idr_high:.2f}",
                'IDR Low': f"{idr_low:.2f}",
                'Entry': f"{entry_price:.2f}",
                'Stop': f"{stop_loss:.2f}",
                'TP': f"{take_profit:.2f}",
                'Result': result,
                'Exit': exit_reason,
                'Balance': f"${balance:.2f}"
            })
    
    return pd.DataFrame(results)

def main():
    print("="*80)
    print("TOPSTEPX ALGO BACKTESTER")
    print("="*80)
    
    # Get contract
    token = authenticate()
    print("\nSearching for MES contract...")
    contracts = search_contracts(token, live=False, searchText="MES")
    
    if not contracts:
        print("No MES contracts found!")
        return
    
    mes_contract = None
    for c in contracts:
        if 'MES' in c.get('name', '').upper() and 'Z5' in c.get('name', '').upper():
            mes_contract = c
            break
    
    if not mes_contract:
        mes_contract = contracts[0]
    
    contract_id = mes_contract['id']
    print(f"✓ Using contract: {mes_contract['name']} ({contract_id})")
    
    # Fetch data
    df = fetch_historical_data(contract_id, days_back=5)
    
    if df.empty:
        print("No data to backtest!")
        return
    
    # Run backtest
    results_df = run_backtest(df)
    
    # Display results
    print("\n" + "="*80)
    print("BACKTEST RESULTS")
    print("="*80)
    
    if results_df.empty:
        print("\nNo trades found in the data range.")
        return
    
    # Show each trade
    for idx, row in results_df.iterrows():
        print(f"\n{'-'*80}")
        print(f"Trade #{idx+1}: {row['Date']} - {row['Session']} Session")
        print(f"{'-'*80}")
        print(f"  Confirmation: {row['Confirmation']} ({row['Bias']})")
        print(f"  DR Levels:  {row['DR High']} / {row['DR Low']}")
        print(f"  IDR Levels: {row['IDR High']} / {row['IDR Low']}")
        print(f"  Entry: {row['Entry']} | Stop: {row['Stop']} | TP: {row['TP']}")
        print(f"  Result: {row['Result']}")
        print(f"  Exit: {row['Exit']}")
        print(f"  Running Balance: {row['Balance']}")
    
    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total Trades: {len(results_df)}")
    
    # Calculate wins/losses
    wins = len([r for r in results_df['Result'] if r.startswith('$') and float(r.replace('$', '')) > 0])
    losses = len([r for r in results_df['Result'] if r.startswith('$') and float(r.replace('$', '')) < 0])
    no_entry = len([r for r in results_df['Result'] if 'No entry' in r])
    
    print(f"Wins: {wins}")
    print(f"Losses: {losses}")
    print(f"No Entry: {no_entry}")
    
    if wins + losses > 0:
        win_rate = (wins / (wins + losses)) * 100
        print(f"Win Rate: {win_rate:.1f}%")
    
    # Final P&L
    final_balance = float(results_df.iloc[-1]['Balance'].replace('$', '')) if not results_df.empty else VIRTUAL_BALANCE
    total_pnl = final_balance - VIRTUAL_BALANCE
    print(f"\nStarting Balance: ${VIRTUAL_BALANCE:.2f}")
    print(f"Ending Balance: ${final_balance:.2f}")
    print(f"Total P&L: ${total_pnl:.2f} ({(total_pnl/VIRTUAL_BALANCE)*100:.1f}%)")
    
    # Save to CSV
    output_file = 'backtest_results.csv'
    results_df.to_csv(output_file, index=False)
    print(f"\n✓ Results saved to {output_file}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nBacktest interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

