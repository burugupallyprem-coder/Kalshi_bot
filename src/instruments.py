"""Futures instrument metadata + contract-aware risk sizing.

This is the "instrument abstraction" layer your mentor put first: the risk engine
must size in CONTRACTS using each product's multiplier and tick size, not in
shares. Multipliers and tick sizes below are exchange-standard and stable.

MARGIN IS DELIBERATELY NOT HARD-CODED. Initial/maintenance/intraday margins change
frequently and differ by broker - pull them live from your broker before sizing.
`margin_hint` is only a rough placeholder you must overwrite from the broker.

Nothing here trades. It is pure, tested library code - safe to import anywhere.
"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Contract:
    symbol: str
    name: str
    multiplier: float      # $ per 1.0 point of price move, per contract
    tick_size: float       # minimum price increment
    # tick_value == multiplier * tick_size  (asserted in tests)
    margin_hint: float     # ROUGH day-trade margin placeholder - VERIFY with broker


# Exchange-standard specs (multiplier & tick_size are stable facts).
REGISTRY = {
    "ES":  Contract("ES",  "E-mini S&P 500",       50.0, 0.25, 500.0),
    "MES": Contract("MES", "Micro E-mini S&P 500",  5.0, 0.25,  50.0),
    "NQ":  Contract("NQ",  "E-mini Nasdaq-100",     20.0, 0.25, 700.0),
    "MNQ": Contract("MNQ", "Micro E-mini Nasdaq",    2.0, 0.25,  70.0),
    "YM":  Contract("YM",  "E-mini Dow",             5.0, 1.00, 500.0),
    "MYM": Contract("MYM", "Micro E-mini Dow",        0.5, 1.00,  50.0),
    "RTY": Contract("RTY", "E-mini Russell 2000",   50.0, 0.10, 400.0),
    "M2K": Contract("M2K", "Micro E-mini Russell",   5.0, 0.10,  40.0),
    "GC":  Contract("GC",  "Gold",                 100.0, 0.10,1000.0),
    "MGC": Contract("MGC", "Micro Gold",            10.0, 0.10, 100.0),
    "CL":  Contract("CL",  "Crude Oil",           1000.0, 0.01,1200.0),
    "MCL": Contract("MCL", "Micro Crude Oil",      100.0, 0.01, 120.0),
}


def get_contract(symbol):
    try:
        return REGISTRY[symbol.upper()]
    except KeyError:
        raise KeyError(f"unknown futures symbol {symbol!r}; known: {sorted(REGISTRY)}")


def tick_value(symbol):
    c = get_contract(symbol)
    return c.multiplier * c.tick_size


def round_to_tick(price, symbol, mode="nearest"):
    """Round a raw price to a valid tick. mode: nearest|up|down.
    Stops/targets MUST sit on real ticks or the exchange rejects them."""
    c = get_contract(symbol)
    n = price / c.tick_size
    if mode == "up":
        n = math.ceil(n)
    elif mode == "down":
        n = math.floor(n)
    else:
        n = math.floor(n + 0.5)
    return round(n * c.tick_size, 10)


def dollar_risk_per_contract(entry, stop, symbol):
    """$ lost per contract if stopped, using the product multiplier."""
    c = get_contract(symbol)
    return abs(entry - stop) * c.multiplier


def contracts_for_risk(entry, stop, symbol, equity, risk_pct):
    """How many whole contracts risk <= risk_pct of equity given the stop distance.
    Returns 0 when even one contract would exceed the risk budget (never rounds up)."""
    per = dollar_risk_per_contract(entry, stop, symbol)
    if per <= 0:
        return 0
    budget = equity * risk_pct / 100.0
    return max(int(math.floor(budget / per)), 0)


def position_notional(entry, symbol, contracts):
    c = get_contract(symbol)
    return entry * c.multiplier * contracts


def effective_slippage_cents(symbol, commission_per_side=0.50, ticks_spread_per_side=0.5):
    """Map a real futures round-trip cost into the equity engine's 'slippage_cents'
    unit so the existing (well-tested) simulator can charge it.

    The engine charges price offset = slippage_cents/100 in the price's native unit.
    For futures the native unit is INDEX POINTS, so we express the per-side cost in
    points and scale by 100:
        cost_points/side = ticks_spread_per_side * tick_size          (half-spread)
                         + commission_per_side / multiplier           (fee in points)
    Defaults are OPTIMISTIC (half-tick spread, $0.50/side). VERIFY commissions with
    your broker and widen the spread assumption for thinner books (e.g. MYM)."""
    c = get_contract(symbol)
    cost_points = ticks_spread_per_side * c.tick_size + commission_per_side / c.multiplier
    return round(cost_points * 100.0, 4)
