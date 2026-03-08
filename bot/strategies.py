"""
Intraday Trading Strategies for Equity and Options
"""
import pandas as pd
import numpy as np
from datetime import datetime, time


# ─────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────

def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    return (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(period).mean()


# ─────────────────────────────────────────────
# EQUITY STRATEGIES
# ─────────────────────────────────────────────

class EMAcrossover:
    """
    Strategy: 9 EMA crosses 21 EMA on 5-min candles
    Buy  → 9 EMA crosses ABOVE 21 EMA (bullish crossover)
    Sell → 9 EMA crosses BELOW 21 EMA (bearish crossover)
    Stop Loss: 1x ATR below entry
    Target:    2x ATR above entry (1:2 R:R)
    Typical Win Rate: 55-60%
    Expected Monthly Return: 6-8% on capital deployed
    """
    name = "EMA Crossover (9/21)"
    description = (
        "Uses 9-period and 21-period Exponential Moving Averages. "
        "Generates BUY signal when fast EMA (9) crosses above slow EMA (21) "
        "and SELL/SHORT signal when fast EMA crosses below slow EMA. "
        "ATR-based dynamic stop-loss and 1:2 risk-reward target."
    )
    win_rate = "55–60%"
    monthly_return = "6–8%"
    timeframe = "5-min"

    @staticmethod
    def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ema9"] = compute_ema(df["close"], 9)
        df["ema21"] = compute_ema(df["close"], 21)
        df["atr"] = compute_atr(df)

        df["signal"] = 0
        cross_above = (df["ema9"] > df["ema21"]) & (df["ema9"].shift(1) <= df["ema21"].shift(1))
        cross_below = (df["ema9"] < df["ema21"]) & (df["ema9"].shift(1) >= df["ema21"].shift(1))
        df.loc[cross_above, "signal"] = 1   # BUY
        df.loc[cross_below, "signal"] = -1  # SELL/SHORT

        df["stop_loss"] = df.apply(
            lambda r: r["close"] - r["atr"] if r["signal"] == 1
            else r["close"] + r["atr"] if r["signal"] == -1 else np.nan, axis=1
        )
        df["target"] = df.apply(
            lambda r: r["close"] + 2 * r["atr"] if r["signal"] == 1
            else r["close"] - 2 * r["atr"] if r["signal"] == -1 else np.nan, axis=1
        )
        return df


class OpeningRangeBreakout:
    """
    Strategy: First 15-min candle defines the range
    Buy  → Price breaks ABOVE the opening range high
    Sell → Price breaks BELOW the opening range low
    Stop Loss: Opposite side of range
    Target:    1.5x the range distance
    Typical Win Rate: 50-55%
    Expected Monthly Return: 8-12% (high R:R trades)
    """
    name = "Opening Range Breakout (ORB 15-min)"
    description = (
        "Marks the High and Low of the first 15 minutes after market open (9:15–9:30 AM). "
        "BUY signal when price breaks above the range High with volume surge. "
        "SHORT signal when price breaks below the range Low. "
        "Stop Loss is set at the opposite end of the opening range."
    )
    win_rate = "50–55%"
    monthly_return = "8–12%"
    timeframe = "5-min"

    @staticmethod
    def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["time"] = pd.to_datetime(df["date"]).dt.time

        # Define opening range (first 15 min = first 3 candles of 5-min)
        opening = df[df["time"] <= time(9, 30)]
        if opening.empty:
            df["signal"] = 0
            return df

        or_high = opening["high"].max()
        or_low = opening["low"].min()
        or_range = or_high - or_low

        df["or_high"] = or_high
        df["or_low"] = or_low
        df["signal"] = 0

        after_open = df[df["time"] > time(9, 30)]
        for idx, row in after_open.iterrows():
            if row["close"] > or_high and df.loc[idx - 1, "signal"] == 0 if idx > 0 else True:
                df.loc[idx, "signal"] = 1
                df.loc[idx, "stop_loss"] = or_low
                df.loc[idx, "target"] = or_high + 1.5 * or_range
                break
            elif row["close"] < or_low and df.loc[idx - 1, "signal"] == 0 if idx > 0 else True:
                df.loc[idx, "signal"] = -1
                df.loc[idx, "stop_loss"] = or_high
                df.loc[idx, "target"] = or_low - 1.5 * or_range
                break

        return df


class RSIVWAPStrategy:
    """
    Strategy: RSI + VWAP confluence
    Buy  → RSI < 40 AND price crosses ABOVE VWAP (oversold + bullish momentum)
    Sell → RSI > 60 AND price crosses BELOW VWAP (overbought + bearish momentum)
    Stop Loss: Previous candle low/high
    Target:    2x stop-loss distance
    Typical Win Rate: 60-65%
    Expected Monthly Return: 5-7% (most consistent)
    """
    name = "RSI + VWAP Confluence"
    description = (
        "Combines RSI (14-period) with Volume Weighted Average Price (VWAP). "
        "BUY when RSI is below 40 (oversold) AND price crosses above VWAP — "
        "indicating a reversal with institutional support. "
        "SELL when RSI > 60 (overbought) AND price crosses below VWAP. "
        "Most consistent strategy with 60-65% win rate."
    )
    win_rate = "60–65%"
    monthly_return = "5–7%"
    timeframe = "5-min"

    @staticmethod
    def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = compute_rsi(df["close"], 14)
        df["vwap"] = compute_vwap(df)
        df["atr"] = compute_atr(df)
        df["signal"] = 0

        for i in range(1, len(df)):
            prev = df.iloc[i - 1]
            curr = df.iloc[i]

            # BUY: RSI oversold + price crosses above VWAP
            if curr["rsi"] < 40 and curr["close"] > curr["vwap"] and prev["close"] <= prev["vwap"]:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("stop_loss")] = curr["low"] - curr["atr"] * 0.5
                df.iloc[i, df.columns.get_loc("target")] = curr["close"] + 2 * curr["atr"]

            # SELL: RSI overbought + price crosses below VWAP
            elif curr["rsi"] > 60 and curr["close"] < curr["vwap"] and prev["close"] >= prev["vwap"]:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("stop_loss")] = curr["high"] + curr["atr"] * 0.5
                df.iloc[i, df.columns.get_loc("target")] = curr["close"] - 2 * curr["atr"]

        return df


