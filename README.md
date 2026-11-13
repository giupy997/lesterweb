# LESTER — The Litecoin Mascot

Single-page website for the LESTER token on Base (paired with cbLTC on Uniswap v2, launched on Notus Pad).

## Files

- `index.html` — the whole site, no build step. Host it anywhere static (GitHub Pages works).
- `data.json` — market snapshot plus the burn / cashback history. The page loads it on open and every minute.
- `scripts/update.py` — regenerates `data.json`. Python standard library only. It is incremental: it remembers the last Base block it scanned.

## Where the numbers come from

| Data | Source | Refresh |
|---|---|---|
| Price, market cap, liquidity, volume | DexScreener API, from the visitor's browser | every 60 s |
| Supply, burned, burn pot, per-wallet cashback | Notus launchpad contract on Base, public RPC, from the browser | every 60 s |
| Cashback totals, claims, phase table, burn and payout log | `data.json`, built from contract events by `scripts/update.py` | whenever the script runs |

If the browser cannot reach DexScreener or the RPC, the page falls back to `data.json`, and then to the snapshot embedded in `index.html`.

Refresh the history with:

```bash
python3 scripts/update.py
```

`--full` rescans from the coin's creation block. Commit and push `data.json` afterwards.

Token `0x319A4924f6660A0660845418FA754a7684C19200` · Pool `0x5259413992d9B5626e62125De8159ED67636f0d8` · Launchpad `0x23231924281B34Bb28F10D854DB8D2DcBd7F78c5`
