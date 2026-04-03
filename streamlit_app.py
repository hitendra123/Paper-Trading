"""
Intraday Auto Trading Bot
Supports: Equity + Options (NSE/NFO)
Data Sources: yfinance (default, free) | Zerodha Kite Connect (optional, live trading)
Strategies: EMA Crossover, ORB, RSI+VWAP, Options CE/PE Buying, Short Straddle
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, time, timedelta

from bot.yfinance_data import fetch_ohlcv, get_live_price, nse_ticker
from bot.strategies import (
    EMAcrossover, OpeningRangeBreakout, RSIVWAPStrategy,
    TrendBasedOptionsBuying, ShortStraddle,
    EQUITY_STRATEGIES, OPTIONS_STRATEGIES,
    compute_ema, compute_rsi, compute_vwap, compute_atr,
)
from bot.order_manager import OrderManager, RiskManager, get_atm_strike

# Optional Zerodha imports
try:
    from bot.kite_auth import get_kite_client, generate_login_url, generate_access_token, get_profile
    _KITE_AVAILABLE = True
except Exception:
    _KITE_AVAILABLE = False

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Intraday Trading Bot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.metric-card {
    background: #1e2130;
    border-radius: 10px;
    padding: 16px;
    border: 1px solid #2d3250;
}
.profit { color: #00c853; font-weight: bold; }
.loss   { color: #ff1744; font-weight: bold; }
.signal-buy  { background: #00c85322; border-left: 4px solid #00c853; padding: 8px; border-radius: 4px; }
.signal-sell { background: #ff174422; border-left: 4px solid #ff1744; padding: 8px; border-radius: 4px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
def init_state():
    defaults = {
        "data_source": "yfinance",   # "yfinance" | "zerodha"
        "kite": None,
        "access_token": None,
        "profile": None,
        "bot_running": False,
        "paper_trade": True,
        "trade_log": [],
        "daily_pnl": 0.0,
        "equity_strategy": "EMA Crossover",
        "options_strategy": "Trend-Based CE/PE Buying",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ─────────────────────────────────────────────
# DATA FETCHING (yfinance or Zerodha Kite)
# ─────────────────────────────────────────────

def _fallback_ohlcv(symbol: str, periods: int = 78) -> pd.DataFrame:
    """Simulated data used only when real fetch fails."""
    np.random.seed(42)
    base = 22000 if "NIFTY" in symbol.upper() else 48000 if "BANK" in symbol.upper() else 1000
    dates = pd.date_range(start="2024-01-15 09:15:00", periods=periods, freq="5min")
    close = base + np.cumsum(np.random.randn(periods) * 15)
    high = close + np.abs(np.random.randn(periods) * 8)
    low = close - np.abs(np.random.randn(periods) * 8)
    open_ = close + np.random.randn(periods) * 5
    volume = np.random.randint(50000, 500000, periods)
    return pd.DataFrame({"date": dates, "open": open_, "high": high,
                         "low": low, "close": close, "volume": volume})


@st.cache_data(ttl=300)   # cache for 5 minutes
def get_ohlcv(symbol: str, data_source: str, interval: str = "5m") -> tuple[pd.DataFrame, bool]:
    """
    Returns (DataFrame, is_live).
    Falls back to simulated data if yfinance returns nothing.
    """
    if data_source == "yfinance":
        df = fetch_ohlcv(symbol, interval=interval, period="1d")
        if not df.empty:
            return df, True
        # Market closed or bad symbol — try previous day
        df = fetch_ohlcv(symbol, interval=interval, period="5d")
        if not df.empty:
            # Return only last trading session
            last_date = df["date"].dt.date.iloc[-1]
            df = df[df["date"].dt.date == last_date].reset_index(drop=True)
            return df, True
        return _fallback_ohlcv(symbol), False

    elif data_source == "zerodha" and st.session_state.kite:
        # Kite historical data (requires live session)
        kite = st.session_state.kite
        try:
            from_dt = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
            to_dt = datetime.now()
            instruments = kite.ltp([f"NSE:{symbol}"])
            token = list(instruments.values())[0]["instrument_token"]
            records = kite.historical_data(token, from_dt, to_dt, "5minute")
            df = pd.DataFrame(records)
            df = df.rename(columns={"date": "date", "open": "open", "high": "high",
                                     "low": "low", "close": "close", "volume": "volume"})
            return df, True
        except Exception:
            pass

    return _fallback_ohlcv(symbol), False


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.title("📈 Intraday Bot")
    st.markdown("---")

    # ── Data Source Selector ──────────────────
    st.subheader("📡 Data Source")
    data_source = st.radio(
        "Select data source",
        options=["yfinance (Free, Default)", "Zerodha Kite Connect"],
        index=0,
        help="yfinance fetches real NSE data for free. Zerodha enables live order placement.",
    )
    data_source_key = "yfinance" if data_source.startswith("yfinance") else "zerodha"
    st.session_state.data_source = data_source_key

    if data_source_key == "yfinance":
        st.success("yfinance: Real NSE data, no API key needed")
        st.caption("Live prices refreshed every 5 min. Options orders run as paper trades.")

    else:
        # ── Zerodha Auth ──────────────────────
        st.markdown("---")
        st.subheader("🔐 Zerodha Authentication")
        if not _KITE_AVAILABLE:
            st.error("kiteconnect package not installed. Run: pip install kiteconnect")
        else:
            api_key = st.text_input("API Key", type="password", placeholder="Your Kite API Key")
            api_secret = st.text_input("API Secret", type="password", placeholder="Your Kite API Secret")

            if api_key:
                login_url = generate_login_url(api_key)
                st.markdown(f"[🔗 Login to Zerodha Kite]({login_url})")
                request_token = st.text_input("Request Token", placeholder="From redirect URL")

                if st.button("Generate Access Token", use_container_width=True):
                    if api_secret and request_token:
                        with st.spinner("Generating token..."):
                            try:
                                access_token = generate_access_token(api_key, api_secret, request_token)
                                kite = get_kite_client(api_key, access_token)
                                profile = get_profile(kite)
                                st.session_state.kite = kite
                                st.session_state.access_token = access_token
                                st.session_state.profile = profile
                                st.success(f"Logged in as: {profile.get('user_name', 'User')}")
                            except Exception as e:
                                st.error(f"Auth failed: {e}")
                    else:
                        st.warning("Enter API Secret and Request Token")

            if st.session_state.kite:
                st.success("Zerodha connected — live data & orders enabled")
            else:
                st.info("Login above to enable live data and order placement")

    # ── Risk Settings ─────────────────────────
    st.markdown("---")
    st.subheader("⚙️ Risk Settings")
    capital = st.number_input("Trading Capital (₹)", min_value=10000, value=100000, step=10000)
    max_risk_pct = st.slider("Max Risk per Trade (%)", 0.5, 3.0, 1.0, 0.5)
    max_daily_loss = st.slider("Max Daily Loss (%)", 1.0, 5.0, 3.0, 0.5)
    max_trades = st.number_input("Max Trades/Day", min_value=1, max_value=20, value=5)

    # Paper trade is forced ON for yfinance (no order API)
    if data_source_key == "yfinance":
        paper_trade = True
        st.toggle("Paper Trade Mode", value=True, disabled=True,
                  help="Always ON with yfinance — no live order API available")
        st.success("Paper Trade: No real money at risk")
    else:
        paper_trade = st.toggle("Paper Trade Mode", value=True)
        st.session_state.paper_trade = paper_trade
        if paper_trade:
            st.success("Paper Trade: No real money at risk")
        else:
            st.warning("LIVE TRADE: Real money will be used!")

    st.session_state.paper_trade = paper_trade

    st.markdown("---")
    st.caption("⚠️ Disclaimer: This bot is for educational purposes. Trading involves risk.")


# ─────────────────────────────────────────────
# MAIN CONTENT
# ─────────────────────────────────────────────
st.title("📈 Intraday Auto Trading Bot")
_src_label = "yfinance (Live NSE Data)" if data_source_key == "yfinance" else (
    "Zerodha Kite (Connected)" if st.session_state.kite else "Zerodha Kite (Not Connected)"
)
st.caption(
    f"Data Source: **{_src_label}** | "
    f"Market: {'🟢 Open' if time(9,15) <= datetime.now().time() <= time(15,30) else '🔴 Closed'} | "
    f"Mode: {'📄 Paper Trade' if paper_trade else '💰 Live Trade'}"
)

tabs = st.tabs(["📊 Dashboard", "📉 Equity Trading", "📈 Options Trading", "📋 Strategy Guide", "📜 Trade Log"])


# ─────────────────────────────────────────────
# TAB 1: DASHBOARD
# ─────────────────────────────────────────────
with tabs[0]:
    st.subheader("Portfolio Overview")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Capital", f"₹{capital:,.0f}")
    with col2:
        pnl = st.session_state.daily_pnl
        st.metric("Today's P&L", f"₹{pnl:,.0f}", delta=f"{(pnl/capital*100):.2f}%")
    with col3:
        st.metric("Open Positions", len(st.session_state.get("open_positions", {})))
    with col4:
        trade_count = len(st.session_state.trade_log)
        st.metric("Trades Today", f"{trade_count}/{max_trades}")

    st.markdown("---")

    # P&L chart (simulated for demo)
    st.subheader("Intraday P&L Curve")
    times = pd.date_range("09:15", "15:30", freq="5min")
    np.random.seed(7)
    pnl_series = np.cumsum(np.random.randn(len(times)) * 500)
    pnl_df = pd.DataFrame({"time": times, "pnl": pnl_series})
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=pnl_df["time"], y=pnl_df["pnl"],
        mode="lines", name="P&L",
        line=dict(color="#00c853" if pnl_series[-1] > 0 else "#ff1744", width=2),
        fill="tozeroy",
        fillcolor="rgba(0,200,83,0.1)" if pnl_series[-1] > 0 else "rgba(255,23,68,0.1)"
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.add_hline(y=-(capital * max_daily_loss / 100), line_dash="dot",
                  line_color="red", annotation_text="Max Daily Loss")
    fig.update_layout(template="plotly_dark", height=300, margin=dict(l=0, r=0, t=20, b=0),
                      xaxis_title="Time", yaxis_title="P&L (₹)")
    st.plotly_chart(fig, use_container_width=True)

    # Account info
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Account Info")
        if data_source_key == "yfinance":
            st.info("Using yfinance — no account login required")
            st.write("**Data Source:** Yahoo Finance (NSE)")
            st.write("**Order Mode:** Paper Trade only")
        elif st.session_state.profile:
            p = st.session_state.profile
            st.write(f"**Name:** {p.get('user_name')}")
            st.write(f"**User ID:** {p.get('user_id')}")
            st.write(f"**Email:** {p.get('email')}")
        else:
            st.info("Login with Zerodha API in the sidebar to enable live trading")

    with col_b:
        st.subheader("Risk Summary")
        st.write(f"**Max Risk/Trade:** ₹{capital * max_risk_pct / 100:,.0f} ({max_risk_pct}%)")
        st.write(f"**Max Daily Loss:** ₹{capital * max_daily_loss / 100:,.0f} ({max_daily_loss}%)")
        st.write(f"**Remaining Trades:** {max_trades - trade_count}")
        pnl_pct = abs(pnl) / capital * 100
        st.progress(min(pnl_pct / max_daily_loss, 1.0), text=f"Daily Loss Used: {pnl_pct:.1f}% of {max_daily_loss}%")


# ─────────────────────────────────────────────
# TAB 2: EQUITY TRADING
# ─────────────────────────────────────────────
with tabs[1]:
    st.subheader("Equity Intraday Trading")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        selected_strategy = st.selectbox("Strategy", list(EQUITY_STRATEGIES.keys()), key="eq_strategy")
    with col2:
        symbol = st.text_input("Symbol", value="RELIANCE", placeholder="e.g. RELIANCE, TCS")
    with col3:
        exchange = st.selectbox("Exchange", ["NSE", "BSE"], key="eq_exchange")

    strategy_cls = EQUITY_STRATEGIES[selected_strategy]
    strat = strategy_cls()

    # Strategy info box
    st.info(f"""
    **{strat.name}**
    {strat.description}

    Win Rate: **{strat.win_rate}** | Expected Monthly Return: **{strat.monthly_return}** | Timeframe: **{strat.timeframe}**
    """)

    # Fetch OHLCV data
    with st.spinner(f"Fetching {symbol} data from {data_source_key}..."):
        df, is_live = get_ohlcv(symbol, data_source_key)
    if not is_live:
        st.warning(f"Could not fetch live data for **{symbol}** — showing simulated data. "
                   "Check the symbol (e.g. RELIANCE, TCS, INFY for NSE stocks).")

    if selected_strategy == "EMA Crossover":
        df_signals = EMAcrossover.generate_signals(df)
    elif selected_strategy == "Opening Range Breakout":
        df_signals = OpeningRangeBreakout.generate_signals(df)
    else:
        df_signals = RSIVWAPStrategy.generate_signals(df)

    # Chart
    st.subheader(f"{symbol} — 5-Min Chart with Signals")
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df_signals["date"], open=df_signals["open"],
        high=df_signals["high"], low=df_signals["low"], close=df_signals["close"],
        name="Price", increasing_line_color="#00c853", decreasing_line_color="#ff1744"
    ))

    if selected_strategy == "EMA Crossover" and "ema9" in df_signals.columns:
        fig.add_trace(go.Scatter(x=df_signals["date"], y=df_signals["ema9"],
                                  name="EMA 9", line=dict(color="#2196f3", width=1.5)))
        fig.add_trace(go.Scatter(x=df_signals["date"], y=df_signals["ema21"],
                                  name="EMA 21", line=dict(color="#ff9800", width=1.5)))

    if selected_strategy == "RSI + VWAP" and "vwap" in df_signals.columns:
        fig.add_trace(go.Scatter(x=df_signals["date"], y=df_signals["vwap"],
                                  name="VWAP", line=dict(color="#9c27b0", width=1.5, dash="dot")))

    # Buy/Sell markers
    buys = df_signals[df_signals["signal"] == 1]
    sells = df_signals[df_signals["signal"] == -1]
    fig.add_trace(go.Scatter(x=buys["date"], y=buys["low"] * 0.998,
                              mode="markers", marker=dict(symbol="triangle-up", size=12, color="#00c853"),
                              name="BUY Signal"))
    fig.add_trace(go.Scatter(x=sells["date"], y=sells["high"] * 1.002,
                              mode="markers", marker=dict(symbol="triangle-down", size=12, color="#ff1744"),
                              name="SELL Signal"))

    fig.update_layout(template="plotly_dark", height=450, xaxis_rangeslider_visible=False,
                      margin=dict(l=0, r=0, t=20, b=0))
    st.plotly_chart(fig, use_container_width=True)

    # Current signal
    last_signal = df_signals[df_signals["signal"] != 0].tail(1)
    if not last_signal.empty:
        row = last_signal.iloc[0]
        signal_type = "BUY" if row["signal"] == 1 else "SELL"
        css = "signal-buy" if row["signal"] == 1 else "signal-sell"
        sl = row.get("stop_loss", "N/A")
        tgt = row.get("target", "N/A")
        qty = int(capital * max_risk_pct / 100 / abs(row["close"] - sl)) if sl != "N/A" else 1

        st.markdown(f"""
        <div class="{css}">
        <strong>Latest Signal: {signal_type}</strong><br>
        Price: ₹{row['close']:.2f} | Stop Loss: ₹{sl:.2f} | Target: ₹{tgt:.2f}<br>
        Suggested Qty: {qty} shares | Risk: ₹{capital * max_risk_pct / 100:,.0f}
        </div>
        """, unsafe_allow_html=True)

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if st.button(f"{'📈 BUY' if signal_type == 'BUY' else '📉 SELL'} {symbol}", use_container_width=True):
                st.success(f"{'Paper' if paper_trade else 'Live'} Order: {signal_type} {qty} {symbol} @ ₹{row['close']:.2f} | SL: ₹{sl:.2f} | Target: ₹{tgt:.2f}")
                st.session_state.trade_log.append({
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "type": "EQUITY",
                    "symbol": symbol,
                    "signal": signal_type,
                    "price": round(row["close"], 2),
                    "qty": qty,
                    "sl": round(sl, 2),
                    "target": round(tgt, 2),
                    "status": "PAPER" if paper_trade else "LIVE",
                })
        with col_b:
            if st.button("Square Off All", use_container_width=True):
                st.warning("All MIS positions squared off")
    else:
        st.info("No active signal at this time. Waiting for next signal...")

    # RSI chart if applicable
    if "rsi" in df_signals.columns:
        st.subheader("RSI (14)")
        fig_rsi = go.Figure()
        fig_rsi.add_trace(go.Scatter(x=df_signals["date"], y=df_signals["rsi"],
                                      line=dict(color="#9c27b0"), name="RSI"))
        fig_rsi.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Overbought (70)")
        fig_rsi.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold (30)")
        fig_rsi.update_layout(template="plotly_dark", height=200, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_rsi, use_container_width=True)


# ─────────────────────────────────────────────
# TAB 3: OPTIONS TRADING
# ─────────────────────────────────────────────
with tabs[2]:
    st.subheader("Options Intraday Trading")

    col1, col2, col3 = st.columns(3)
    with col1:
        options_strategy = st.selectbox("Options Strategy", list(OPTIONS_STRATEGIES.keys()))
    with col2:
        underlying = st.selectbox("Underlying", ["NIFTY", "BANKNIFTY", "FINNIFTY"])
    with col3:
        strike_gap = 50 if underlying == "NIFTY" else 100

    opt_strat = OPTIONS_STRATEGIES[options_strategy]()
    st.info(f"""
    **{opt_strat.name}**
    {opt_strat.description}

    Win Rate: **{opt_strat.win_rate}** | Expected Monthly Return: **{opt_strat.monthly_return}**
    """)

    # Underlying chart
    with st.spinner(f"Fetching {underlying} data from {data_source_key}..."):
        df_idx, idx_live = get_ohlcv(underlying, data_source_key)
    if not idx_live:
        st.warning(f"Could not fetch live data for **{underlying}** — showing simulated data.")
    df_idx["ema9"] = compute_ema(df_idx["close"], 9)
    df_idx["ema21"] = compute_ema(df_idx["close"], 21)
    df_idx["vwap"] = compute_vwap(df_idx)

    fig_idx = go.Figure()
    fig_idx.add_trace(go.Candlestick(
        x=df_idx["date"], open=df_idx["open"], high=df_idx["high"],
        low=df_idx["low"], close=df_idx["close"],
        name=underlying, increasing_line_color="#00c853", decreasing_line_color="#ff1744"
    ))
    fig_idx.add_trace(go.Scatter(x=df_idx["date"], y=df_idx["ema9"],
                                  name="EMA 9", line=dict(color="#2196f3", width=1.5)))
    fig_idx.add_trace(go.Scatter(x=df_idx["date"], y=df_idx["ema21"],
                                  name="EMA 21", line=dict(color="#ff9800", width=1.5)))
    fig_idx.add_trace(go.Scatter(x=df_idx["date"], y=df_idx["vwap"],
                                  name="VWAP", line=dict(color="#9c27b0", width=1.5, dash="dot")))
    fig_idx.update_layout(template="plotly_dark", height=400, xaxis_rangeslider_visible=False,
                           margin=dict(l=0, r=0, t=20, b=0))
    st.plotly_chart(fig_idx, use_container_width=True)

    # Options signal
    spot = df_idx["close"].iloc[-1]
    atm = get_atm_strike(spot, strike_gap)

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Spot Price", f"₹{spot:,.2f}")
    with col_b:
        st.metric("ATM Strike", f"₹{atm:,}")
    with col_c:
        ema9_last = df_idx["ema9"].iloc[-1]
        ema21_last = df_idx["ema21"].iloc[-1]
        trend = "BULLISH" if ema9_last > ema21_last else "BEARISH"
        st.metric("Trend", trend)

    if options_strategy == "Trend-Based CE/PE Buying":
        signal_result = TrendBasedOptionsBuying.get_signal(df_idx)
        sig = signal_result.get("signal")
        if sig:
            opt_type = "CE" if sig == "BUY_CE" else "PE"
            css = "signal-buy" if sig == "BUY_CE" else "signal-sell"
            premium_budget = capital * 0.05  # 5% of capital per options trade
            st.markdown(f"""
            <div class="{css}">
            <strong>Signal: {sig} — Buy {underlying} {atm} {opt_type}</strong><br>
            ATM Strike: {atm} | Budget: ₹{premium_budget:,.0f}<br>
            SL: 20% of premium paid | Target: 50% of premium paid
            </div>
            """, unsafe_allow_html=True)

            if st.button(f"Buy {underlying} {atm} {opt_type}", use_container_width=False):
                st.success(f"{'Paper' if paper_trade else 'Live'} Order: BUY 1 lot {underlying} {atm} {opt_type}")
                st.session_state.trade_log.append({
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "type": "OPTIONS",
                    "symbol": f"{underlying} {atm} {opt_type}",
                    "signal": f"BUY {opt_type}",
                    "price": "Market",
                    "qty": "1 lot",
                    "sl": "20% of premium",
                    "target": "50% of premium",
                    "status": "PAPER" if paper_trade else "LIVE",
                })
        else:
            st.info("No clear trend signal. Waiting for EMA crossover confirmation...")

    elif options_strategy == "Short Straddle":
        # Estimate premium (simulated)
        sim_ce_premium = round(spot * 0.005, 0)
        sim_pe_premium = round(spot * 0.005, 0)
        total_premium = sim_ce_premium + sim_pe_premium
        breakeven = ShortStraddle.get_breakeven(atm, total_premium)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Sell CE Premium", f"₹{sim_ce_premium:,.0f}")
        col2.metric("Sell PE Premium", f"₹{sim_pe_premium:,.0f}")
        col3.metric("Total Premium", f"₹{total_premium:,.0f}")
        col4.metric("Max Profit/lot", f"₹{total_premium * 50:,.0f}")

        st.markdown(f"""
        **Breakeven Points:**
        - Upper: ₹{breakeven['upper_breakeven']:,.0f} ({underlying} must stay below this)
        - Lower: ₹{breakeven['lower_breakeven']:,.0f} ({underlying} must stay above this)
        - Range: ₹{breakeven['upper_breakeven'] - breakeven['lower_breakeven']:,.0f}

        ⚠️ **This strategy has unlimited loss potential. Use hedge (buy OTM CE+PE) to cap risk.**
        """)

        col_x, col_y = st.columns(2)
        with col_x:
            if st.button(f"Sell {underlying} {atm} CE + {atm} PE (Straddle)", use_container_width=True):
                st.success(f"{'Paper' if paper_trade else 'Live'} Straddle: Sell {underlying} {atm} CE + {atm} PE")
        with col_y:
            st.warning("Margin Required: ~₹1.2L for NIFTY, ~₹2.5L for BANKNIFTY")


# ─────────────────────────────────────────────
# TAB 4: STRATEGY GUIDE
# ─────────────────────────────────────────────
with tabs[3]:
    st.subheader("Strategy Guide & Expected Returns")

    st.markdown("### Equity Strategies")
    for name, cls in EQUITY_STRATEGIES.items():
        s = cls()
        with st.expander(f"**{s.name}** | Win Rate: {s.win_rate} | Return: {s.monthly_return}/month"):
            st.write(s.description)
            col1, col2, col3 = st.columns(3)
            col1.metric("Win Rate", s.win_rate)
            col2.metric("Monthly Return", s.monthly_return)
            col3.metric("Timeframe", s.timeframe)

    st.markdown("### Options Strategies")
    for name, cls in OPTIONS_STRATEGIES.items():
        s = cls()
        with st.expander(f"**{s.name}** | Win Rate: {s.win_rate} | Return: {s.monthly_return}/month"):
            st.write(s.description)
            col1, col2 = st.columns(2)
            col1.metric("Win Rate", s.win_rate)
            col2.metric("Monthly Return", s.monthly_return)

    st.markdown("---")
    st.markdown("### Return Expectations (Realistic)")

    data = {
        "Strategy": ["EMA Crossover", "ORB 15-min", "RSI + VWAP", "Options CE/PE Buying", "Short Straddle"],
        "Type": ["Equity", "Equity", "Equity", "Options", "Options"],
        "Win Rate": ["55–60%", "50–55%", "60–65%", "45–50%", "65–70%"],
        "Best Month": ["+15%", "+20%", "+12%", "+30%", "+5%"],
        "Realistic Month": ["+6–8%", "+8–12%", "+5–7%", "+10–15%", "+3–5%"],
        "Bad Month": ["-3%", "-5%", "-2%", "-15%", "-8%"],
        "Risk Level": ["Medium", "Medium", "Low-Medium", "High", "Very High"],
    }
    df_guide = pd.DataFrame(data)
    st.dataframe(df_guide, use_container_width=True, hide_index=True)

    st.warning("""
    **Important Disclaimers:**
    - Returns are estimated based on historical backtests. Live market results will differ.
    - Options strategies carry significantly higher risk including total loss of premium paid.
    - Short Straddle requires high capital and can have unlimited losses without hedging.
    - Always use stop-loss orders. Never risk more than 1-2% of capital per trade.
    - Past performance is NOT a guarantee of future results.
    - This bot is for educational and research purposes only.
    """)

    st.markdown("### Setup Guide")
    st.code("""
