#!/usr/bin/env python3
"""cbBTC 1-minute bounce bot — make.fun "Race a BTC trading bot live for 24 hours"
(btc-race-24h-20261113-2314, deadline 2026-11-14 12:14 WIB).

Protocol — agent-fun/bars-replay/v1, verified against this competition's kit
(kit.json bundle hashes all OK, protocol.schema.json, sdk/makefun_bars.py,
competition.yaml, RULES.txt, dataset/bars/CBBTC.ndjson.gz):
  * Harness -> bot on stdin, NDJSON: one "hello", then one "batch" per
    minute, then "done". The bot answers EVERY batch with exactly one
    "reply" echoing its seq, and nothing else on stdout.
  * hello: {"type":"hello","protocol":"agent-fun/bars-replay/v1",
    "seed":str,"symbols":[{"symbol":"CBBTC","mint":...,"price_scale":5,
    "qty_scale":8}],"capital":{"quote":"USDC","quote_scale":6,
    "quote_units":"1000000000"},"bar_interval":"1m","first_close_ms":...,
    "caps":{"max_open_positions":1,"max_orders_per_bar":16,
    "max_weight_bps":10000,"shorts":false,"leverage":false},
    "fees":{"fee_bps":4,"slippage_bps":2,"min_notional_quote_units":"1000000"},
    "latency_bars":1} — no warmup_bars for this competition.
  * batch: {"type":"batch","seq":int,"t":ms,
    "bars":[{"symbol":"CBBTC","t":ms,"o":str,"h":str,"l":str,"c":str,
    "v":str|null,"o_depth":[str],"c_depth":[str]}],
    "fills":[{...}],"account":{"cash_quote_units":str,
    "positions":[{"symbol","qty","cost_quote_units"}],
    "equity_quote_units":str}}
    - Bar prices are INTEGER decimal strings at price_scale 5
      ($71,000 -> "7100000000"); qty at qty_scale 8 (1 BTC -> "100000000");
      quote amounts at quote_scale 6 ($1 -> "1000000"). "v" is null.
    - A minute with no sample has NO bar (CBBTC absent from that batch).
  * reply: {"type":"reply","seq":<same>,"orders":[...]} — hold = [].
    - buy:  {"side":"buy","symbol":"CBBTC",
             "notional_quote_units":<int USDC raw units>,
             "max_slippage_bps":100}
    - sell: {"side":"sell","symbol":"CBBTC","qty":<int base units>,
             "max_slippage_bps":100}
    - client_id is omitted: the shim assigns o1, o2, ... (never "_...").
  * Fills: an order decided on batch k fills at bar k+1's open, fee 4 bps
    + slippage 2 bps + constant-product impact vs that bar's o_depth;
    max_slippage_bps is measured from the latest close the bot was sent.
    A sell's proceeds never fund a buy of the same reply; orders decided
    on the last batch are rejected (after_end); everything still held at
    the end is flattened at the last close (no max_slippage, no min notional).
    A full round trip costs ~26 bps at $1,000 size.
  * Dev gate: net PnL > $0 after all fees on the dev window, or the entry
    does not race. Race guardrails: >= 1 trade and max drawdown <= 25%.

Rules obeyed: Python standard library only (via the kit's own vendored
shim, copied byte-identical under vendor/ as the kit instructs), no
network, no wall clock, no files, no environment, no randomness. Two
runs on the same input produce byte-identical replies.

Strategy — bounce rider (long only, full equity, at most 2 round trips):
  * Entry: EMA(8) crosses above EMA(21) AND the close sits at least 1%
    below the highest close of the last 480 bars (8h). The drawdown
    filter is the point: on a falling tape the first EMA cross happens
    near the top of the window, and buying it rides the fall down. The
    filter only lets the bot in after a real decline, i.e. it buys
    bounces, not tops. EMAs are seeded as the mean of their first span
    of closes, exactly like the kit's ema-cross baseline, so the bot can
    trade from bar 21.
  * Exit: take-profit +0.80%, or a trailing stop (once +0.40% in profit,
    sell 0.30% below the peak since entry), or a 240-bar (4h) time stop.
    No fixed stop-loss: 1-minute noise (stdev ~0.08%, max ~0.66% on the
    dev window) would stop the bot out of good bounces.
  * At most 2 round trips per window: after the second trip the bot sits
    in cash. Re-entries past the second bleed ~26 bps of costs per trip
    against fading bounces.
  * max_slippage_bps 100 (1%): the dev window's largest 1-minute move is
    0.66%, so a 1% cap essentially never rejects on price moves; it
    matches the kit baselines.

Local dev grade (exact engine port, grade_local.py in /tmp/btc2314-dev/,
buy-and-hold sanity check -$52.59 on the same engine):
  net PnL +$11.55, 2 round trips won 2/2 (+$6.18, +$5.38), fees $1.61,
  max drawdown 0.62%, 0 rejections, replies byte-identical across 2 runs.
  Dev gate: PASS.
  The same parameters stay positive across a wide neighbourhood on this
  window (drawdown filter 0.5–1.5%, take-profit 0.4–0.8%, time stop
  180–480 bars all give +$4.60 to +$11.55 with both trips won), so the
  result is not a knife-edge fit.
  Honest caveat: the margin is two trades on one 24h window. On the
  previous competition's dev window (a slow rise then a grind down) this
  same bot loses -$6.62 with max drawdown 1.04% — bounded, but a loss.
  The race window is unseen and can look like either regime; what the
  grade proves is that the bot races (dev gate passed) with tiny
  drawdown, not that it will profit there.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "vendor"))
import makefun_bars  # noqa: E402  (vendored kit shim, byte-identical copy)

SYMBOL = "CBBTC"
MAX_SLIPPAGE_BPS = 100

# ---------------------------------------------------------------------------
# Parameters (all fixed constants — no tuning at run time, no randomness)
# ---------------------------------------------------------------------------
FAST_SPAN = 8              # EMA(8) — entry cross, kit ema-cross baseline
SLOW_SPAN = 21             # EMA(21)
DRAWDOWN_FILTER = 0.01     # entry only >= 1% below the 480-bar high close
DRAWDOWN_LOOKBACK = 480    # bars (8h) for the high close
TAKE_PROFIT = 0.0080       # +0.80%
TRAIL_TRIGGER = 0.0040     # start trailing once +0.40% in profit
TRAIL_GIVEBACK = 0.0030    # sell 0.30% below the peak since entry
TIME_STOP_BARS = 240       # exit after 4 hours in a trade
MAX_TRIPS = 2              # at most two round trips per window
MIN_NOTIONAL = 1_000_000   # $1 in quote units (hello fees.min_notional)


class Ema:
    """One EMA, seeded as the mean of its first span of closes (kit baseline)."""

    def __init__(self, span):
        self.span = span
        self.warm = []
        self.value = None

    def step(self, close):
        if self.value is not None:
            self.value += (2.0 / (self.span + 1)) * (close - self.value)
            return
        self.warm.append(close)
        if len(self.warm) == self.span:
            self.value = sum(self.warm) / self.span


class BounceRider:
    def __init__(self):
        self.fast = Ema(FAST_SPAN)
        self.slow = Ema(SLOW_SPAN)
        self.prev_gap = None       # fast - slow after the previous bar
        self.closes = []           # every close seen, for the high filter
        self.entry_price = None    # fill price (int) of the open position
        self.entry_seq = None
        self.peak_since_entry = None
        self.trips = 0             # closed round trips so far
        self.bar_seq = 0

    def _apply_fills(self, fills):
        """Track our own filled orders (ignore the harness's _flatten_ closes)."""
        for f in fills or []:
            if not isinstance(f, dict):
                continue
            cid = f.get("client_id") or ""
            if not isinstance(cid, str) or cid.startswith("_"):
                continue
            if f.get("status") != "filled":
                continue
            if f.get("symbol") != SYMBOL:
                continue
            if f.get("side") == "buy":
                try:
                    price = int(f["price"])
                except (KeyError, TypeError, ValueError):
                    continue
                if price > 0:
                    self.entry_price = price
                    self.entry_seq = self.bar_seq
                    self.peak_since_entry = price
            elif f.get("side") == "sell":
                self.entry_price = None
                self.entry_seq = None
                self.peak_since_entry = None
                self.trips += 1

    def on_batch(self, state, batch):
        self.bar_seq = state.seq
        # Fills from the previous batch's orders (may arrive on a gap
        # batch too — only "filled" ones matter here).
        self._apply_fills(batch.get("fills"))

        bar = state.latest.get(SYMBOL)
        if bar is None:
            return []  # gap minute: no new bar, no decision to make
        close = int(bar["c"])
        self.closes.append(close)
        self.fast.step(close)
        self.slow.step(close)
        gap = (self.fast.value - self.slow.value
               if self.fast.value is not None
               and self.slow.value is not None else None)
        prev_gap = self.prev_gap
        self.prev_gap = gap

        if state.warming_up:
            return []  # protocol warm-up: any order would be rejected

        holding = state.positions.get(SYMBOL)
        qty = holding.qty if holding is not None else 0

        if qty > 0:
            if self.peak_since_entry is not None and close > self.peak_since_entry:
                self.peak_since_entry = close
            return self._maybe_exit(close, qty)

        if self.trips >= MAX_TRIPS:
            return []  # two rides taken: sit out the rest of the window
        if gap is None or prev_gap is None:
            return []
        cross_up = gap > 0 and prev_gap <= 0
        if not cross_up:
            return []
        if len(self.closes) < DRAWDOWN_LOOKBACK:
            return []
        high = max(self.closes[-DRAWDOWN_LOOKBACK:])
        if close > high * (1.0 - DRAWDOWN_FILTER):
            return []  # too close to the 8h high: not a bounce, skip it
        notional = min(state.equity, state.cash, state.weight_room(SYMBOL))
        if notional < MIN_NOTIONAL:
            return []
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": int(notional),
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]

    def _maybe_exit(self, close, qty):
        if self.entry_price is None or self.entry_price <= 0:
            # Position held but entry price unknown (should not happen —
            # fills are tracked): hold until the time stop.
            if (self.entry_seq is not None
                    and self.bar_seq - self.entry_seq >= TIME_STOP_BARS):
                return self._sell_all(qty)
            return []
        pnl = close / self.entry_price - 1.0
        held = (self.bar_seq - self.entry_seq
                if self.entry_seq is not None else 0)
        if pnl >= TAKE_PROFIT:
            return self._sell_all(qty)
        if (self.peak_since_entry is not None
                and self.peak_since_entry >= self.entry_price * (1.0 + TRAIL_TRIGGER)
                and close <= self.peak_since_entry * (1.0 - TRAIL_GIVEBACK)):
            return self._sell_all(qty)
        if held >= TIME_STOP_BARS:
            return self._sell_all(qty)
        return []

    def _sell_all(self, qty):
        return [{"side": "sell", "symbol": SYMBOL, "qty": int(qty),
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]


def main():
    bot = BounceRider()
    makefun_bars.run(bot.on_batch)


if __name__ == "__main__":
    main()
