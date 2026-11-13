#!/usr/bin/env python3
"""Refresh data.json for the LESTER site.

Reads the market from DexScreener and the burn / cashback history from the
Notus launchpad contract on Base. Incremental: data.json remembers the last
block it scanned, so each run only reads the new blocks. Standard library only.
"""
import json, os, sys, time, datetime, urllib.request

RPCS = [u for u in os.environ.get("BASE_RPC", "").split(",") if u] + [
    "https://base-rpc.publicnode.com",
    "https://mainnet.base.org",
]
PAD = "0x23231924281b34bb28f10d854db8d2dcbd7f78c5"
TOKEN = "0x319a4924f6660a0660845418fa754a7684c19200"
PAIR = "0x5259413992d9b5626e62125de8159ed67636f0d8"
CREATED = 53125656      # block the coin was created in
GRADUATED = 53179072    # block it left the bonding curve
CHUNK = 50000
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.json")

T = {
    "0x7ce543d1780f3bdc3dac42da06c95da802653cd1b212b8d74ec3e3c33ad7095c": "Bought",
    "0x9be8a5ca22b7e6e81f04b5879f0248227bb770114291bd47dfaee4c3a82ad60e": "Sold",
    "0xf98723a8087ad8f3e606cb7260106113525d1eb06bc103534ea9a5ba776ea791": "PoolFee",
    "0xa52290e9bbeea08e85a4902c066be363bfea47a8be21bba8d1e325b67df795c6": "BoughtBack",
    "0x147e506c1ceb8acefa82862bf4d6b357b88660edf89ca2601722db6708455dd2": "CashbackClaimed",
    "0x429107d052e4d0cd116c820815b1d7d8cdb6ae4740384489ebd9c573ad1ac87d": "Taxed",
}
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x" + "0" * 64
PADDED_TOKEN = "0x" + "0" * 24 + TOKEN[2:]


