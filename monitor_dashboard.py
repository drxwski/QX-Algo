"""
Streamlit Monitoring Dashboard for TopstepX Algo
Clean interface with Live Output and Current Performance
"""
import streamlit as st
import pandas as pd
import time
import threading
import os
from datetime import datetime
import pytz
from topstepx_client import authenticate
from topstepx_market_client import TopstepXMarketClient

# Page config
st.set_page_config(
    page_title="QX Algo Monitor",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .big-metric { font-size: 24px; font-weight: bold; }
    .status-running { color: #00ff00; font-weight: bold; font-size: 18px; }
    .status-stopped { color: #ff0000; font-weight: bold; font-size: 18px; }
    .profit { color: #00ff00; font-weight: bold; }
    .loss { color: #ff0000; font-weight: bold; }
    .console-output { 
        background-color: #1e1e1e; 
        padding: 15px; 
        border-radius: 5px;
        font-family: 'Courier New', monospace;
        font-size: 13px;
        max-height: 400px;
        overflow-y: auto;
    }
    .perf-section {
        background-color: #2b2b2b;
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'algo_running' not in st.session_state:
    st.session_state.algo_running = False
if 'algo_thread' not in st.session_state:
    st.session_state.algo_thread = None
if 'client' not in st.session_state:
    st.session_state.client = None
if 'console_output' not in st.session_state:
    st.session_state.console_output = []

def run_algo():
    """Run the algo in background thread"""
    try:
        os.environ['TOPSTEPX_USERNAME'] = 'AndrewTy'
        os.environ['TOPSTEPX_API_KEY'] = 'TZx4ZPH51dg9nhwliaOKB7cslWE2BXwiBhH2t8fj21s='
        
        token = authenticate()
        client = TopstepXMarketClient(token)
        st.session_state.client = client
        
        client.run_forever()
    except Exception as e:
        st.session_state.console_output.append(f"❌ ERROR: {e}")
        st.session_state.algo_running = False

def start_algo():
    if not st.session_state.algo_running:
        st.session_state.algo_running = True
        st.session_state.console_output = ["🚀 Algo starting..."]
        thread = threading.Thread(target=run_algo, daemon=True)
        thread.start()
        st.session_state.algo_thread = thread

def stop_algo():
    if st.session_state.algo_running:
        st.session_state.algo_running = False
        st.session_state.console_output.append("⏹️ Algo stopped by user")
        st.session_state.client = None

# ============================================================================
# HEADER
# ============================================================================
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    st.title("📊 QX Algo Monitor")

with col2:
    if st.session_state.algo_running:
        st.markdown('<p class="status-running">● RUNNING</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="status-stopped">● STOPPED</p>', unsafe_allow_html=True)

with col3:
    eastern = pytz.timezone('US/Eastern')
    now_est = datetime.now(eastern)
    st.write(f"**{now_est.strftime('%H:%M:%S')} EST**")

st.divider()

# ============================================================================
# SIDEBAR - CONTROL PANEL
# ============================================================================
st.sidebar.header("🎛️ Control Panel")

if st.session_state.algo_running:
    if st.sidebar.button("🛑 STOP ALGO", type="primary", use_container_width=True):
        stop_algo()
        st.rerun()
else:
    if st.sidebar.button("▶️ START ALGO", type="primary", use_container_width=True):
        start_algo()
        time.sleep(2)
        st.rerun()

st.sidebar.divider()

auto_refresh = st.sidebar.checkbox("🔄 Auto-refresh (5s)", value=True)

if st.sidebar.button("🔃 Refresh Now", use_container_width=True):
    st.rerun()

st.sidebar.divider()

# Account Info
st.sidebar.header("💰 Account")
st.sidebar.metric("Balance", "$50,000")
st.sidebar.metric("Account", "50KTC-V2...")
st.sidebar.metric("Contract", "ES (ESZ5)")

# ============================================================================
# MAIN CONTENT
# ============================================================================

client = st.session_state.client

# ============================================================================
# SECTION 1: LIVE OUTPUT (Console-style)
# ============================================================================
st.header("📺 Live Output")

with st.container():
    if client and st.session_state.algo_running:
        eastern = pytz.timezone('US/Eastern')
        now_utc = datetime.utcnow()
        now_est = now_utc.replace(tzinfo=pytz.utc).astimezone(eastern)
        
        current_session, window, _ = client.get_current_session(now_utc)
        
        # Build console output
        console_lines = []
        console_lines.append(f"⏰ {now_est.strftime('%Y-%m-%d %H:%M:%S')} EST")
        console_lines.append("")
        
        if current_session:
            console_lines.append(f"📍 SESSION: {current_session.upper()}")
            console_lines.append(f"   Window: {window[0].strftime('%H:%M')} - {window[1].strftime('%H:%M')} EST")
            console_lines.append(f"   Trades today: {client.session_trades[current_session]}/2")
            console_lines.append("")
            
            # DR/IDR levels
            if not client.bars_df.empty:
                try:
                    boundaries = client.model.compute_boundaries(client.bars_df)
                    session_bounds = boundaries[current_session]
                    valid_bounds = session_bounds.dropna(subset=['dr_high', 'dr_low', 'idr_high', 'idr_low'])
                    
                    if not valid_bounds.empty:
                        dr_high = valid_bounds['dr_high'].iloc[-1]
                        dr_low = valid_bounds['dr_low'].iloc[-1]
                        idr_high = valid_bounds['idr_high'].iloc[-1]
                        idr_low = valid_bounds['idr_low'].iloc[-1]
                        current_price = client.bars_df['close'].iloc[-1]
                        
                        console_lines.append(f"📊 LEVELS:")
                        console_lines.append(f"   DR High:  {dr_high:.2f}")
                        console_lines.append(f"   DR Low:   {dr_low:.2f}")
                        console_lines.append(f"   IDR High: {idr_high:.2f}")
                        console_lines.append(f"   IDR Low:  {idr_low:.2f}")
                        console_lines.append("")
                        console_lines.append(f"💹 CURRENT PRICE: {current_price:.2f}")
                        console_lines.append("")
                except:
                    console_lines.append("⏳ Calculating levels...")
                    console_lines.append("")
        else:
            console_lines.append("⏸️  No active trading session")
            console_lines.append("")
            console_lines.append("   Next sessions:")
            console_lines.append("   • ODR: 3:00 AM - 8:00 AM")
            console_lines.append("   • RDR: 10:30 AM - 4:00 PM")
            console_lines.append("   • ADR: 8:30 PM - 1:00 AM")
            console_lines.append("")
        
        # Open trades
        if client.open_trades:
            console_lines.append("🔴 OPEN TRADES:")
            for trade in client.open_trades:
                console_lines.append(f"   Order #{trade['order_id']}")
                console_lines.append(f"   {trade['session'].upper()} {trade['bias'].upper()}")
                console_lines.append(f"   Entry: {trade['entry']:.2f} | Stop: {trade['stop']:.2f} | TP: {trade['tp']:.2f}")
                
                if not client.bars_df.empty:
                    current_price = client.bars_df['close'].iloc[-1]
                    if trade['bias'] == 'bullish':
                        pnl = (current_price - trade['entry']) * trade['contracts_remaining'] * 50
                    else:
                        pnl = (trade['entry'] - current_price) * trade['contracts_remaining'] * 50
                    
                    pnl_symbol = "📈" if pnl >= 0 else "📉"
                    console_lines.append(f"   {pnl_symbol} P&L: ${pnl:.2f}")
                
                if trade['trailing_stop_active']:
                    console_lines.append(f"   🎯 Trailing: {trade['trailing_stop_price']:.2f} (75% closed)")
                
                console_lines.append("")
        else:
            console_lines.append("✅ No open trades")
            console_lines.append("")
        
        # Status
        console_lines.append(f"🔄 Monitoring... (updates every 5 min)")
        console_lines.append(f"   Last update: {now_est.strftime('%H:%M:%S')}")
        
        # Display console
        console_text = "\n".join(console_lines)
        st.code(console_text, language=None)
        
    else:
        st.info("⏸️ Algo is stopped. Click START in the sidebar to begin.")

st.divider()

# ============================================================================
# SECTION 2: CURRENT PERFORMANCE
# ============================================================================
st.header("📈 Current Performance")

if client:
    # Performance metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        pnl = client.daily_pnl
        pnl_delta = f"+${pnl:.2f}" if pnl >= 0 else f"${pnl:.2f}"
        pnl_delta_color = "normal" if pnl >= 0 else "inverse"
        st.metric("Daily P&L", f"${pnl:.2f}", delta=pnl_delta, delta_color=pnl_delta_color)
    
    with col2:
        total_trades = sum(client.session_trades.values())
        st.metric("Total Trades Today", total_trades, delta=f"{total_trades}/6")
    
    with col3:
        win_rate = "N/A"
        if client.consecutive_wins + client.consecutive_losses > 0:
            total = client.consecutive_wins + client.consecutive_losses
            win_rate = f"{(client.consecutive_wins/total)*100:.1f}%"
        st.metric("Win Streak", client.consecutive_wins)
    
    with col4:
        loss_streak = client.consecutive_losses
        st.metric("Loss Streak", loss_streak, delta="⚠️" if loss_streak > 0 else "✓")
    
    st.divider()
    
    # Session breakdown
    st.subheader("📊 Session Breakdown")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.write("**RDR Session**")
        st.metric("Trades", f"{client.session_trades['rdr']}/2")
        if client.session_pnl['rdr'] != 0:
            st.metric("P&L", f"${client.session_pnl['rdr']:.2f}")
    
    with col2:
        st.write("**ODR Session**")
        st.metric("Trades", f"{client.session_trades['odr']}/2")
        if client.session_pnl['odr'] != 0:
            st.metric("P&L", f"${client.session_pnl['odr']:.2f}")
    
    with col3:
        st.write("**ADR Session**")
        st.metric("Trades", f"{client.session_trades['adr']}/2")
        if client.session_pnl['adr'] != 0:
            st.metric("P&L", f"${client.session_pnl['adr']:.2f}")
    
    st.divider()
    
    # Risk status
    st.subheader("⚠️ Risk Status")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        remaining_loss = 900 + client.daily_pnl  # How much more we can lose
        progress = (900 + client.daily_pnl) / 900
        st.progress(max(0, min(1, progress)))
        st.write(f"Daily Loss Buffer: ${remaining_loss:.2f} / $900")
    
    with col2:
        st.write(f"Current Risk Level: **{client.current_risk_percent * 100:.1f}%**")
        if client.consecutive_wins >= 2:
            st.success("🔥 Hot streak - risk increased")
        elif client.consecutive_losses > 0:
            st.warning("⚠️ Loss streak - risk reduced")
    
    with col3:
        st.write(f"Open Positions: **{len(client.open_trades)}**")
        if len(client.open_trades) > 0:
            st.info("Monitoring for exits...")
        else:
            st.success("No exposure")

else:
    st.info("⏸️ Start the algo to see performance metrics")
    
    # Show config when stopped
    st.subheader("⚙️ Configuration")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Account", "$50,000")
        st.metric("Position Size", "1 contract")
    
    with col2:
        st.metric("Max Daily Loss", "$900")
        st.metric("Base Risk", "1.5%")
    
    with col3:
        st.metric("Max Trades/Session", "2")
        st.metric("Poll Interval", "5 min")

st.divider()

# ============================================================================
# SECTION 3: TRADE LOG
# ============================================================================
st.header("📋 Trade History")

log_file = '/Users/andrew-tyson/Desktop/QX_ALGO/QX_Algo/trade_log.csv'
if os.path.exists(log_file):
    try:
        df = pd.read_csv(log_file)
        if not df.empty:
            st.dataframe(df.tail(20), use_container_width=True, height=300)
        else:
            st.info("No trades yet today")
    except:
        st.info("No trades yet today")
else:
    st.info("No trade history available")

# ============================================================================
# AUTO-REFRESH
# ============================================================================
if auto_refresh and st.session_state.algo_running:
    time.sleep(5)
    st.rerun()
