# Bounce Rider — cbBTC 1-minute trading bot

make.fun bounty **btc-race-24h-20261113-2314** — "Race a BTC trading bot live
for 24 hours" ($250 prize pool, deadline 14 Nov 2026 12:14 WIB).

A long-only bot that trades Coinbase Wrapped BTC (cbBTC) against USDC,
minute by minute, on the `agent-fun/bars-replay/v1` protocol (NDJSON on
stdin/stdout). It starts with 1,000 USDC of paper money and races only if it
made money on the published dev window.

## Strategy

- **Entry:** EMA(8) crosses above EMA(21) **and** the close sits at least 1%
  below the highest close of the last 480 bars (8h). The drawdown filter is
  the point: on a falling tape the first EMA cross happens near the top, and
  buying it rides the fall down. The filter only lets the bot in after a real
  decline — it buys bounces, not tops.
- **Exit:** take-profit +0.80%, or a trailing stop (once +0.40% in profit,
  sell 0.30% below the peak since entry), or a 240-bar (4h) time stop. No
  fixed stop-loss: 1-minute noise would stop the bot out of good bounces.
- **At most 2 round trips per window**, full equity per trade. After the
  second trip the bot sits in cash — re-entries past the second bleed ~26 bps
  of costs per trip against fading bounces.

## Files

- `main.py` — the bot (Python 3.13, standard library only)
- `vendor/makefun_bars.py` — the kit's protocol shim, copied byte-identical
  from the kit's `sdk/makefun_bars.py`
- `LICENSE` — MIT (`SPDX-License-Identifier: MIT`)
- `.makefun/owner.json` — claim file naming the payout wallet

## Local verification (dev window, exact engine port)

```
net PnL +$11.55, 2 round trips won 2/2 (+$6.18, +$5.38), fees $1.61,
max drawdown 0.62%, 0 rejections, replies byte-identical across 2 runs.
Dev gate: PASS.
```

The same parameters stay positive across a wide neighbourhood on this window
(drawdown filter 0.5–1.5%, take-profit 0.4–0.8%, time stop 180–480 bars all
give +$4.60 to +$11.55 with both trips won), so the result is not a
knife-edge fit.

Honest caveat: the margin is two trades on one 24h window. On the previous
competition's dev window (a slow rise then a grind down) this same bot loses
-$6.62 with max drawdown 1.04% — bounded, but a loss. The race window is
unseen and can look like either regime; what the grade proves is that the bot
races (dev gate passed) with tiny drawdown, not that it will profit there.

## License

MIT — see `LICENSE`.
