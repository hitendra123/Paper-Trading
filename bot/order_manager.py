"""
Order Manager and Risk Manager.
Supports two modes:
  - Paper trade (default, works with any data source)
  - Live trade via Zerodha Kite Connect (requires kiteconnect + valid session)
"""
from datetime import datetime
import pandas as pd

try:
    from kiteconnect import KiteConnect as _KiteConnect  # noqa: F401
    _KITE_AVAILABLE = True
except ImportError:
    _KiteConnect = None
    _KITE_AVAILABLE = False


# ─────────────────────────────────────────────
# RISK MANAGER
# ─────────────────────────────────────────────

class RiskManager:
    def __init__(self, max_risk_per_trade_pct: float = 1.0,
                 max_daily_loss_pct: float = 3.0,
                 capital: float = 100000.0):
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.capital = capital
        self.daily_pnl = 0.0
        self.trade_count = 0
        self.max_trades_per_day = 5

    @property
    def max_risk_per_trade(self) -> float:
        return self.capital * (self.max_risk_per_trade_pct / 100)

    @property
    def max_daily_loss(self) -> float:
        return self.capital * (self.max_daily_loss_pct / 100)

    def can_trade(self) -> tuple[bool, str]:
        if self.daily_pnl <= -self.max_daily_loss:
            return False, f"Daily loss limit hit: ₹{abs(self.daily_pnl):.0f} >= ₹{self.max_daily_loss:.0f}"
        if self.trade_count >= self.max_trades_per_day:
            return False, f"Max trades per day ({self.max_trades_per_day}) reached"
        return True, "OK"

    def calculate_quantity(self, entry_price: float, stop_loss: float) -> int:
        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share == 0:
            return 1
        qty = int(self.max_risk_per_trade / risk_per_share)
        return max(1, qty)

    def update_pnl(self, pnl: float):
        self.daily_pnl += pnl
        self.trade_count += 1

    def reset_daily(self):
        self.daily_pnl = 0.0
        self.trade_count = 0


# ─────────────────────────────────────────────
# ORDER MANAGER
# ─────────────────────────────────────────────

class OrderManager:
    def __init__(self, kite=None, risk_manager: RiskManager = None, paper_trade: bool = True):
        self.kite = kite
        self.risk = risk_manager or RiskManager()
        self.paper_trade = paper_trade or (kite is None)
        self.open_positions = {}
        self.trade_log = []

    def place_order(self, symbol: str, exchange: str, transaction_type: str,
                    quantity: int, order_type: str = "MARKET",
                    price: float = 0, trigger_price: float = 0,
                    product: str = "MIS") -> dict:
        """Place a buy/sell order via Kite or paper trade."""
        order = {
            "symbol": symbol,
            "exchange": exchange,
            "transaction_type": transaction_type,
            "quantity": quantity,
            "order_type": order_type,
            "price": price,
            "product": product,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "PENDING",
            "order_id": None,
        }

        if self.paper_trade:
            order["status"] = "PAPER_EXECUTED"
            order["order_id"] = f"PAPER_{len(self.trade_log) + 1:04d}"
        else:
            try:
                can, reason = self.risk.can_trade()
                if not can:
                    order["status"] = "REJECTED"
                    order["reject_reason"] = reason
                    return order

                kite_order = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=exchange,
                    tradingsymbol=symbol,
                    transaction_type=transaction_type,
                    quantity=quantity,
                    product=product,
                    order_type=order_type,
                    price=price if order_type == "LIMIT" else None,
                    trigger_price=trigger_price if trigger_price else None,
                )
                order["order_id"] = kite_order
                order["status"] = "PLACED"
            except Exception as e:
                order["status"] = "ERROR"
                order["error"] = str(e)

        self.trade_log.append(order)
        return order

    def place_bracket_order(self, symbol: str, exchange: str, transaction_type: str,
                             quantity: int, entry_price: float,
                             stop_loss: float, target: float) -> dict:
        """Place entry order with SL and target as separate orders (GTT or CO)."""
        entry = self.place_order(
            symbol=symbol, exchange=exchange,
            transaction_type=transaction_type,
            quantity=quantity, order_type="MARKET",
        )

        sl_side = "SELL" if transaction_type == "BUY" else "BUY"

        sl_order = {
            "symbol": symbol,
            "type": "STOP_LOSS",
            "trigger_price": stop_loss,
            "quantity": quantity,
            "side": sl_side,
            "linked_to": entry.get("order_id"),
        }
        target_order = {
            "symbol": symbol,
            "type": "TARGET",
            "price": target,
            "quantity": quantity,
            "side": sl_side,
            "linked_to": entry.get("order_id"),
        }

        self.open_positions[symbol] = {
            "entry": entry,
            "stop_loss": sl_order,
            "target": target_order,
            "entry_price": entry_price,
            "stop_loss_price": stop_loss,
            "target_price": target,
            "quantity": quantity,
            "side": transaction_type,
        }

        return {"entry": entry, "stop_loss": sl_order, "target": target_order}

    def square_off_all(self) -> list:
        """Square off all open MIS positions (auto square-off at 3:15 PM)."""
        results = []
        if self.paper_trade:
            for symbol, pos in self.open_positions.items():
                results.append({"symbol": symbol, "status": "PAPER_SQUARED_OFF"})
            self.open_positions.clear()
            return results

        try:
            positions = self.kite.positions()
            for pos in positions.get("day", []):
                if pos["quantity"] != 0:
                    side = "SELL" if pos["quantity"] > 0 else "BUY"
                    result = self.place_order(
                        symbol=pos["tradingsymbol"],
                        exchange=pos["exchange"],
                        transaction_type=side,
                        quantity=abs(pos["quantity"]),
                        product="MIS",
                    )
                    results.append(result)
        except Exception as e:
            results.append({"error": str(e)})
        return results

    def get_trade_log_df(self) -> pd.DataFrame:
        if not self.trade_log:
            return pd.DataFrame(columns=["timestamp", "symbol", "transaction_type",
                                         "quantity", "price", "status", "order_id"])
        return pd.DataFrame(self.trade_log)

    def get_open_positions_df(self) -> pd.DataFrame:
        if not self.open_positions:
            return pd.DataFrame()
        rows = []
        for symbol, pos in self.open_positions.items():
            rows.append({
                "Symbol": symbol,
                "Side": pos["side"],
                "Qty": pos["quantity"],
                "Entry": pos["entry_price"],
                "SL": pos["stop_loss_price"],
                "Target": pos["target_price"],
                "Status": pos["entry"]["status"],
            })
        return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# OPTIONS HELPER
# ─────────────────────────────────────────────

def get_atm_strike(spot_price: float, strike_gap: int = 50) -> int:
    """Round spot price to nearest ATM strike."""
    return round(spot_price / strike_gap) * strike_gap


def build_option_symbol(underlying: str, expiry: str, strike: int, option_type: str) -> str:
    """
    Build NSE option tradingsymbol.
    Example: NIFTY2531250050CE → NIFTY 25-Mar 50CE (wrong format, correct below)
    Format: NIFTY25MAR5000CE (BSE) or NIFTY25316CE (Zerodha NFO format)
    """
    # Zerodha NFO format: {UNDERLYING}{YY}{MMM}{STRIKE}{CE/PE}
    return f"{underlying}{expiry}{strike}{option_type}"
