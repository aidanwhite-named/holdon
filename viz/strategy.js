// Signal / risk / paper-execution layer. No rendering here, so the same logic
// can later be ported to the Python live engine as-is.
//
// Input:  Strat.onTrade({ t, side:'B'|'S', qty, price, broker, inv:'IND'|'FOR'|'INS' })
//         Strat.onTick(t, { index })   // index = KOSPI change from open, as a fraction
// Output: Strat.onOrder(order) callback, Strat.st (features, checks, positions, P&L)
//
// Live data note: tick trades don't carry the investor type. In the live engine,
// FOR flow is taken from the change in the foreign-broker (외국계 창구) cumulative
// volume, and INS/IND from the periodic investor-flow snapshots.
(function (global) {
  const INVS = ['IND', 'FOR', 'INS'];
  const tickOf = p => p < 2000 ? 1 : p < 5000 ? 5 : p < 20000 ? 10 : p < 50000 ? 50 : p < 200000 ? 100 : p < 500000 ? 500 : 1000;

  const cfg = {
    // How much each investor group counts in the weighted 체결강도 and flow index.
    weights: { FOR: 1.0, INS: 0.6, IND: 0.2 },
    trend: {
      on: true, requireForeign: true,
      flowWin: 20,          // s, window for weighted 체결강도
      slopeWin: 30,         // s, regression window for the slope
      slopeMin: 1.5,        // %p per second
      r2Min: 0.7,           // how straight the rise must be
      csMin: 120,           // weighted 체결강도 floor, %
      wfsMin: 0.15,         // weighted net-buy index floor (-1..1)
      forPersistMin: 10,    // s of continuous foreign net buying
      tp: 0.006, sl: 0.004, maxHold: 300, cooldown: 30, budget: 3e6,
    },
    drop: {
      on: true,
      dropPct: 0.02,        // fall from the recent high
      lookback: 5,          // s
      indexMax: -0.003,     // skip if KOSPI fell more than this in 10 s (market-wide move)
      concMin: 0.5,         // one broker's share of the selling (fat-finger signature)
      forSellBlock: 20,     // skip if foreigners had been net selling this long (real selling)
      retrace: 0.5,         // take profit at this share of the drop recovered
      sl: 0.02, maxHold: 180, cooldown: 30, budget: 3e6,
    },
    risk: { capital: 1e7, dailyLossLimit: 2e5, fee: 0.00015, tax: 0.002, slipTicks: 1 },
  };

  const freshState = () => ({
    t: 0, sampleT: -1, trades: [], samples: [], idx: [], pv: 0, vol: 0, last: 0,
    forPersist: 0, forSellPersist: 0,
    pos: { trend: null, drop: null }, lastExit: { trend: -1e9, drop: -1e9 },
    realized: 0, unreal: 0, costs: 0, log: [], killed: false, halted: false,
    feat: {}, checks: { trend: [], drop: [] },
  });
  const st = freshState();

  function onTrade(tr) {
    st.trades.push(tr);
    st.pv += tr.price * tr.qty; st.vol += tr.qty;
    st.last = tr.price;
  }

  function sumSince(t0) {
    const s = { B: { IND: 0, FOR: 0, INS: 0 }, S: { IND: 0, FOR: 0, INS: 0 } };
    for (let i = st.trades.length - 1; i >= 0 && st.trades[i].t >= t0; i--) s[st.trades[i].side][st.trades[i].inv] += st.trades[i].qty;
    return s;
  }
  function priceAt(t0) { for (const tr of st.trades) if (tr.t >= t0) return tr.price; return st.last; }
  function linreg(pts) {
    const n = pts.length; let mx = 0, my = 0;
    for (const [x, y] of pts) { mx += x; my += y; }
    mx /= n; my /= n;
    let sxx = 0, sxy = 0, syy = 0;
    for (const [x, y] of pts) { sxx += (x - mx) ** 2; sxy += (x - mx) * (y - my); syy += (y - my) ** 2; }
    return { slope: sxx ? sxy / sxx : 0, r2: sxx && syy ? sxy * sxy / (sxx * syy) : 0 };
  }

  function onTick(t, mkt) {
    st.t = t;
    if (t - st.sampleT < 0.5) return;
    st.sampleT = t;
    while (st.trades.length && st.trades[0].t < t - 60) st.trades.shift();
    if (!st.last) return;
    const T = cfg.trend, D = cfg.drop, W = cfg.weights;

    const s = sumSince(t - T.flowWin);
    let Bw = 0, Sw = 0;
    for (const k of INVS) { Bw += W[k] * s.B[k]; Sw += W[k] * s.S[k]; }
    const cs = Math.min(500, Bw / Math.max(Sw, 1) * 100);
    const wfs = Bw + Sw ? (Bw - Sw) / (Bw + Sw) : 0;

    const s10 = sumSince(t - 10), fnet = s10.B.FOR - s10.S.FOR;
    st.forPersist = fnet > 0 ? st.forPersist + 0.5 : 0;
    st.forSellPersist = fnet < 0 ? st.forSellPersist + 0.5 : 0;

    st.samples.push({ t, cs });
    while (st.samples.length && st.samples[0].t < t - T.slopeWin) st.samples.shift();
    const { slope, r2 } = st.samples.length >= T.slopeWin * 2 * 0.8 ? linreg(st.samples.map(p => [p.t, p.cs])) : { slope: 0, r2: 0 };

    const price = st.last, vwap = st.pv / st.vol;
    const pchg = price / priceAt(t - T.slopeWin) - 1;
    const absorb = slope > 0 && cs >= T.csMin && pchg <= 0;

    let high = price, sellTot = 0; const sells = {};
    for (let i = st.trades.length - 1; i >= 0 && st.trades[i].t >= t - D.lookback; i--) {
      const tr = st.trades[i];
      if (tr.price > high) high = tr.price;
      if (tr.side === 'S') { sells[tr.broker] = (sells[tr.broker] || 0) + tr.qty; sellTot += tr.qty; }
    }
    const drop = (high - price) / high;
    const conc = sellTot ? Math.max(...Object.values(sells)) / sellTot : 0;

    st.idx.push({ t, v: mkt.index });
    while (st.idx.length && st.idx[0].t < t - 10) st.idx.shift();
    const idxChg = mkt.index - st.idx[0].v;

    const f = st.feat = { cs, wfs, slope, r2, fnet, absorb, vwap, pchg, drop, high, conc, idxChg, price };

    for (const k of ['trend', 'drop']) {
      const p = st.pos[k];
      if (p) { const why = exitReason(k, p, f, t); if (why) sell(k, why, t); }
    }
    st.unreal = 0;
    for (const k in st.pos) if (st.pos[k]) st.unreal += (price - st.pos[k].px) * st.pos[k].qty;
    if (!st.halted && st.realized + st.unreal <= -cfg.risk.dailyLossLimit) st.halted = true;
    const canEnter = !st.killed && !st.halted;

    st.checks.trend = [
      ['기울기', slope >= T.slopeMin], ['직선성 R²', r2 >= T.r2Min], ['체결강도', cs >= T.csMin],
      ['세력지수', wfs >= T.wfsMin], ['외인 지속', !T.requireForeign || st.forPersist >= T.forPersistMin],
      ['VWAP 위', price >= vwap], ['흡수 아님', !absorb], ['쿨다운', t - st.lastExit.trend >= T.cooldown],
    ];
    if (T.on && canEnter && !st.pos.trend && st.checks.trend.every(c => c[1]))
      buy('trend', T.budget, `기울기 ${slope.toFixed(1)}%p/s · R² ${r2.toFixed(2)} · 외인 ${st.forPersist}초 순매수`, t);

    st.checks.drop = [
      ['낙폭', drop >= D.dropPct], ['지수 안정', idxChg > D.indexMax], ['창구 집중', conc >= D.concMin],
      ['외인 매도 지속 아님', st.forSellPersist < D.forSellBlock], ['쿨다운', t - st.lastExit.drop >= D.cooldown],
    ];
    if (D.on && canEnter && !st.pos.drop && st.checks.drop.every(c => c[1]))
      buy('drop', D.budget, `고점 대비 -${(drop * 100).toFixed(1)}% · 매도 ${Math.round(conc * 100)}% 한 창구 집중`, t,
        { target: price + D.retrace * (high - price) });
  }

  function exitReason(k, p, f, t) {
    const C = cfg[k];
    if (k === 'trend') {
      if (f.price >= p.px * (1 + C.tp)) return '목표가';
      if (f.price <= p.px * (1 - C.sl)) return '손절';
      if (st.forSellPersist >= 5) return '외인 순매도 전환';
      if (f.slope <= -C.slopeMin && f.r2 >= C.r2Min) return '체결강도 하락 추세';
    } else {
      if (f.price >= p.target) return '반등 목표 도달';
      if (f.price <= p.px * (1 - C.sl)) return '손절';
    }
    if (t - p.t >= C.maxHold) return '시간 청산';
    return null;
  }

  function buy(k, budget, reason, t, extra) {
    const R = cfg.risk;
    const px = st.last + tickOf(st.last) * R.slipTicks;
    let used = 0; for (const j in st.pos) if (st.pos[j]) used += st.pos[j].px * st.pos[j].qty;
    const qty = Math.floor(Math.min(budget, R.capital - used) / px);
    if (qty <= 0) return;
    const fee = px * qty * R.fee;
    st.costs += fee; st.realized -= fee;
    st.pos[k] = { qty, px, t, fee, ...extra };
    record({ t, side: 'B', k, qty, px, reason });
  }

  function sell(k, reason, t) {
    const R = cfg.risk, p = st.pos[k];
    const px = st.last - tickOf(st.last) * R.slipTicks;
    const cost = px * p.qty * (R.fee + R.tax), gross = (px - p.px) * p.qty;
    st.costs += cost; st.realized += gross - cost;
    st.pos[k] = null; st.lastExit[k] = t;
    record({ t, side: 'S', k, qty: p.qty, px, reason, pnl: gross - cost - p.fee });
  }

  function record(o) {
    st.log.push(o);
    if (st.log.length > 100) st.log.shift();
    if (api.onOrder) api.onOrder(o);
  }

  function kill() { for (const k in st.pos) if (st.pos[k]) sell(k, '긴급 정지', st.t); st.killed = true; }
  function resume() { st.killed = false; st.halted = false; }
  function reset() { Object.assign(st, freshState()); }

  const api = { cfg, st, onTrade, onTick, kill, resume, reset, onOrder: null };
  global.Strat = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