def http(url, body=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json", "user-agent": "lesterweb-updater/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def rpc(method, params):
    last = None
    for attempt in range(4):
        for url in RPCS:
            try:
                d = http(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                if "error" in d:
                    last = d["error"]
                    continue
                return d["result"]
            except Exception as e:  # network error: try the next RPC
                last = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{method} failed: {last}")


def call(to, data):
    return int(rpc("eth_call", [{"to": to, "data": data}, "latest"]), 16)


def word(data, i):
    return int(data[2 + 64 * i: 2 + 64 * (i + 1)], 16)


def fresh_state():
    return {
        "scannedTo": CREATED - 1,
        "curve": {"buys": 0, "sells": 0, "fees": "0", "buybacks": 0, "buybackQuote": "0"},
        "pool": {"taxedSwaps": 0, "taxedTokens": "0", "harvests": 0, "toHolders": "0", "toTreasury": "0",
                 "buybacks": 0, "buybackQuote": "0"},
        "burn": {"curve": "0", "pool": "0", "events": 0},
        "claims": {"n": 0, "amount": "0", "wallets": []},
        "recent": [],
    }


def add(d, k, v):
    d[k] = str(int(d[k]) + v)


def scan(st, head):
    start = st["scannedTo"] + 1
    new = []
    a = start
    while a <= head:
        b = min(a + CHUNK - 1, head)
        rng = {"fromBlock": hex(a), "toBlock": hex(b)}
        pad_logs = rpc("eth_getLogs", [dict(rng, address=PAD, topics=[list(T), PADDED_TOKEN])])
        burn_logs = rpc("eth_getLogs", [dict(rng, address=TOKEN, topics=[TRANSFER, None, ZERO])])
        for l in pad_logs:
            name, blk, d = T[l["topics"][0]], int(l["blockNumber"], 16), l["data"]
            if name in ("Bought", "Sold"):
                st["curve"]["buys" if name == "Bought" else "sells"] += 1
                add(st["curve"], "fees", word(d, 2))
            elif name == "BoughtBack":
                ph = st["curve"] if blk <= GRADUATED else st["pool"]
                ph["buybacks"] += 1
                add(ph, "buybackQuote", word(d, 0))
            elif name == "Taxed":
                st["pool"]["taxedSwaps"] += 1
                add(st["pool"], "taxedTokens", word(d, 1))
            elif name == "PoolFee":
                st["pool"]["harvests"] += 1
                add(st["pool"], "toTreasury", word(d, 0))
                add(st["pool"], "toHolders", word(d, 2))
                if word(d, 2):
                    new.append({"type": "cashback", "block": blk, "amount": word(d, 2) / 1e8})
            elif name == "CashbackClaimed":
                st["claims"]["n"] += 1
                add(st["claims"], "amount", word(d, 0))
                w = "0x" + l["topics"][2][-40:]
                if w not in st["claims"]["wallets"]:
                    st["claims"]["wallets"].append(w)
        for l in burn_logs:
            blk, v = int(l["blockNumber"], 16), int(l["data"], 16)
            add(st["burn"], "curve" if blk <= GRADUATED else "pool", v)
            st["burn"]["events"] += 1
            new.append({"type": "burn", "block": blk, "amount": v / 1e18})
        st["scannedTo"] = b
        a = b + 1
        print(f"  scanned to {b} ({len(pad_logs)} launchpad logs, {len(burn_logs)} burns)", flush=True)
    new.sort(key=lambda e: e["block"])
    new = new[-14:]
    for e in new:  # timestamps only for the entries we keep
        e["ts"] = int(rpc("eth_getBlockByNumber", [hex(e["block"]), False])["timestamp"], 16)
    st["recent"] = (st["recent"] + new)[-14:]


def market():
    try:
        p = http(f"https://api.dexscreener.com/latest/dex/pairs/base/{PAIR}")["pair"]
        return {k: p.get(k) for k in ("priceUsd", "priceNative", "marketCap", "liquidity", "volume", "txns", "priceChange")}
    except Exception as e:
        print("  market fetch failed:", e)
        return None


def main():
    old = {}
    if os.path.exists(OUT) and "--full" not in sys.argv:
        old = json.load(open(OUT))
    st = old.get("state") or fresh_state()
    head = int(rpc("eth_blockNumber", []), 16) - 10  # stay clear of reorgs
    print(f"scanning {st['scannedTo'] + 1} -> {head}")
    scan(st, head)

    q = lambda s: int(s) / 1e8   # cbLTC has 8 decimals
    t = lambda s: int(s) / 1e18
    curve_fees = q(st["curve"]["fees"])
    curve_holders = curve_fees / 4  # fee is 1%: half Notus, half tax; half of the tax to holders
    pool_holders = q(st["pool"]["toHolders"])
    data = {
        "updatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "block": head,
        "market": market() or old.get("market"),
        "chain": {
            "supply": call(TOKEN, "0x18160ddd") / 1e18,
            "burned": call(PAD, "0xa7509b83" + PADDED_TOKEN[2:]) / 1e18,
            "burnPot": call(PAD, "0x4dd8afb6" + PADDED_TOKEN[2:]) / 1e8,
            "eligible": call(PAD, "0xe15904e0" + PADDED_TOKEN[2:]) / 1e18,
        },
        "curve": {
            "buys": st["curve"]["buys"], "sells": st["curve"]["sells"], "fees": curve_fees,
            "toHolders": curve_holders, "buybacks": st["curve"]["buybacks"],
            "buybackQuote": q(st["curve"]["buybackQuote"]), "burned": t(st["burn"]["curve"]),
        },
        "pool": {
            "taxedSwaps": st["pool"]["taxedSwaps"], "taxedTokens": t(st["pool"]["taxedTokens"]),
            "harvests": st["pool"]["harvests"], "toHolders": pool_holders,
            "buybacks": st["pool"]["buybacks"], "buybackQuote": q(st["pool"]["buybackQuote"]),
            "burned": t(st["burn"]["pool"]),
        },
        "cashback": {
            "total": curve_holders + pool_holders, "claimed": q(st["claims"]["amount"]),
            "claims": st["claims"]["n"], "wallets": len(st["claims"]["wallets"]),
        },
        "recent": st["recent"],
        "state": st,
    }
    json.dump(data, open(OUT, "w"), indent=1)
    print("wrote data.json:", json.dumps({k: data[k] for k in ("updatedAt", "block", "chain", "cashback")}))


if __name__ == "__main__":
    main()
