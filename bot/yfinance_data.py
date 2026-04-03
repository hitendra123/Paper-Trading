"""
yfinance Data Module — fetches real NSE/BSE OHLCV data
Supported intervals: 1m, 2m, 5m, 15m, 30m, 60m, 1d
NSE stocks  : RELIANCE.NS, TCS.NS, INFY.NS, etc.
Indices     : ^NSEI (Nifty 50), ^NSEBANK (BankNifty)
"""
import pandas as pd
import yfinance as yf


# Map friendly names → yfinance tickers
INDEX_TICKERS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
}


def nse_ticker(symbol: str) -> str:
    """Convert plain NSE symbol to yfinance ticker."""
    symbol = symbol.upper().strip()
    if symbol in INDEX_TICKERS:
        return INDEX_TICKERS[symbol]
    if symbol.startswith("^") or symbol.endswith(".NS") or symbol.endswith(".BO"):
        return symbol
    return f"{symbol}.NS"


def fetch_ohlcv(symbol: str, interval: str = "5m", period: str = "1d") -> pd.DataFrame:
    """
    Fetch intraday OHLCV from yfinance.

    Returns a DataFrame with columns:
        date, open, high, low, close, volume
    Returns an empty DataFrame on failure.
    """
    ticker = nse_ticker(symbol)
    try:
        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
    except Exception:
        return pd.DataFrame()

    if raw.empty:
        return pd.DataFrame()

    # Flatten MultiIndex columns produced by yfinance ≥ 0.2
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    raw = raw.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    raw = raw[["open", "high", "low", "close", "volume"]].copy()
    raw.index.name = "date"
    raw = raw.reset_index()
    raw["date"] = pd.to_datetime(raw["date"])

    # Drop rows with NaN OHLC (sometimes at market open)
    raw = raw.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return raw


def get_live_price(symbol: str) -> float | None:
    """Return the latest close price for a symbol."""
    ticker = nse_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        return float(info.last_price)
    except Exception:
        return None