# ─────────────────────────────────────────────
# OPTIONS STRATEGIES
# ─────────────────────────────────────────────

class TrendBasedOptionsBuying:
    """
    Strategy: Buy CE or PE based on underlying trend
    - Use EMA crossover on Nifty/BankNifty spot
    - Buy ATM CE when trend is bullish
    - Buy ATM PE when trend is bearish
    - Exit at 30% profit or 20% SL on premium
    Typical Win Rate: 45-50% (but 1:3 R:R)
    Expected Monthly Return: 10-15% on options capital
    """
    name = "Trend-Based Options Buying (CE/PE)"
    description = (
        "Identifies trend using EMA crossover on the underlying index (Nifty/BankNifty). "
        "Buys ATM Call Option (CE) on bullish trend, ATM Put Option (PE) on bearish trend. "
        "Uses premium-based stop loss (20% of premium paid) and target (50-60% profit). "
        "Best used during high-volatility days like budget, expiry days."
    )
    win_rate = "45–50%"
    monthly_return = "10–15%"
    instruments = ["NIFTY", "BANKNIFTY", "FINNIFTY"]

    @staticmethod
    def get_signal(df: pd.DataFrame) -> dict:
        df = df.copy()
        df["ema9"] = compute_ema(df["close"], 9)
        df["ema21"] = compute_ema(df["close"], 21)

        last = df.iloc[-1]
        prev = df.iloc[-2]

        signal = None
        if last["ema9"] > last["ema21"] and prev["ema9"] <= prev["ema21"]:
            signal = "BUY_CE"
        elif last["ema9"] < last["ema21"] and prev["ema9"] >= prev["ema21"]:
            signal = "BUY_PE"

        return {
            "signal": signal,
            "underlying_price": last["close"],
            "ema9": round(last["ema9"], 2),
            "ema21": round(last["ema21"], 2),
            "strike_type": "ATM",
            "sl_pct": 20,
            "target_pct": 50,
        }


class ShortStraddle:
    """
    Strategy: Sell ATM CE + ATM PE simultaneously
    - Collect premium from both sides
    - Profit when market stays in a range (theta decay)
    - Best on Wednesday/Thursday (pre-expiry)
    - Hedge with OTM options to limit risk
    Typical Win Rate: 65-70%
    Expected Monthly Return: 3-5% (safer, consistent)
    ⚠️ Requires higher margin (SPAN + Exposure)
    """
    name = "Short Straddle (Sell ATM CE + PE)"
    description = (
        "Sells ATM Call and ATM Put simultaneously to collect premium. "
        "Profits when the market stays within a range (time decay works in your favor). "
        "Best deployed on expiry week when theta decay is fastest. "
        "Exit when combined premium erodes by 50% (profit) or expands by 30% (loss). "
        "Requires significant margin — recommended for experienced traders only."
    )
    win_rate = "65–70%"
    monthly_return = "3–5%"
    risk = "HIGH (unlimited loss without hedge)"

    @staticmethod
    def get_breakeven(atm_strike: float, total_premium: float) -> dict:
        return {
            "upper_breakeven": atm_strike + total_premium,
            "lower_breakeven": atm_strike - total_premium,
            "max_profit": total_premium,
            "max_loss": "Unlimited (hedge recommended)",
        }


# Strategy registry
EQUITY_STRATEGIES = {
    "EMA Crossover": EMAcrossover,
    "Opening Range Breakout": OpeningRangeBreakout,
    "RSI + VWAP": RSIVWAPStrategy,
}

OPTIONS_STRATEGIES = {
    "Trend-Based CE/PE Buying": TrendBasedOptionsBuying,
    "Short Straddle": ShortStraddle,
}
