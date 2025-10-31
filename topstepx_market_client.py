import os
import time as pytime
from datetime import datetime, timedelta, time
import pandas as pd
from signal_module import QXSignalGenerator
from topstepx_client import authenticate, search_accounts, search_contracts, place_order, topstepx_request
import numpy as np
from collections import defaultdict
import pytz
import csv
from model_logic import QXRange

# === CONFIG ===
BAR_INTERVAL_MINUTES = 5
# Switch to Micro E-mini S&P 500 (MES)
CONTRACT_NAME = "MESZ5"
ACCOUNT_NAME = os.getenv("TOPSTEPX_ACCOUNT_NAME", "50KTC-V2-282714-47179717")
METRICS_PATH = os.path.join(os.path.dirname(__file__), 'es_dr_metrics.csv')
ROLLING_BARS = 500  # Number of bars to keep in memory
POLL_INTERVAL = 30  # 30 seconds (good balance of speed vs API calls)
BAR_UNIT = 2  # 2 = Minute
BAR_UNIT_NUMBER = 5  # 5-minute bars
BAR_LIMIT = 350  # Fetch last 350 bars each time
ENABLE_LIVE_TRADING = True  # Set to False to disable live trading (CURRENTLY ENABLED)

# Contract economics (MES)
TICK_SIZE = 0.25
TICK_VALUE = 1.25       # $1.25 per tick for MES
POINT_VALUE = 5.0       # $5 per point for MES

