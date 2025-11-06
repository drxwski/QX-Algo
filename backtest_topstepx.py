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

def fetch_historical_data(contract_id, days_back=14):
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
        limit=5000,  # 2 weeks ~= 4000 bars
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
    """
    Calculate position size using 12% risk of BASE balance ($2000).
    For TopstepX challenge: Always risk $240 max, cap contracts at 48.
    """
    BASE_BALANCE = 2000.0  # TopstepX starting balance
    
    stop_distance = abs(entry - stop)
    ticks = stop_distance / TICK_SIZE
    risk_per_contract = ticks * TICK_VALUE
    risk_dollars = BASE_BALANCE * RISK_PCT  # Always $240
    contracts = max(1, int(risk_dollars // risk_per_contract)) if risk_per_contract > 0 else 1
    
    # Ensure max loss at stop is ≤ $240
    max_loss = stop_distance * contracts * POINT_VALUE
    if max_loss > 240:
        contracts = int(240 / (stop_distance * POINT_VALUE))
        contracts = max(1, contracts)
    
    # Cap at 48 contracts (prevents >$1200 profit per trade for challenge compliance)
    contracts = min(contracts, 48)
    return contracts

def simulate_trade(entry, stop, tp, side, contracts, bars_df, entry_time):
    """
    Simulate a trade and return P&L
    side: 'long' or 'short'
    Max profit capped at $1300 for challenge compliance
    """
    MAX_PROFIT_PER_TRADE = 1300.0  # TopstepX challenge limit
    
    # Get bars after entry
    future_bars = bars_df[bars_df.index > entry_time].head(100)  # Look ahead max 100 bars (~8 hours)
    
    if future_bars.empty:
        return 0, "No data", None
    
    for idx, row in future_bars.iterrows():
        high = row['high']
        low = row['low']
        
        if side == 'long':
            # Check profit cap first (close if profit would exceed $1300)
            current_profit = (high - entry) * contracts * POINT_VALUE
            if current_profit >= MAX_PROFIT_PER_TRADE:
                return MAX_PROFIT_PER_TRADE, f"Profit cap at ${MAX_PROFIT_PER_TRADE:.0f}", idx
            
            # Check stop
            if low <= stop:
                pnl = (stop - entry) * contracts * POINT_VALUE
                return pnl, f"Stop hit at {stop:.2f}", idx
            # Check TP
            if high >= tp:
                # 75% at target
                pnl_75 = (tp - entry) * int(contracts * 0.75) * POINT_VALUE
                # Cap if exceeds max
                if pnl_75 > MAX_PROFIT_PER_TRADE:
                    return MAX_PROFIT_PER_TRADE, f"Profit cap at ${MAX_PROFIT_PER_TRADE:.0f}", idx
                # Assume 25% trails and gets stopped at breakeven
                pnl_25 = 0
                return pnl_75 + pnl_25, f"TP hit at {tp:.2f} (75%)", idx
        else:  # short
            # Check profit cap first
            current_profit = (entry - low) * contracts * POINT_VALUE
            if current_profit >= MAX_PROFIT_PER_TRADE:
                return MAX_PROFIT_PER_TRADE, f"Profit cap at ${MAX_PROFIT_PER_TRADE:.0f}", idx
            
            # Check stop
            if high >= stop:
                pnl = (entry - stop) * contracts * POINT_VALUE
                return pnl, f"Stop hit at {stop:.2f}", idx
            # Check TP
            if low <= tp:
                # 75% at target
                pnl_75 = (entry - tp) * int(contracts * 0.75) * POINT_VALUE
                # Cap if exceeds max
                if pnl_75 > MAX_PROFIT_PER_TRADE:
                    return MAX_PROFIT_PER_TRADE, f"Profit cap at ${MAX_PROFIT_PER_TRADE:.0f}", idx
                # Assume 25% trails and gets stopped at breakeven
                pnl_25 = 0
                return pnl_75 + pnl_25, f"TP hit at {tp:.2f} (75%)", idx
    
    # Time limit: close at last price
    last_price = future_bars.iloc[-1]['close']
    if side == 'long':
        pnl = (last_price - entry) * contracts * POINT_VALUE
    else:
        pnl = (entry - last_price) * contracts * POINT_VALUE
    
    # Cap profit even on time limit
    if pnl > MAX_PROFIT_PER_TRADE:
        pnl = MAX_PROFIT_PER_TRADE
        return pnl, f"Profit cap at ${MAX_PROFIT_PER_TRADE:.0f}", future_bars.index[-1]
    
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
            
            # Entry time cutoffs (skip trade if entry not hit by these times)
            entry_cutoff = {
                'odr': time(6, 0),   # 6:00 AM
                'rdr': time(14, 0),  # 2:00 PM
                'adr': time(23, 0)   # 11:00 PM
            }
            cutoff_time = entry_cutoff[session]
            post_conf_bars = post_conf_bars[post_conf_bars.index.time <= cutoff_time]
            
            if post_conf_bars.empty:
                continue  # No bars available before cutoff, skip this trade
            
            if bias == 'bullish':
                entry_price = idr_high - (0.20 * idr_range)
                idr_std = day_bars['close'].std()
                take_profit = idr_high + idr_std
                side = 'long'
                
                # Find when price reaches entry (retraces DOWN to entry level)
                entry_bars = post_conf_bars[post_conf_bars['close'] <= entry_price]
                if entry_bars.empty:
                    result = "No entry - price didn't reach entry level"
                    pnl = 0
                    exit_reason = "N/A"
                    actual_entry_time = None
                    exit_time = None
                else:
                    actual_entry_time = entry_bars.index[0]
                    contracts = calculate_position_size(entry_price, stop_loss, balance)
                    pnl, exit_reason, exit_time = simulate_trade(entry_price, stop_loss, take_profit, side, contracts, df, actual_entry_time)
                    result = f"${pnl:.2f}"
                    balance += pnl
            else:  # bearish
                entry_price = idr_low + (0.20 * idr_range)
                idr_std = day_bars['close'].std()
                take_profit = idr_low - idr_std
                side = 'short'
                
                # Find when price reaches entry (retraces UP to entry level)
                entry_bars = post_conf_bars[post_conf_bars['close'] >= entry_price]
                if entry_bars.empty:
                    result = "No entry - price didn't reach entry level"
                    pnl = 0
                    exit_reason = "N/A"
                    actual_entry_time = None
                    exit_time = None
                else:
                    actual_entry_time = entry_bars.index[0]
                    contracts = calculate_position_size(entry_price, stop_loss, balance)
                    pnl, exit_reason, exit_time = simulate_trade(entry_price, stop_loss, take_profit, side, contracts, df, actual_entry_time)
                    result = f"${pnl:.2f}"
                    balance += pnl
            
            # Calculate risk metrics
            if 'No entry' not in result:
                stop_distance = abs(entry_price - stop_loss)
                risk_dollars = VIRTUAL_BALANCE * RISK_PCT
                risk_per_contract = stop_distance * POINT_VALUE
                actual_contracts = calculate_position_size(entry_price, stop_loss, balance if 'No entry' not in result else VIRTUAL_BALANCE)
                actual_risk = stop_distance * actual_contracts * POINT_VALUE
            else:
                stop_distance = 0
                risk_dollars = 0
                risk_per_contract = 0
                actual_contracts = 0
                actual_risk = 0
            
            # Record result
            results.append({
                'Date': date,
                'Session': session.upper(),
                'Confirmation': conf_time.strftime('%H:%M:%S'),
                'Entry Time': actual_entry_time.strftime('%H:%M:%S') if actual_entry_time else 'N/A',
                'Exit Time': exit_time.strftime('%H:%M:%S') if exit_time else 'N/A',
                'Bias': bias.upper(),
                'DR High': dr_high,
                'DR Low': dr_low,
                'IDR High': idr_high,
                'IDR Low': idr_low,
                'IDR Range': idr_range,
                'Entry': entry_price,
                'Stop': stop_loss,
                'TP': take_profit,
                'Stop Distance': stop_distance,
                'Contracts': actual_contracts,
                'Risk $': actual_risk,
                'PnL': pnl,
                'Exit': exit_reason,
                'Balance': balance
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
    df = fetch_historical_data(contract_id, days_back=14)
    
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
    
    # Show each trade with full details
    for idx, row in results_df.iterrows():
        print(f"\n{'='*80}")
        print(f"TRADE #{idx+1}: {row['Date']} - {row['Session']} SESSION - {row['Bias']}")
        print(f"{'='*80}")
        
        print(f"\n📊 RANGE LEVELS:")
        print(f"  DR High:  {row['DR High']:.2f}")
        print(f"  DR Low:   {row['DR Low']:.2f}")
        print(f"  IDR High: {row['IDR High']:.2f}")
        print(f"  IDR Low:  {row['IDR Low']:.2f}")
        print(f"  IDR Range: {row['IDR Range']:.2f} points")
        
        print(f"\n🎯 ENTRY SETUP:")
        print(f"  Confirmation Time: {row['Confirmation']} EST")
        print(f"  Entry Time: {row['Entry Time']} EST")
        print(f"  Exit Time: {row['Exit Time']} EST")
        print(f"  Direction: {row['Bias']}")
        print(f"  Entry Price: {row['Entry']:.2f}")
        print(f"  Stop Loss: {row['Stop']:.2f}")
        print(f"  Take Profit: {row['TP']:.2f}")
        print(f"  Stop Distance: {row['Stop Distance']:.2f} points")
        
        print(f"\n💰 RISK MANAGEMENT:")
        print(f"  Account Balance: ${row['Balance'] - row['PnL']:.2f}")
        print(f"  Risk % Allocated: {RISK_PCT*100:.0f}%")
        print(f"  Risk per Contract: ${row['Stop Distance'] * POINT_VALUE:.2f}")
        print(f"  Position Size: {row['Contracts']} micro contracts")
        print(f"  Total $ Risk: ${row['Risk $']:.2f}")
        
        print(f"\n📈 TRADE RESULT:")
        print(f"  Exit: {row['Exit']}")
        pnl_color = "+" if row['PnL'] >= 0 else ""
        print(f"  P&L: {pnl_color}${row['PnL']:.2f}")
        print(f"  New Balance: ${row['Balance']:.2f}")
        print(f"  Return: {(row['PnL']/(row['Balance'] - row['PnL']))*100:.1f}%")
    
    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total Trades: {len(results_df)}")
    
    # Calculate wins/losses
    wins = len(results_df[results_df['PnL'] > 0])
    losses = len(results_df[results_df['PnL'] < 0])
    no_entry = len(results_df[results_df['PnL'] == 0])
    
    print(f"Wins: {wins}")
    print(f"Losses: {losses}")
    print(f"No Entry: {no_entry}")
    
    if wins + losses > 0:
        win_rate = (wins / (wins + losses)) * 100
        print(f"Win Rate: {win_rate:.1f}%")
    
    # Final P&L
    final_balance = float(results_df.iloc[-1]['Balance']) if not results_df.empty else VIRTUAL_BALANCE
    total_pnl = final_balance - VIRTUAL_BALANCE
    print(f"\nStarting Balance: ${VIRTUAL_BALANCE:.2f}")
    print(f"Ending Balance: ${final_balance:.2f}")
    print(f"Total P&L: ${total_pnl:.2f} ({(total_pnl/VIRTUAL_BALANCE)*100:.1f}%)")
    
    # Best and worst trades
    if not results_df.empty:
        best_trade = results_df.loc[results_df['PnL'].idxmax()]
        worst_trade = results_df.loc[results_df['PnL'].idxmin()]
        print(f"\nBest Trade: +${best_trade['PnL']:.2f} ({best_trade['Date']} {best_trade['Session']})")
        print(f"Worst Trade: -${abs(worst_trade['PnL']):.2f} ({worst_trade['Date']} {worst_trade['Session']})")
    
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

