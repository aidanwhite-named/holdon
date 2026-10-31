"""Fake KB API that answers in the documented response shape, so the collector
pipeline can be tested without keys or outside market hours.

Value formats (numbers as strings, HHMMSS times, sell_buy_ccd 1=매도/2=매수) are
assumptions; the collector also saves raw samples of the real responses to check them.
"""
import math
import random
import time
from datetime import datetime


class _Stock:
    def __init__(self, price):
        self.price = price
        self.acml = 0
        self.buy = self.sell = 1
        self.trades = []  # newest last
        self.fgn = {"모건스탠리": [0, 0], "JP모간": [0, 0], "골드만": [0, 0]}
        self.inv = {"B": {"indv": 0, "fgnr": 0, "ogn": 0}, "S": {"indv": 0, "fgnr": 0, "ogn": 0}}
        self.last = time.monotonic()

    def advance(self):
        now = time.monotonic()
        n = min(200, int((now - self.last) * 8 + random.random()))
        self.last = now if n else self.last
        tick = 100 if self.price < 200000 else 500
        for _ in range(n):
            side = "2" if random.random() < 0.5 else "1"
            qty = max(1, int(math.exp(random.gauss(4.3, 1.1))))
            if random.random() < 0.03:
                self.price += tick if side == "2" else -tick
            self.acml += qty
            if side == "2":
                self.buy += qty
            else:
                self.sell += qty
            who = random.choices(["indv", "fgnr", "ogn"], [0.6, 0.2, 0.2])[0]
            self.inv["B" if side == "2" else "S"][who] += qty
            if who == "fgnr":
                self.fgn[random.choice(list(self.fgn))][0 if side == "2" else 1] += qty
            self.trades.append({
                "ccls_tm": datetime.now().strftime("%H%M%S"), "excg_cd": "KRX",
                "ccls_prc": str(self.price), "sell_buy_ccd": side, "ccls_q": str(qty),
                "acml_vlm": str(self.acml), "ccls_strn_p2": str(round(self.buy / self.sell * 10000)),
            })
        del self.trades[:-300]


class MockClient:
    PRICES = {"005930": 71000, "005380": 245000, "298040": 420000}

    def __init__(self):
        self.stocks = {}

    def _s(self, code):
        if code not in self.stocks:
            self.stocks[code] = _Stock(self.PRICES.get(code, 50000))
        s = self.stocks[code]
        s.advance()
        return s

    def call(self, tr, body):
        time.sleep(0.02)
        tr = tr.upper()
        code = body.get("is_cd") or body.get("shrt_cd")
        if tr == "IVU10080":
            s = self._s(code)
            n = int(body.get("inq_cnt") or 30)
            return {"out": list(reversed(s.trades[-n:]))}
        if tr == "IVU10070":
            s = self._s(code)
            return {"now_prc": str(s.price), "s1_aprc": str(s.price + 100), "b1_aprc": str(s.price),
                    "s_askprc_tl_q": str(random.randint(50000, 150000)), "b_askprc_tl_q": str(random.randint(50000, 150000)),
                    "krx_vit_knd_cd": "0", "vlm": str(s.acml)}
        if tr == "IVU10420":
            s = self._s(code)
            rec = {}
            for i, (name, (b, sl)) in enumerate(s.fgn.items(), 1):
                rec.update({f"b_scrts_cmpny_nm{i}": name, f"b_q{i}": str(b), f"s_scrts_cmpny_nm{i}": name, f"s_q{i}": str(sl)})
            return {"out": [rec]}
        if tr == "IVU10430":
            s = self._s(code)
            side = "B" if body.get("trd_clsf") == "2" else "S"
            v = s.inv[side]
            return {"out": [{"mtrl_clsf": "1", "dt": datetime.now().strftime("%Y%m%d"),
                             "indv": str(v["indv"]), "fgnr": str(v["fgnr"]), "ogn": str(v["ogn"]), "pgm": "0",
                             "frgn_afflt_dl_orgn_sum": str(v["fgnr"])}]}
        if tr == "IVU10450":
            s = self._s(code)
            return {"out": [{"tm": datetime.now().strftime("%H%M%S"), "now_prc": str(s.price),
                             "nt_b_q": str(random.randint(-5000, 5000)), "b_q": "0", "s_q": "0"}]}
        if tr == "IVSA0070":
            return {"out2": [{"indx_id": "001", "indx_nm": "코스피", "now_indx_p2": "258000",
                              "up_dwn_r_p2": str(random.randint(-50, 50))}]}
        return {}