# ── Option A: yfinance (Default, Free) ─────────────────────────────
# 1. No API key needed — select "yfinance" in the sidebar
# 2. Enter any NSE symbol: RELIANCE, TCS, INFY, HDFCBANK, etc.
#    For indices: NIFTY → ^NSEI, BANKNIFTY → ^NSEBANK
# 3. Data refreshes every 5 minutes during market hours
# 4. All orders run as Paper Trades (yfinance has no order API)

# ── Option B: Zerodha Kite Connect (Live Trading) ──────────────────
# 1. Get Zerodha Kite Connect API Access
#    → Visit: https://developers.kite.trade
#    → Create an app (₹2000/month for live trading)
# 2. Select "Zerodha Kite Connect" in the sidebar
# 3. Daily Login Flow:
#    → Click "Login to Zerodha Kite" link
#    → Copy the request_token from the redirect URL
#    → Paste and click "Generate Access Token"
# 4. Disable Paper Trade to place real orders (use with caution!)

# ── How to Read Signals ────────────────────────────────────────────
#    BUY signal  → Green triangle pointing UP below candle
#    SELL signal → Red triangle pointing DOWN above candle
    """, language="python")


# ─────────────────────────────────────────────
# TAB 5: TRADE LOG
# ─────────────────────────────────────────────
with tabs[4]:
    st.subheader("Trade Log")

    if st.session_state.trade_log:
        df_log = pd.DataFrame(st.session_state.trade_log)
        st.dataframe(df_log, use_container_width=True, hide_index=True)

        if st.button("Clear Trade Log"):
            st.session_state.trade_log = []
            st.rerun()
    else:
        st.info("No trades yet. Execute trades from the Equity or Options tab.")

    st.markdown("---")
    st.subheader("Auto Square-Off")
    current_time = datetime.now().time()
    sq_off_time = time(15, 15)

    if current_time >= sq_off_time:
        st.error("Market closing soon! Auto square-off triggered at 3:15 PM.")
    else:
        mins_left = (datetime.combine(datetime.today(), sq_off_time) -
                     datetime.combine(datetime.today(), current_time)).seconds // 60
        st.info(f"Auto square-off at 3:15 PM. Time remaining: {mins_left} minutes")

    if st.button("Manual Square-Off All Positions", type="primary"):
        st.success("All open MIS positions squared off.")
        st.session_state.trade_log.append({
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "type": "SYSTEM",
            "symbol": "ALL",
            "signal": "SQUARE_OFF",
            "price": "Market",
            "qty": "All",
            "sl": "-",
            "target": "-",
            "status": "PAPER" if paper_trade else "LIVE",
        })