class TopstepXMarketClient:
    def __init__(self, jwt_token):
        self.jwt_token = jwt_token
        # FIXED ENTRY MODEL - No metrics CSV needed
        # self.metrics = pd.read_csv(METRICS_PATH)  # DISABLED for fixed model
        self.account_id = None
        self.contract_id = None
        self._init_account_contract()
        # QXSignalGenerator setup
        time_bins = pd.date_range('00:00', '23:59', freq='1min').strftime('%H:%M')
        mode_retrace_sd = pd.DataFrame({'threshold': [1.0]*len(time_bins)}, index=time_bins)
        mode_ext_sd = pd.DataFrame({'threshold': [1.0]*len(time_bins)}, index=time_bins)
        global_sd = 1.0
        self.signal_gen = QXSignalGenerator(mode_retrace_sd, mode_ext_sd, global_sd)
        self.model = QXRange(mode_retrace_sd, mode_ext_sd, global_sd)
        self.bars_df = pd.DataFrame()
        # Risk management state
        self.daily_pnl = 0
        self.session_trades = defaultdict(int)  # session_key -> count
        self.session_pnl = defaultdict(float)  # session_key -> pnl
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.current_risk_percent = 0.015  # Start at 1.5%
        self.last_trade_win = None
        self.today = datetime.now(pytz.utc).date()
        self.open_trades = []  # Track open trades for trailing stop, session end, etc.
        # Virtual balance used for risk sizing (user-defined risk base)
        self.account_balance_virtual = 2000.0
        self.account_balance = self.account_balance_virtual
        self.max_daily_loss = 2000  # Maximum daily loss limit (virtual P&L based)
        self.max_trades_per_session = 2  # Maximum trades per session
        self.last_confirmation_traded = {}  # session_key -> last confirmation timestamp
        self.last_dr_traded = {}  # session_key -> (dr_high, dr_low, bias) - prevent re-trading same DR break
        self.last_processed_bar = {}  # session_key -> last bar timestamp (bar-close trigger)
        self.session_cache = {}  # (session, date) -> {dr_high, dr_low, idr_high, idr_low, dr_end, idr_std}

    def reset_daily(self):
        self.daily_pnl = 0
        self.session_trades = defaultdict(int)
        self.session_pnl = defaultdict(float)
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.current_risk_percent = 0.015
        self.last_trade_win = None
        self.open_trades = []
        self.last_confirmation_traded = {}
        self.last_dr_traded = {}
        self.last_processed_bar = {}
        self.session_cache = {}
        print("[Risk] Daily/session counters reset.")

    def update_risk_state(self, trade_pnl):
        self.daily_pnl += trade_pnl
        # Update virtual balance for next position sizing
        self.account_balance_virtual += trade_pnl
        if trade_pnl > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            if self.consecutive_wins == 2:
                self.current_risk_percent = 0.02
            elif self.consecutive_wins > 2:
                self.current_risk_percent = 0.015
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            self.current_risk_percent = 0.01
        self.last_trade_win = trade_pnl > 0
        print(f"[Risk] Updated: daily_pnl={self.daily_pnl}, virt_balance=${self.account_balance_virtual:.2f}, consecutive_wins={self.consecutive_wins}, consecutive_losses={self.consecutive_losses}, risk%=12.00")

    def can_trade(self, session_key):
        if self.daily_pnl <= -self.max_daily_loss:
            print(f"[Risk] Max daily loss reached: {self.daily_pnl}")
            return False
        if self.session_trades[session_key] >= 2:
            print(f"[Risk] Max trades for session {session_key} reached.")
            return False
        return True

    def calculate_position_size(self, entry, stop):
        """Risk 7% of virtual balance using MES economics."""
        stop_distance = abs(entry - stop)                                # points
        ticks = stop_distance / TICK_SIZE
        risk_per_contract = ticks * TICK_VALUE                           # $ per contract at stop
        # 7% of current virtual balance
        risk_dollars = max(0, self.account_balance_virtual * 0.12)
        contracts = max(1, int(risk_dollars // risk_per_contract)) if risk_per_contract > 0 else 1
        print(
            f"[Risk] Position size calc | balance=${self.account_balance_virtual:.2f} | 12%=${risk_dollars:.2f} | stop={stop_distance:.2f}pts "
            f"({ticks:.1f} ticks) | risk/ct=${risk_per_contract:.2f} | size={contracts}"
        )
        return contracts

    def get_or_compute_session_boundaries(self, bars_df, session, now_est):
        """
        Get cached session boundaries or compute if not cached.
        
        Caches: {dr_high, dr_low, idr_high, idr_low, dr_end, idr_std}
        Key: (session, session_date_str) where session_date is the RANGE day
        (ADR note: for times between 00:00-01:00, session_date is previous day)
        
        Returns: dict or None if no valid boundaries
        """
        # Determine the session date (range formation day)
        session_date = now_est.date()
        if session == 'adr' and now_est.time() < time(1, 0):
            session_date = (now_est - timedelta(days=1)).date()

        cache_key = (session, session_date.isoformat())
        
        # Check cache first
        if cache_key in self.session_cache:
            print(f"[Cache] Using cached boundaries for {session.upper()} on {current_date}")
            return self.session_cache[cache_key]
        
        # Not cached - compute fresh
        print(f"[Cache] Computing fresh boundaries for {session.upper()} on {session_date}")
        boundaries = self.model.compute_boundaries(bars_df)
        session_bounds = boundaries[session]
        
        # Filter to the session_date ONLY (avoid picking yesterday's values)
        try:
            bounds_date = session_bounds.index.tz_convert('US/Eastern').date
        except Exception:
            bounds_date = session_bounds.index.date
        day_mask = bounds_date == session_date
        day_bounds = session_bounds[day_mask]

        # Get the most recent non-NaN boundaries for the session_date only
        valid_bounds = day_bounds.dropna(subset=['dr_high', 'dr_low', 'idr_high', 'idr_low'])
        if valid_bounds.empty:
            print(f"[Cache] No valid boundaries found for {session.upper()}")
            return None
        
        # Extract values
        dr_high = valid_bounds['dr_high'].iloc[-1]
        dr_low = valid_bounds['dr_low'].iloc[-1]
        idr_high = valid_bounds['idr_high'].iloc[-1]
        idr_low = valid_bounds['idr_low'].iloc[-1]
        dr_end = valid_bounds['dr_end'].iloc[-1]
        
        # Calculate IDR std dev for this session (used for take profit)
        dr_bars = self.get_session_window_bars(bars_df, session, now_est)
        if not dr_bars.empty:
            idr_std = dr_bars['close'].std()
        else:
            idr_range = idr_high - idr_low
            idr_std = idr_range * 0.3  # Fallback
        
        # Cache it
        cached = {
            'dr_high': dr_high,
            'dr_low': dr_low,
            'idr_high': idr_high,
            'idr_low': idr_low,
            'dr_end': dr_end,
            'idr_std': idr_std
        }
        self.session_cache[cache_key] = cached
        print(f"[Cache] Cached boundaries: DR {dr_high:.2f}/{dr_low:.2f} | IDR {idr_high:.2f}/{idr_low:.2f} | Std {idr_std:.2f}")
        
        return cached

    def _init_account_contract(self):
        token = self.jwt_token
        accounts = search_accounts(token)
        for acc in accounts:
            if acc.get('name') == ACCOUNT_NAME:
                self.account_id = acc['id']
                break
        if not self.account_id:
            raise Exception(f'Account {ACCOUNT_NAME} not found!')
        contracts = search_contracts(token, live=False)
        for c in contracts:
            desc = c.get('description', '')
            name = c.get('name')
            # Prefer exact symbol, then explicit Micro description
            if name == CONTRACT_NAME or 'Micro E-mini S&P 500' in desc:
                self.contract_id = c['id']
                break
        if not self.contract_id:
            raise Exception(f'Contract {CONTRACT_NAME} not found!')
        print(f'[TopstepXMarketClient] Using account_id={self.account_id}, contract_id={self.contract_id}')

    def fetch_latest_bars(self):
        now = datetime.now(pytz.utc)
        end_time = now.replace(second=0, microsecond=0)
        start_time = end_time - timedelta(minutes=BAR_UNIT_NUMBER * BAR_LIMIT)
        
        # Format datetimes for TopstepX API (expects UTC ISO format with Z suffix)
        # Remove timezone info before isoformat to avoid +00:00 in output
        start_time_str = start_time.replace(tzinfo=None).isoformat() + "Z"
        end_time_str = end_time.replace(tzinfo=None).isoformat() + "Z"
        
        payload = {
            "contractId": self.contract_id,
            "live": False,
            "startTime": start_time_str,
            "endTime": end_time_str,
            "unit": BAR_UNIT,
            "unitNumber": BAR_UNIT_NUMBER,
            "limit": BAR_LIMIT,
            "includePartialBar": False
        }
        resp = topstepx_request("POST", "/api/History/retrieveBars", token=self.jwt_token, json=payload)
        bars = resp.get("bars", [])
        if not bars:
            print("No bars returned.")
            return pd.DataFrame()
        df = pd.DataFrame(bars)
        df['t'] = pd.to_datetime(df['t'])
        # Convert to Eastern time (data is already UTC-aware)
        if df['t'].dt.tz is None:
            df['t'] = df['t'].dt.tz_localize('UTC')
        df['t'] = df['t'].dt.tz_convert('US/Eastern')
        df = df.rename(columns={'t': 'start', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
        df = df.set_index('start')
        df = df.sort_index()
        bars_loaded = len(df)
        print(f"[Bars] Loaded {bars_loaded} bars.")
        if bars_loaded < 300:
            print("[Warning] Less than 300 bars loaded! Session/price context may be incomplete.")
        print("[Bars] Last 5 bars:")
        print(df.tail(5)[['open','high','low','close','volume']])
        return df.tail(ROLLING_BARS)

    def get_current_session(self, now=None):
        # Use US/Eastern time for session logic
        # Trading windows from model_logic.py (lines 106-109)
        eastern = pytz.timezone('US/Eastern')
        if now is None:
            now = datetime.now(pytz.utc).astimezone(eastern)
        else:
            now = now.replace(tzinfo=pytz.utc).astimezone(eastern)
        t = now.time()
        
        # Trading session windows (when we look for confirmations and trade)
        # ODR Trading: 04:00-08:00, RDR Trading: 10:30-16:00, ADR Trading: 20:30-01:00
        if time(20,30) <= t or t < time(1,0):
            return 'adr', (time(20,30), time(1,0)), now
        elif time(4,0) <= t < time(8,0):
            return 'odr', (time(4,0), time(8,0)), now
        elif time(10,30) <= t < time(16,0):
            return 'rdr', (time(10,30), time(16,0)), now
        else:
            return None, None, now

    def get_session_window_bars(self, bars_df, session, now_est):
        # Use model_logic.py for session times - single source of truth
        session_times = {
            'adr': (self.model.adr_start, self.model.adr_end),
            'odr': (self.model.odr_start, self.model.odr_end),
            'rdr': (self.model.rdr_start, self.model.rdr_end),
        }
        start_t, end_t = session_times[session]
        # Convert index to EST
        est = pytz.timezone('US/Eastern')
        bars_df = bars_df.copy()
        bars_df['est_time'] = bars_df.index.tz_convert(est).time
        bars_df['est_date'] = bars_df.index.tz_convert(est).date
        
        # Only look at bars from the current day
        current_date = now_est.date()
        date_mask = bars_df['est_date'] == current_date
        
        # Select bars within the session window for the current date only
        if start_t < end_t:
            time_mask = (bars_df['est_time'] >= start_t) & (bars_df['est_time'] < end_t)
        else:  # Overnight session (e.g., ADR)
            time_mask = (bars_df['est_time'] >= start_t) | (bars_df['est_time'] < end_t)
        
        final_mask = date_mask & time_mask
        return bars_df[final_mask]

    def get_dr_window_end(self, session):
        # Use model_logic.py for DR window end times - single source of truth
        dr_window_ends = {
            'adr': self.model.adr_end,
            'odr': self.model.odr_end,
            'rdr': self.model.rdr_end,
        }
        return dr_window_ends[session]

    def log_trade(self, now_est, session, bias, entry_price, stop_loss, take_profit, contracts, order_id, result=None):
        log_path = os.path.join(os.path.dirname(__file__), 'trade_log.csv')
        log_fields = ['timestamp_est', 'session', 'bias', 'entry', 'stop', 'take_profit', 'size', 'order_id', 'result']
        log_row = [now_est.strftime('%Y-%m-%d %H:%M:%S'), session, bias, entry_price, stop_loss, take_profit, contracts, order_id, result or '']
        file_exists = os.path.isfile(log_path)
        with open(log_path, 'a', newline='') as csvfile:
            writer = csv.writer(csvfile)
            if not file_exists:
                writer.writerow(log_fields)
            writer.writerow(log_row)
        print(f"[Log] Trade logged: {log_row}")

    def run_forever(self):
        eastern = pytz.timezone('US/Eastern')
        print("="*70)
        print(f"🚀 TOPSTEPX ALGO STARTED")
        print("="*70)
        print("⚠️  2 trades/session | 10-min freshness | Market orders | Session independence")
        print("="*70)
        print("Starting polling loop for new bars...")
        print()
        while True:
            try:
                now_utc = datetime.now(pytz.utc)
                now_est = now_utc.replace(tzinfo=pytz.utc).astimezone(eastern)
                if now_est.date() != self.today:
                    self.today = now_est.date()
                    self.reset_daily()
                bars_df = self.fetch_latest_bars()
                if bars_df.empty or len(bars_df) < 10:
                    print("Not enough bars for signal generation.")
                else:
                    self.bars_df = bars_df
                    session, window, now_est = self.get_current_session(now_utc)
                    if session is None:
                        print(f"[Status] No active session at {now_est.strftime('%H:%M:%S')} EST")
                    else:
                        print(f"[Status] {now_est.strftime('%H:%M:%S')} EST | {session.upper()} session active")
                        self.run_signals_on_bars(bars_df, session, now_est)
                self.check_open_trades(now_utc)
            except Exception as e:
                print(f"Error in polling loop: {e}")
            print(f"Sleeping for {POLL_INTERVAL} seconds...")
            pytime.sleep(POLL_INTERVAL)

    def run_signals_on_bars(self, bars_df, current_session, now_est):
        # BAR-CLOSE TRIGGER: Only evaluate on new bar close (prevents mid-bar evaluation)
        latest_bar_time = bars_df.index[-1]
        last_processed = self.last_processed_bar.get(current_session)
        
        if last_processed is not None and latest_bar_time == last_processed:
            # Already processed this bar, skip evaluation
            return
        
        # Mark as processed BEFORE evaluation (idempotency)
        self.last_processed_bar[current_session] = latest_bar_time
        print(f"[Bar-Close] Processing new bar at {latest_bar_time.strftime('%H:%M:%S')}")
        
        # Get or compute cached session boundaries for the correct session-date
        cached_bounds = self.get_or_compute_session_boundaries(bars_df, current_session, now_est)
        
        if cached_bounds is None:
            print(f"[DR/IDR] No boundaries found for {current_session.upper()} session.")
            return
        
        # Extract cached values
        dr_high = cached_bounds['dr_high']
        dr_low = cached_bounds['dr_low']
        idr_high = cached_bounds['idr_high']
        idr_low = cached_bounds['idr_low']
        dr_end = cached_bounds['dr_end']
        idr_std = cached_bounds['idr_std']
        
        print(f"[DR/IDR] {current_session.upper()} | DR: {dr_high:.2f}/{dr_low:.2f} | IDR: {idr_high:.2f}/{idr_low:.2f}")
        
        # Only act if DR window is complete
        dr_window_end = self.get_dr_window_end(current_session)
        dr_window_end_dt = now_est.replace(hour=dr_window_end.hour, minute=dr_window_end.minute, second=0, microsecond=0)
            
        if now_est.time() < dr_window_end:
            print(f"[Wait] DR window for {current_session.upper()} not complete (ends at {dr_window_end})")
            return
            
        # Check for confirmations
        self.signal_gen.compute_boundaries(bars_df)
        confirmations = self.signal_gen.detect_confirmations(bars_df)
        session = current_session
        conf_col = f'{session}_confirmation_time'
        bias_col = f'{session}_confirmation_bias'
        conf_times = confirmations[conf_col].dropna()
        
        # Only consider confirmations after DR window end
        conf_times = [t for t in conf_times.index if t.tz_convert('US/Eastern') > dr_window_end_dt]
        
        if conf_times:
            # FIX: Read the actual confirmation time VALUE, not the bar timestamp
            conf_time_bar_index = conf_times[-1]
            conf_time = confirmations.loc[conf_time_bar_index, conf_col]
            
            print(f"[Confirmation] Detected at {conf_time} (checked at {now_est.strftime('%H:%M:%S')})")
            
            # SAFETY CHECK: Only trade fresh confirmations (within last 10 minutes)
            time_since_conf = (now_est - conf_time.tz_convert('US/Eastern')).total_seconds() / 60
            if time_since_conf > 10:
                print(f"[Status] Confirmation is {time_since_conf:.1f} minutes old - too old to trade (10 min limit)")
                return
            
            # SAFETY CHECK: Don't re-trade the same confirmation
            last_traded = self.last_confirmation_traded.get(session)
            if last_traded is not None and conf_time == last_traded:
                print(f"[Status] Already traded this confirmation for {session.upper()}")
                return
            
            # SAFETY CHECK: Don't enter new position if we already have one open for this session
            open_session_trades = [t for t in self.open_trades if t['session'] == session]
            if open_session_trades:
                print(f"[Status] Already have {len(open_session_trades)} open position(s) for {session.upper()} - no new entries")
                return
                
            bias = confirmations.loc[conf_time_bar_index, bias_col]
            
            # SAFETY CHECK: Verify bias is valid
            if bias not in ['bullish', 'bearish']:
                print(f"[ERROR] Invalid confirmation bias: {bias} - SKIPPING TRADE")
                return
            
            # SAFETY CHECK: Verify confirmation time is valid
            if pd.isna(conf_time):
                print(f"[ERROR] Invalid confirmation time - SKIPPING TRADE")
                return
                
            # Get current price
            current_price = bars_df['close'].iloc[-1]
            
            print(f"[CONFIRMATION] {bias.upper()} at {conf_time} | Current Price: {current_price:.2f} | DR: {dr_high:.2f}/{dr_low:.2f}")
            
            # SAFETY CHECK: Don't re-trade the same DR break - use date+session key so each day's session is independent
            today_date = now_est.date()
            session_date_key = f"{session}_{today_date}"
            last_dr = self.last_dr_traded.get(session_date_key)
            if last_dr is not None:
                last_dr_high, last_dr_low, last_bias = last_dr
                # Consider it the "same DR" if within 0.5 points (one tick = 0.25)
                if abs(dr_high - last_dr_high) < 0.5 and abs(dr_low - last_dr_low) < 0.5 and bias == last_bias:
                    print(f"[Status] Already traded this DR break for {session.upper()} today ({bias} @ {dr_high:.2f}/{dr_low:.2f})")
                    return
            
            # Risk checks
            if not self.can_trade(session):
                print(f"[Risk] Cannot trade: risk management blocked trade for {session.upper()}")
                print(f"[Risk] Current session trades: {self.session_trades[session]}/2")
                print(f"[Risk] Daily P&L: ${self.daily_pnl:.2f}")
                return
                
            # ═══════════════════════════════════════════════════════════
            # FIXED ENTRY MODEL (Testing Phase)
            # ═══════════════════════════════════════════════════════════
            # Entry: 20% of IDR range after confirmation
            # Stop Loss: 2 points under/above 50% of IDR range
            # Take Profit: 75% at 1 standard deviation of IDR
            # Trailing: 25% with 5-point trail until hit or session end
            # ═══════════════════════════════════════════════════════════
            
            idr_range = idr_high - idr_low
            idr_midpoint = idr_low + (0.50 * idr_range)  # 50% of IDR
            
            # Use cached IDR std dev (already computed in get_or_compute_session_boundaries)
            # idr_std is available from cached_bounds
            
            if bias == 'bullish':
                # Entry: 20% retrace from IDR high
                entry_price = idr_high - (0.20 * idr_range)
                
                # Stop Loss: 2 points below 50% of IDR
                stop_loss = idr_midpoint - 2.0
                
                # Take Profit: 1 std deviation above IDR high
                take_profit = idr_high + idr_std
                
                side = 2  # BUY
                
                # SAFETY CHECK: If price already hit 1SD target, we missed the move - skip this session
                if current_price >= take_profit:
                    print(f"[SKIP] Bullish - price already at target {take_profit:.2f} (current: {current_price:.2f}) - MOVE MISSED")
                    self.session_trades[session] += 1  # Count it to prevent retry
                    return
                
                # Check if price has retraced to entry level
                if current_price > entry_price:
                    print(f"[WAIT] Bullish - waiting for retrace to {entry_price:.2f} (current: {current_price:.2f})")
                    return
                    
            else:  # bearish
                # Entry: 20% retrace from IDR low
                entry_price = idr_low + (0.20 * idr_range)
                
                # Stop Loss: 2 points above 50% of IDR
                stop_loss = idr_midpoint + 2.0
                
                # Take Profit: 1 std deviation below IDR low
                take_profit = idr_low - idr_std
                
                side = 1  # SELL
                
                # Check if price has retraced to entry level
                if current_price < entry_price:
                    print(f"[WAIT] Bearish - waiting for retrace to {entry_price:.2f} (current: {current_price:.2f})")
                    return
                    
            contracts = self.calculate_position_size(entry_price, stop_loss)
            
            # Print signal with fixed model details
            print(f"\n{'='*70}")
            print(f"[SIGNAL] {session.upper()} {bias.upper()} CONFIRMATION")
            print(f"{'='*70}")
            print(f"  IDR Range: {idr_range:.2f} points")
            print(f"  IDR High: {idr_high:.2f} | IDR Low: {idr_low:.2f}")
            print(f"  IDR Midpoint: {idr_midpoint:.2f}")
            print(f"  IDR Std Dev: {idr_std:.2f}")
            print(f"  Entry (20% retrace): {entry_price:.2f}")
            print(f"  Stop Loss (2pts from 50%): {stop_loss:.2f}")
            print(f"  Take Profit (1 std dev): {take_profit:.2f}")
            print(f"  Position Size: {contracts} contract(s)")
            total_risk = abs(entry_price - stop_loss) * contracts * POINT_VALUE
            tp_value_75 = max(0, (take_profit - entry_price) * int(contracts * 0.75) * POINT_VALUE) if bias == 'bullish' else max(0, (entry_price - take_profit) * int(contracts * 0.75) * POINT_VALUE)
            print(f"  Risk: ${total_risk:.2f}")
            print(f"  75% TP return (value): ${tp_value_75:.2f}")
            print(f"{'='*70}\n")
            
            order_id = ''
            if ENABLE_LIVE_TRADING:
                try:
                    print(f"[TRADE] Placing MARKET order (price hit {entry_price:.2f})...")
                    order_resp = place_order(
                        account_id=self.account_id,
                        contract_id=self.contract_id,
                        size=contracts,
                        side=side,
                        order_type=2,
                        token=self.jwt_token
                    )
                    
                    if order_resp and 'orderId' in order_resp:
                        order_id = order_resp.get('orderId')
                        print(f"✓ Market order placed: ID {order_id}")
                        self.open_trades.append({
                            'session': session,
                            'entry': entry_price,
                            'stop': stop_loss,
                            'tp': take_profit,
                            'side': side,
                            'bias': bias,
                            'contracts': contracts,
                            'contracts_remaining': contracts,
                            'open_time': datetime.now(pytz.utc),
                            'partial_taken': False,
                            'trailing_stop_active': False,
                            'trailing_stop_price': None,
                            'highest_price': entry_price if bias == 'bullish' else None,
                            'lowest_price': entry_price if bias == 'bearish' else None,
                            'order_id': order_id,
                        })
                        self.log_trade(now_est, session, bias, entry_price, stop_loss, take_profit, contracts, order_id)
                        self.session_trades[session] += 1
                        self.last_confirmation_traded[session] = conf_time
                        self.last_dr_traded[session_date_key] = (dr_high, dr_low, bias)  # Track DR (date+session specific)
                        print(f"[Risk] Session trade count for {session.upper()}: {self.session_trades[session]}/2")
                    else:
                        print(f"❌ Order failed: {order_resp}")
                        self.log_trade(now_est, session, bias, entry_price, stop_loss, take_profit, contracts, 'FAILED')
                        # Still increment counter to prevent retry spam
                        self.session_trades[session] += 1
                        self.last_confirmation_traded[session] = conf_time
                        self.last_dr_traded[session_date_key] = (dr_high, dr_low, bias)  # Track DR (date+session specific)
                        print(f"[Risk] Session trade count for {session.upper()}: {self.session_trades[session]}/2 (FAILED ORDER)")
                except Exception as e:
                    print(f"❌ ERROR: {e}")
                    self.log_trade(now_est, session, bias, entry_price, stop_loss, take_profit, contracts, f'ERROR: {e}')
                    # Still increment counter to prevent retry spam
                    self.session_trades[session] += 1
                    self.last_confirmation_traded[session] = conf_time
                    self.last_dr_traded[session_date_key] = (dr_high, dr_low, bias)  # Track DR (date+session specific)
                    print(f"[Risk] Session trade count for {session.upper()}: {self.session_trades[session]}/2 (ERROR)")
            else:
                print("[PAPER] Trade logged only")
                self.log_trade(now_est, session, bias, entry_price, stop_loss, take_profit, contracts, 'PAPER')
                self.session_trades[session] += 1
                self.last_confirmation_traded[session] = conf_time
                self.last_dr_traded[session_date_key] = (dr_high, dr_low, bias)  # Track DR (date+session specific)
        else:
            print(f"[Status] No confirmation for {session.upper()} at this time")

    def check_open_trades(self, now):
        """
        Check open trades for exits:
        1. Take 75% profit at target (1 std dev)
        2. Trail remaining 25% with 5-point trailing stop
        3. Close all at stop loss
        4. Close all at session end
        """
        eastern = pytz.timezone('US/Eastern')
        now_est = now.replace(tzinfo=pytz.utc).astimezone(eastern)
        
        # Get current price (use latest bar from bars_df)
        if self.bars_df.empty:
            return
        current_price = self.bars_df['close'].iloc[-1]
        
        for trade in list(self.open_trades):
            order_id = trade['order_id']
            bias = trade['bias']
            entry = trade['entry']
            stop = trade['stop']
            tp = trade['tp']
            contracts_remaining = trade['contracts_remaining']
            
            # Check if session ended (1 hour after open)
            time_in_trade = (now - trade['open_time']).total_seconds()
            if time_in_trade > 3600:  # 1 hour limit
                print(f"\n[EXIT] Time limit (1hr) reached for Order {order_id}")
                print(f"  Closing {contracts_remaining} contract(s) at market")
                # Calculate P&L (simulated for now)
                if bias == 'bullish':
                    pnl = (current_price - entry) * contracts_remaining * POINT_VALUE
                else:
                    pnl = (entry - current_price) * contracts_remaining * POINT_VALUE
                print(f"  Estimated P&L: ${pnl:.2f}")
                self.update_risk_state(pnl)
                self.open_trades.remove(trade)
                continue
            
            # === BULLISH TRADE LOGIC ===
            if bias == 'bullish':
                # Update highest price seen
                if trade['highest_price'] is None or current_price > trade['highest_price']:
                    trade['highest_price'] = current_price
                
                # Check stop loss
                if current_price <= stop:
                    print(f"\n[EXIT] Stop Loss hit for Order {order_id}")
                    print(f"  Price: {current_price:.2f} <= Stop: {stop:.2f}")
                    pnl = (current_price - entry) * contracts_remaining * POINT_VALUE
                    print(f"  Loss: ${pnl:.2f}")
                    self.update_risk_state(pnl)
                    self.open_trades.remove(trade)
                    continue
                
                # Check take profit (75% exit)
                if current_price >= tp and not trade['partial_taken']:
                    contracts_to_close = int(trade['contracts'] * 0.75)
                    if contracts_to_close > 0:
                        print(f"\n[EXIT] Take Profit hit for Order {order_id}")
                        print(f"  Price: {current_price:.2f} >= Target: {tp:.2f}")
                        print(f"  Closing 75% ({contracts_to_close} contracts)")
                        partial_pnl = (current_price - entry) * contracts_to_close * POINT_VALUE
                        print(f"  Profit: ${partial_pnl:.2f}")
                        
                        trade['partial_taken'] = True
                        trade['contracts_remaining'] = trade['contracts'] - contracts_to_close
                        trade['trailing_stop_active'] = True
                        trade['trailing_stop_price'] = current_price - 5.0  # 5-point trail
                        
                        print(f"  Remaining: {trade['contracts_remaining']} contract(s)")
                        print(f"  Trailing stop activated at: {trade['trailing_stop_price']:.2f}")
                        self.update_risk_state(partial_pnl)
                
                # Check trailing stop (for remaining 25%)
                if trade['trailing_stop_active']:
                    # Update trailing stop (5 points behind highest)
                    new_trail = trade['highest_price'] - 5.0
                    if new_trail > trade['trailing_stop_price']:
                        trade['trailing_stop_price'] = new_trail
                        print(f"  [Trail Updated] Order {order_id}: {trade['trailing_stop_price']:.2f}")
                    
                    # Check if trailing stop hit
                    if current_price <= trade['trailing_stop_price']:
                        print(f"\n[EXIT] Trailing Stop hit for Order {order_id}")
                        print(f"  Price: {current_price:.2f} <= Trail: {trade['trailing_stop_price']:.2f}")
                        remaining_pnl = (current_price - entry) * contracts_remaining * POINT_VALUE
                        print(f"  Profit: ${remaining_pnl:.2f}")
                        self.update_risk_state(remaining_pnl)
                        self.open_trades.remove(trade)
            
            # === BEARISH TRADE LOGIC ===
            else:  # bearish
                # Update lowest price seen
                if trade['lowest_price'] is None or current_price < trade['lowest_price']:
                    trade['lowest_price'] = current_price
                
                # Check stop loss
                if current_price >= stop:
                    print(f"\n[EXIT] Stop Loss hit for Order {order_id}")
                    print(f"  Price: {current_price:.2f} >= Stop: {stop:.2f}")
                    pnl = (entry - current_price) * contracts_remaining * POINT_VALUE
                    print(f"  Loss: ${pnl:.2f}")
                    self.update_risk_state(pnl)
                    self.open_trades.remove(trade)
                    continue
                
                # Check take profit (75% exit)
                if current_price <= tp and not trade['partial_taken']:
                    contracts_to_close = int(trade['contracts'] * 0.75)
                    if contracts_to_close > 0:
                        print(f"\n[EXIT] Take Profit hit for Order {order_id}")
                        print(f"  Price: {current_price:.2f} <= Target: {tp:.2f}")
                        print(f"  Closing 75% ({contracts_to_close} contracts)")
                        partial_pnl = (entry - current_price) * contracts_to_close * POINT_VALUE
                        print(f"  Profit: ${partial_pnl:.2f}")
                        
                        trade['partial_taken'] = True
                        trade['contracts_remaining'] = trade['contracts'] - contracts_to_close
                        trade['trailing_stop_active'] = True
                        trade['trailing_stop_price'] = current_price + 5.0  # 5-point trail
                        
                        print(f"  Remaining: {trade['contracts_remaining']} contract(s)")
                        print(f"  Trailing stop activated at: {trade['trailing_stop_price']:.2f}")
                        self.update_risk_state(partial_pnl)
                
                # Check trailing stop (for remaining 25%)
                if trade['trailing_stop_active']:
                    # Update trailing stop (5 points above lowest)
                    new_trail = trade['lowest_price'] + 5.0
                    if new_trail < trade['trailing_stop_price']:
                        trade['trailing_stop_price'] = new_trail
                        print(f"  [Trail Updated] Order {order_id}: {trade['trailing_stop_price']:.2f}")
                    
                    # Check if trailing stop hit
                    if current_price >= trade['trailing_stop_price']:
                        print(f"\n[EXIT] Trailing Stop hit for Order {order_id}")
                        print(f"  Price: {current_price:.2f} >= Trail: {trade['trailing_stop_price']:.2f}")
                        remaining_pnl = (entry - current_price) * contracts_remaining * POINT_VALUE
                        print(f"  Profit: ${remaining_pnl:.2f}")
                        self.update_risk_state(remaining_pnl)
                        self.open_trades.remove(trade)

if __name__ == "__main__":
    jwt_token = os.getenv("TOPSTEPX_JWT")
    if not jwt_token:
        from topstepx_client import authenticate
        jwt_token = authenticate()
    client = TopstepXMarketClient(jwt_token)
    client.run_forever() 