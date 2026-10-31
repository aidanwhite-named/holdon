"""Collects intraday data for a few KOSPI stocks into data/YYYYMMDD/.

  python collector/collect.py                  # real API, waits for the session window
  python collector/collect.py --now            # start immediately (ignore session window)
  python collector/collect.py --mock --now     # fake API, to test the pipeline

Files per day (one CSV per stock and kind):
  {code}_ticks.csv     every trade: time, price, qty, aggressor side, cumulative volume, 체결강도
  {code}_book.csv      best quotes, total bid/ask size, VI state
  {code}_foreign.csv   top foreign brokers' cumulative buy/sell (외국계 창구)
  {code}_investor.csv  intraday investor estimates (개인/외인/기관), buy and sell separately
  {code}_program.csv   program trading by time
  index.csv            KOSPI and other indices
  raw/                 first responses of each TR as-is, to check field formats
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from kb_client import ApiError, KBClient  # noqa: E402
from mock_client import MockClient  # noqa: E402


def num(v):
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None


def records(body, key="out"):
    v = body.get(key)
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return [v]
    return []


class Store:
    """Appends rows to per-day CSVs; writes the header when a file is new."""

    def __init__(self, root):
        self.dir = Path(root) / datetime.now().strftime("%Y%m%d")
        (self.dir / "raw").mkdir(parents=True, exist_ok=True)
        self.files = {}
        self.raw_counts = {}

    def write(self, name, header, rows):
        if not rows:
            return
        if name not in self.files:
            path = self.dir / f"{name}.csv"
            new = not path.exists()
            f = open(path, "a", newline="", encoding="utf-8")
            w = csv.writer(f)
            if new:
                w.writerow(header)
            self.files[name] = (f, w)
        f, w = self.files[name]
        w.writerows(rows)
        f.flush()

    def raw(self, tr, body, keep=2):
        n = self.raw_counts.get(tr, 0)
        if n < keep:
            (self.dir / "raw" / f"{tr}_{n}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
            self.raw_counts[tr] = n + 1

    def close(self):
        for f, _ in self.files.values():
            f.close()


class Collector:
    def __init__(self, client, store, cfg):
        self.c, self.store, self.cfg = client, store, cfg
        self.excg = cfg.get("exchange", "0")
        self.last_acml = {}
        self.last_prog_tm = {}
        self.stats = {code: {"ticks": 0, "missed_vol": 0, "errors": 0} for code in cfg["symbols"]}
        self.errors = 0

    def _call(self, tr, body):
        out = self.c.call(tr, body)
        self.store.raw(tr, out)
        return out

    # ---- tasks ----
    def ticks(self, code):
        body = self._call("IVU10080", {"excg_clsf": self.excg, "ovtm_mkt_clsf": "0", "is_cd": code,
                                       "inq_cnt": str(self.cfg.get("tick_fetch_count", 100))})
        rows = []
        for r in records(body):
            acml = num(r.get("acml_vlm"))
            if acml is not None:
                rows.append((acml, r))
        rows.sort(key=lambda x: x[0])
        last = self.last_acml.get(code)
        new = [(a, r) for a, r in rows if last is None or a > last]
        if not new:
            return
        if last is not None:
            # Gap check: cumulative volume grew by more than the trades we received.
            got = sum(num(r.get("ccls_q")) or 0 for _, r in new)
            self.stats[code]["missed_vol"] += max(0, (new[-1][0] - last) - got)
        self.last_acml[code] = new[-1][0]
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.stats[code]["ticks"] += len(new)
        self.store.write(f"{code}_ticks",
                         ["recv", "ccls_tm", "excg", "price", "qty", "side_cd", "acml_vlm", "strength_p2"],
                         [[now, r.get("ccls_tm"), r.get("excg_cd"), num(r.get("ccls_prc")), num(r.get("ccls_q")),
                           r.get("sell_buy_ccd"), a, r.get("ccls_strn_p2")] for a, r in new])

    def book(self, code):
        b = self._call("IVU10070", {"is_cd": code, "ovtm_mkt_clsf": "0"})
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.store.write(f"{code}_book",
                         ["recv", "price", "ask1", "bid1", "ask_total", "bid_total", "vi", "volume"],
                         [[now, num(b.get("now_prc")), num(b.get("s1_aprc")), num(b.get("b1_aprc")),
                           num(b.get("s_askprc_tl_q")), num(b.get("b_askprc_tl_q")), b.get("krx_vit_knd_cd"),
                           num(b.get("vlm"))]])

    def foreign(self, code):
        body = self._call("IVU10420", {"excg_clsf": self.excg, "is_cd": code})
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        rows = []
        for rec in records(body) or [body]:
            for k, name in rec.items():
                m = re.fullmatch(r"([sb])_scrts_cmpny_nm(\d+)", k)
                if m and name:
                    side, i = m.groups()
                    rows.append([now, "S" if side == "s" else "B", str(name).strip(), num(rec.get(f"{side}_q{i}"))])
        self.store.write(f"{code}_foreign", ["recv", "side", "broker", "qty"], rows)

    def investor(self, code):
        today = datetime.now().strftime("%Y%m%d")
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        rows = []
        for side, trd in (("B", "2"), ("S", "3")):
            body = self._call("IVU10430", {"excg_clsf": self.excg, "is_cd": code, "strt_dt": today, "end_dt": today,
                                           "amt_q_clsf": "2", "trd_clsf": trd, "acml_clsf": "0"})
            for r in records(body):
                if str(r.get("dt", today)) == today:
                    rows.append([now, side, r.get("mtrl_clsf"), num(r.get("indv")), num(r.get("fgnr")), num(r.get("ogn")),
                                 num(r.get("pgm")), num(r.get("frgn_afflt_dl_orgn_sum"))])
        self.store.write(f"{code}_investor", ["recv", "side", "estimate", "indv", "fgnr", "ogn", "pgm", "fgn_brokers"], rows)

    def program(self, code):
        body = self._call("IVU10450", {"excg_clsf": self.excg, "is_cd": code, "amt_q_clsf": "2", "prd_clsf": "1", "inq_cnt": "20"})
        last = self.last_prog_tm.get(code, "")
        rows = sorted((r for r in records(body) if str(r.get("tm", "")) > last), key=lambda r: str(r.get("tm")))
        if rows:
            self.last_prog_tm[code] = str(rows[-1].get("tm"))
        self.store.write(f"{code}_program", ["tm", "price", "net_buy_q", "buy_q", "sell_q"],
                         [[r.get("tm"), num(r.get("now_prc")), num(r.get("nt_b_q")), num(r.get("b_q")), num(r.get("s_q"))] for r in rows])

    def index(self, _=None):
        body = self._call("IVSA0070", {})
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.store.write("index", ["recv", "id", "name", "value_p2", "change_pct_p2"],
                         [[now, r.get("indx_id"), r.get("indx_nm"), r.get("now_indx_p2"), r.get("up_dwn_r_p2")]
                          for r in records(body, "out2")])

    # ---- loop ----
    def run(self, until):
        iv = self.cfg["intervals"]
        tasks = []  # [due, priority, name, code]
        prio = {"ticks": 0, "book": 1, "index": 2, "foreign": 3, "program": 4, "investor": 5}
        for name in iv:
            if name == "index":
                tasks.append([0.0, prio[name], name, None])
            else:
                tasks += [[0.0, prio[name], name, code] for code in self.cfg["symbols"]]
        report_at = time.monotonic() + 30
        while datetime.now() < until:
            tasks.sort()
            task = tasks[0]
            wait = task[0] - time.monotonic()
            if wait > 0:
                time.sleep(min(wait, 1.0))
                continue
            _, _, name, code = task
            try:
                getattr(self, name)(code)
            except ApiError as e:
                self.errors += 1
                if code:
                    self.stats[code]["errors"] += 1
                print(f"[{datetime.now():%H:%M:%S}] {e}", flush=True)
            task[0] = time.monotonic() + iv[name]
            if time.monotonic() > report_at:
                report_at = time.monotonic() + 30
                self.report()
        self.report()

    def report(self):
        parts = [f"{self.cfg['symbols'][c]} 체결 {s['ticks']:,}건 누락량 {s['missed_vol']:,} 오류 {s['errors']}"
                 for c, s in self.stats.items()]
        print(f"[{datetime.now():%H:%M:%S}] " + " | ".join(parts), flush=True)


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    cfg["app_key"] = os.environ.get("KB_APP_KEY") or cfg.get("app_key")
    cfg["app_secret"] = os.environ.get("KB_APP_SECRET") or cfg.get("app_secret")
    return cfg


def at_today(hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--mock", action="store_true", help="fake API (no keys needed)")
    ap.add_argument("--now", action="store_true", help="ignore the session start time")
    ap.add_argument("--minutes", type=float, help="stop after this many minutes")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        cfg_path = HERE / "config.example.json"
        print(f"config.json이 없어 {cfg_path.name}을 사용합니다.")
    cfg = load_config(cfg_path)

    if args.mock:
        client = MockClient()
    else:
        client = KBClient(cfg["app_key"], cfg["app_secret"], HERE / ".token.json",
                          per_sec=cfg.get("requests_per_sec", 4), ip=cfg.get("ip"), mac=cfg.get("mac"))
        print(f"IP {client.ip} / MAC {client.mac} 로 접속합니다. (토큰은 이 값에 묶입니다)")

    start, end = at_today(cfg["session"]["start"]), at_today(cfg["session"]["end"])
    if args.minutes:
        end = datetime.fromtimestamp(time.time() + args.minutes * 60)
    if not args.now and datetime.now() < start:
        print(f"{start:%H:%M}까지 대기합니다...")
        while datetime.now() < start:
            time.sleep(5)

    root = Path(cfg.get("data_dir", "data"))
    if not root.is_absolute():
        root = HERE.parent / root
    store = Store(root)
    print(f"저장 위치: {store.dir}")
    try:
        Collector(client, store, cfg).run(end)
    except KeyboardInterrupt:
        print("중단했습니다.")
    finally:
        store.close()


if __name__ == "__main__":
    main()
