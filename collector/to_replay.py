"""Turns one collected day for one stock into a replay file for viz/arena3d.html.

  python collector/to_replay.py 20261103 005930
  -> viz/replay/20261103_005930.json

Investor and broker are NOT in the tick data, so they are estimated:
  - foreign: growth of the top foreign brokers' cumulative buy/sell (외국계 창구, ~10 s)
  - institution: growth of the intraday investor estimate (~60 s)
  - the rest: retail
Within each interval the largest trades are assigned first (foreign, then
institution), which is a heuristic. The replay file marks this as estimated.
"""
import argparse
import csv
import json
import sys
from bisect import bisect_right
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPEN = 9 * 3600

KNOWN_FOREIGN = {"모건": "ms", "JP": "jpm", "제이피": "jpm"}


def secs(hms):
    """'HHMMSS', 'HH:MM:SS' or 'HH:MM:SS.mmm' -> seconds since 09:00."""
    s = str(hms or "")
    if ":" in s:
        h, m, rest = s.split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest) - OPEN
    d = "".join(ch for ch in s if ch.isdigit())[:6].ljust(6, "0")
    return int(d[:2]) * 3600 + int(d[2:4]) * 60 + int(d[4:6]) - OPEN


def read(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pick_side_map(ticks):
    """sell_buy_ccd's meaning isn't documented: pick the mapping whose buy/sell
    ratio matches the API's own 체결강도 at the end of the day."""
    codes = sorted({t["side_cd"] for t in ticks})
    if len(codes) != 2:
        return {"1": "S", "2": "B"}, "default"
    a, b = codes
    vol = {a: 0, b: 0}
    for t in ticks:
        vol[t["side_cd"]] += int(t["qty"])
    reported = fnum(ticks[-1].get("strength_p2"))
    best = None
    for buy, sell in ((b, a), (a, b)):
        ratio = vol[buy] / max(vol[sell], 1) * 100
        for scale in (1, 100):
            if reported is None:
                continue
            err = abs(reported / scale - ratio)
            if best is None or err < best[0]:
                best = (err, buy, sell)
    if best is None:
        return {a: "S", b: "B"}, "default"
    return {best[1]: "B", best[2]: "S"}, f"checked against 체결강도 (err {best[0]:.1f})"


def deltas(snaps):
    """[(t, buy_total, sell_total)] -> [(t0, t1, d_buy, d_sell)]"""
    out = []
    for (t0, b0, s0), (t1, b1, s1) in zip(snaps, snaps[1:]):
        out.append((t0, t1, max(0, b1 - b0), max(0, s1 - s0)))
    return out


def foreign_snaps(rows):
    by_t = {}
    for r in rows:
        q = fnum(r["qty"]) or 0
        d = by_t.setdefault(r["recv"], {"B": 0, "S": 0, "names": {}})
        d[r["side"]] += q
        d["names"][r["broker"]] = d["names"].get(r["broker"], 0) + q
    snaps = [(secs(t), d["B"], d["S"]) for t, d in sorted(by_t.items())]
    names = [(secs(t), d["names"]) for t, d in sorted(by_t.items())]
    return snaps, names


def investor_snaps(rows, col):
    by_t = {}
    for r in rows:
        by_t.setdefault(r["recv"], {})[r["side"]] = fnum(r[col]) or 0
    return [(secs(t), d.get("B", 0), d.get("S", 0)) for t, d in sorted(by_t.items()) if "B" in d and "S" in d]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("code")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "viz" / "replay"))
    args = ap.parse_args()

    day = Path(args.data) / args.date
    ticks = read(day / f"{args.code}_ticks.csv")
    if not ticks:
        sys.exit(f"{day / (args.code + '_ticks.csv')} 에 체결 데이터가 없습니다.")
    side_map, how = pick_side_map(ticks)

    trades = []
    for t in ticks:
        tt = secs(t["ccls_tm"]) if t.get("ccls_tm") else secs(t["recv"])
        trades.append({"t": tt, "side": side_map.get(t["side_cd"], "B"), "qty": int(t["qty"]),
                       "price": int(float(t["price"])), "inv": "IND", "broker": "retail"})
    trades.sort(key=lambda x: x["t"])
    times = [x["t"] for x in trades]

    def assign(intervals, inv, broker_of):
        for t0, t1, d_buy, d_sell in intervals:
            lo, hi = bisect_right(times, t0), bisect_right(times, t1)
            for side, need in (("B", d_buy), ("S", d_sell)):
                pool = sorted((x for x in trades[lo:hi] if x["side"] == side and x["inv"] == "IND"), key=lambda x: -x["qty"])
                for x in pool:
                    if need <= 0:
                        break
                    x["inv"], x["broker"] = inv, broker_of(t1)
                    need -= x["qty"]

    f_snaps, f_names = foreign_snaps(read(day / f"{args.code}_foreign.csv"))

    def foreign_broker(t):
        # the foreign broker whose cumulative volume grew most in the interval ending at t
        i = max(0, min(range(len(f_names)), key=lambda k: abs(f_names[k][0] - t)) if f_names else 0)
        if not f_names or i == 0:
            return "fgn"
        prev, cur = f_names[i - 1][1], f_names[i][1]
        name = max(cur, key=lambda n: cur[n] - prev.get(n, 0))
        return next((v for k, v in KNOWN_FOREIGN.items() if k in name), "fgn")

    assign(deltas(f_snaps), "FOR", foreign_broker)
    assign(deltas(investor_snaps(read(day / f"{args.code}_investor.csv"), "ogn")), "INS", lambda t: "inst")

    index = []
    for r in read(day / "index.csv"):
        name = r.get("name") or ""
        if "코스피" in name and "200" not in name:
            v = fnum(r["change_pct_p2"])
            if v is not None:
                pct = v / 100 if abs(v) >= 30 else v  # P2 = two implied decimals
                index.append([round(secs(r["recv"]), 2), round(pct / 100, 6)])

    book = [[round(secs(r["recv"]), 2), int(fnum(r["bid_total"]) or 0), int(fnum(r["ask_total"]) or 0)]
            for r in read(day / f"{args.code}_book.csv")]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{args.date}_{args.code}.json"
    path.write_text(json.dumps({
        "code": args.code, "date": args.date, "side_map": how, "estimated": ["inv", "broker"],
        "fields": ["t", "side", "qty", "price", "inv", "broker"],
        "trades": [[round(x["t"], 3), x["side"], x["qty"], x["price"], x["inv"], x["broker"]] for x in trades],
        "index": index, "book": book,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    n = len(trades)
    share = {k: sum(1 for x in trades if x["inv"] == k) / n for k in ("IND", "FOR", "INS")}
    print(f"{path} : 체결 {n:,}건, 매수/매도 구분 {how}")
    print("투자자 추정 비중(건수): " + ", ".join(f"{k} {v:.0%}" for k, v in share.items()))


if __name__ == "__main__":
    main()
