"""
Quotex Trading Bot Engine v11.5 — Full Market Adaptive Strategy.
ATR-scaled entry thresholds + Market regime detection + Per-confidence learning.
RSI mandatory slope + MACD + Stoch with dynamic strength gates.

v11.5 CHANGES (from v11.4):
  - Removed: prev2 logic for ALL indicators (RSI, CCI, STOCH, MACD)
  - Gradual check: 3-point → 2-point (prev + current only)
  - Delta: current - prev2 → current - prev
  - Display: 3 timestamps → 2 timestamps only
  - _grad() helper updated for 2-point check

Designed to be imported by server.py for web UI integration.
"""

import asyncio
import json
import os
import time
from datetime import datetime
from pyquotex.stable_api import Quotex
from dotenv import load_dotenv

# Load from config.env if it exists (local), otherwise from system env vars (cloud)
if os.path.exists("config.env"):
    load_dotenv("config.env")
else:
    load_dotenv()

EMAIL    = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")

# ══════════════════════════════════════════════
# CONFIG — v11.5
# ══════════════════════════════════════════════
MIN_PAYOUT          = 85
TRADE_ENTRY_LIMIT   = 50
TRADES_FILE         = "trades.json"
ASSET_STATS_FILE    = "asset_stats.json"

ASSET_MIN_TRADES    = 5
ASSET_MIN_WINRATE   = 38

MIN_CONFIDENCE      = 68
MIN_CONF_MODERATE   = 68
MIN_CONF_STRONG     = 72
CONSEC_LOSS_LIMIT   = 3

ENTRY_CANDLES       = 50
ATR_PERIOD          = 14
MAX_CANDLE_JUMP_PCT = 5.0

# ── Indicator Params ──────────────────────────
MACD_FAST           = 12
MACD_SLOW           = 26
MACD_SIGNAL         = 9
RSI_PERIOD          = 14

ADX_PERIOD          = 14
ADX_MIN_STRENGTH    = 18
ADX_STRONG          = 33

RSI_BLOCK_WEAK_OVERBOUGHT = 74
RSI_BLOCK_WEAK_OVERSOLD   = 26

MACD_MIN_HIST_ABS      = 0.0000001
CANDLE_COUNT_MIN_RATIO = 0.50

STOCH_CALL_MAX_DK_DIFF = 8
STOCH_PUT_MAX_KD_DIFF  = 14
RSI_CALL_HARD_BLOCK    = 84

# ── v11.5 Adaptive Entry Thresholds (BASE values — scaled by ATR at runtime) ──
RSI_MIN_DELTA_BASE     = 1.0
STOCH_MIN_KD_BASE      = 3.0
MACD_HIST_ATR_RATIO    = 0.001
CCI_BULL_BASE          = 0
CCI_BEAR_BASE          = 0

# ── Martingale Config ─────────────────────────
MARTINGALE_MULTIPLIER = 2.0
MARTINGALE_MAX_STEPS  = 2

# ── v10 Accuracy Config ──────────────────────
HTF_MULTIPLIER        = 5
HTF_CANDLES           = 40
SR_LOOKBACK           = 3
SR_ATR_ZONE           = 1.5
DIVERGENCE_BARS       = 30
TREND_CONSISTENCY_LB  = 12
PATTERN_CONFIRM_BONUS = True
MAX_SCAN_ASSETS       = 60

# ── v10 New Strategy Thresholds ───────────────
STOCH_EXTREME_CALL    = 16
STOCH_EXTREME_PUT     = 84
BOUNCE_STOCH_CALL_MAX = 25
BOUNCE_STOCH_PUT_MIN  = 75
BOUNCE_RSI_DEAD_LOW   = 45
BOUNCE_RSI_DEAD_HIGH  = 55
BOUNCE_HTF_BLOCK_ADX  = 20

FOREX_PAIRS = [
    "USD","EUR","GBP","JPY","AUD","NZD","CAD","CHF",
    "INR","BRL","MXN","PKR","DZD","IDR","ARS","NGN",
    "EGP","PHP","BDT","SGD","ZAR","THB","HUF","CZK",
    "NOK","SEK","DKK","PLN","TRY","RUB","KRW","TWD"
]

# ══════════════════════════════════════════════
# FORMAT HELPERS
# ══════════════════════════════════════════════
def fmt1(v):  return f"{v:.1f}"  if v is not None else "N/A"
def fmt2(v):  return f"{v:.2f}"  if v is not None else "N/A"
def fmt3(v):  return f"{v:.3f}"  if v is not None else "N/A"
def fmt7(v):  return f"{v:+.7f}" if v is not None else "N/A"

# ══════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════
def get_tf_seconds(label):
    return {"1 min":60,"2 min":120,"3 min":180,"5 min":300,
            "10 min":600,"15 min":900,"30 min":1800,"60 min":3600}[label]

def get_htf_seconds(entry_dur):
    mapping = {60:300, 120:300, 180:900, 300:900, 600:1800, 900:3600}
    return mapping.get(entry_dur, entry_dur * HTF_MULTIPLIER)

def now_str():  return datetime.now().strftime("%H:%M:%S")
def now_full(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_balance(profile, account_type):
    return profile.demo_balance if account_type == "PRACTICE" else profile.live_balance

def calc_martingale_amount(base, step):
    return round(base * (MARTINGALE_MULTIPLIER ** step), 2)

# ══════════════════════════════════════════════
# CANDLE SANITY
# ══════════════════════════════════════════════
def is_valid(candles):
    for c in candles:
        if c["close"]<=0 or c["open"]<=0 or c["high"]<=0 or c["low"]<=0:
            return False
    closes = [c["close"] for c in candles]
    for i in range(1, len(closes)):
        if closes[i-1]>0:
            if abs(closes[i]-closes[i-1])/closes[i-1]*100 > MAX_CANDLE_JUMP_PCT:
                return False
    return True

# ══════════════════════════════════════════════
# CORE INDICATORS
# ══════════════════════════════════════════════
def calc_rsi(candles, period=RSI_PERIOD):
    if len(candles)<period+1: return None
    closes = [c["close"] for c in candles]
    gains, losses = [], []
    for i in range(1,len(closes)):
        d = closes[i]-closes[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag = sum(gains[:period])/period
    al = sum(losses[:period])/period
    for i in range(period,len(gains)):
        ag = (ag*(period-1)+gains[i])/period
        al = (al*(period-1)+losses[i])/period
    if al==0: return 100.0
    return round(100-(100/(1+ag/al)),2)

def calc_rsi_series(candles, period=RSI_PERIOD):
    if len(candles)<period+1: return []
    closes = [c["close"] for c in candles]
    gains, losses = [], []
    for i in range(1,len(closes)):
        d = closes[i]-closes[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag = sum(gains[:period])/period
    al = sum(losses[:period])/period
    out = []
    if al==0: out.append(100.0)
    else: out.append(round(100-(100/(1+ag/al)),2))
    for i in range(period,len(gains)):
        ag = (ag*(period-1)+gains[i])/period
        al = (al*(period-1)+losses[i])/period
        if al==0: out.append(100.0)
        else: out.append(round(100-(100/(1+ag/al)),2))
    return out

def calc_macd(candles, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL):
    if len(candles)<slow+signal: return None,None,None,None,None
    closes = [c["close"] for c in candles]
    def _ema(values, period):
        if len(values)<period: return []
        k   = 2/(period+1)
        ema = [sum(values[:period])/period]
        for v in values[period:]:
            ema.append(v*k + ema[-1]*(1-k))
        return ema
    ema_fast    = _ema(closes, fast)
    ema_slow    = _ema(closes, slow)
    diff        = len(ema_fast)-len(ema_slow)
    if diff>0: ema_fast=ema_fast[diff:]
    macd_line   = [f-s for f,s in zip(ema_fast,ema_slow)]
    if len(macd_line)<signal: return None,None,None,None,None
    sig_line    = _ema(macd_line, signal)
    if len(sig_line)<2: return None,None,None,None,None
    hist      = macd_line[-1]-sig_line[-1]
    prev_hist = macd_line[-2]-sig_line[-2]
    return round(macd_line[-1],8),round(sig_line[-1],8),round(hist,8),round(prev_hist,8),round(macd_line[-2],8)

def calc_adx(candles, period=ADX_PERIOD):
    if len(candles)<period*2: return None,None,None
    trl,pdml,ndml=[],[],[]
    for i in range(1,len(candles)):
        h,l   = candles[i]["high"],   candles[i]["low"]
        ph,pl = candles[i-1]["high"], candles[i-1]["low"]
        pc    = candles[i-1]["close"]
        tr  = max(h-l,abs(h-pc),abs(l-pc))
        pdm = max(h-ph,0) if (h-ph)>(pl-l) else 0
        ndm = max(pl-l,0) if (pl-l)>(h-ph) else 0
        trl.append(tr); pdml.append(pdm); ndml.append(ndm)
    def wilder(data,p):
        r=[sum(data[:p])]
        for v in data[p:]: r.append(r[-1]-r[-1]/p+v)
        return r
    atr_s=wilder(trl,period); pdm_s=wilder(pdml,period); ndm_s=wilder(ndml,period)
    if not atr_s or atr_s[-1]==0: return None,None,None
    pdi=100*pdm_s[-1]/atr_s[-1]; ndi=100*ndm_s[-1]/atr_s[-1]
    dx=[]
    for a,p,n in zip(atr_s,pdm_s,ndm_s):
        if a==0: continue
        _p=100*p/a; _n=100*n/a; d=_p+_n
        if d>0: dx.append(100*abs(_p-_n)/d)
    if len(dx)<period: return None,None,None
    adx=sum(dx[-period:])/period
    return round(adx,2),round(pdi,2),round(ndi,2)

def calc_atr(candles, period=ATR_PERIOD):
    if len(candles)<period+1: return None,None
    trs=[]
    for i in range(1,len(candles)):
        h,l,pc=candles[i]["high"],candles[i]["low"],candles[i-1]["close"]
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    a=sum(trs[:period])/period
    for tr in trs[period:]: a=(a*(period-1)+tr)/period
    price=candles[-1]["close"]
    pct=a/price*100 if price else 0
    return round(a,6),round(pct,4)

def calc_stochastic(candles, k_period=14, d_period=3):
    if len(candles)<k_period+d_period: return None,None
    kvs=[]
    for i in range(k_period-1,len(candles)):
        w=candles[i-k_period+1:i+1]
        lo=min(c["low"] for c in w); hi=max(c["high"] for c in w)
        cl=candles[i]["close"]
        k=((cl-lo)/(hi-lo)*100) if (hi-lo)>0 else 50.0
        kvs.append(round(k,2))
    if len(kvs)<d_period: return None,None
    d=sum(kvs[-d_period:])/d_period
    return round(kvs[-1],2),round(d,2)

def calc_cci(candles, period=20):
    if len(candles) < period:
        return None
    tp_list = [(c["high"] + c["low"] + c["close"]) / 3 for c in candles]
    recent  = tp_list[-period:]
    sma     = sum(recent) / period
    mad     = sum(abs(x - sma) for x in recent) / period
    if mad == 0:
        return 0.0
    cci = (tp_list[-1] - sma) / (0.015 * mad)
    return round(cci, 2)

def calc_cci_series(candles, period=20):
    if len(candles) < period:
        return []
    tp_list = [(c["high"] + c["low"] + c["close"]) / 3 for c in candles]
    out = []
    for i in range(period - 1, len(tp_list)):
        recent = tp_list[i - period + 1 : i + 1]
        sma    = sum(recent) / period
        mad    = sum(abs(x - sma) for x in recent) / period
        if mad == 0:
            out.append(0.0)
        else:
            out.append(round((tp_list[i] - sma) / (0.015 * mad), 2))
    return out

def calc_candle_count(candles, lookback=10):
    safe  =candles[:-1] if len(candles)>lookback+1 else candles
    sub   =safe[-lookback:] if len(safe)>=lookback else safe
    green =sum(1 for c in sub if c["close"]>c["open"])
    red   =sum(1 for c in sub if c["close"]<c["open"])
    doji  =len(sub)-green-red
    total =len(sub)
    gr=green/total if total else 0
    rr=red/total   if total else 0
    if   gr>=CANDLE_COUNT_MIN_RATIO: dom="call"
    elif rr>=CANDLE_COUNT_MIN_RATIO: dom="put"
    else:                            dom="neutral"
    return green,red,doji,total,round(gr,2),round(rr,2),dom

# ══════════════════════════════════════════════
# MARKET REGIME & HTF (v11.6 — ADX only, no BB)
# ══════════════════════════════════════════════
def detect_market_regime(candles):
    if not candles or len(candles) < ADX_PERIOD * 2:
        return "UNKNOWN"
    adx, _, _ = calc_adx(candles)
    if adx is None:
        return "UNKNOWN"
    if adx < 15.0:
        return "RANGING"
    elif adx >= 30.0:
        return "BREAKOUT"
    return "TRENDING"

def htf_trend_check(htf_candles):
    """v11.6: PDI/NDI primary — RSI is optional confirmation, not mandatory.
    Scoring:
      PDI/NDI gap >= 3  → direction determined
      RSI confirms      → stronger signal (noted in debug string)
      RSI conflicts     → direction still given, just not boosted
    Returns None only when ADX/PDI/NDI calc fails or PDI==NDI (no clear side).
    """
    if not htf_candles or len(htf_candles) < ADX_PERIOD * 2 + 2:
        return None, None, None
    adx, pdi, ndi = calc_adx(htf_candles)
    if adx is None or pdi is None or ndi is None:
        return None, None, None

    # ── PDI/NDI must have a clear gap to avoid noise ──
    gap = abs(pdi - ndi)
    if gap < 2.0:
        return None, adx, f"PDI:{pdi:.1f}/NDI:{ndi:.1f}(no gap)"

    # ── Primary direction from PDI/NDI ──
    if pdi > ndi:
        htf_dir = "call"
    else:
        htf_dir = "put"

    # ── RSI as optional confirmation (does not block, only annotates) ──
    rsi_confirm = ""
    rsi_now  = calc_rsi(htf_candles)
    rsi_prev = calc_rsi(htf_candles[:-1]) if len(htf_candles) > RSI_PERIOD + 2 else rsi_now
    if rsi_now is not None and rsi_prev is not None:
        if htf_dir == "call" and rsi_now >= rsi_prev:
            rsi_confirm = "+RSI✓"
        elif htf_dir == "put" and rsi_now <= rsi_prev:
            rsi_confirm = "+RSI✓"
        else:
            rsi_confirm = "+RSI~"  # conflict noted but not blocking

    return htf_dir, adx, f"PDI:{pdi:.1f}/NDI:{ndi:.1f}{rsi_confirm}"

# ══════════════════════════════════════════════
# ADAPTIVE LEARNING
# ══════════════════════════════════════════════
def calc_dynamic_entry_thresholds(atr_pct):
    atr = max(min(atr_pct if atr_pct else 0.10, 0.30), 0.04)
    scale = 0.5 + ((atr - 0.04) / 0.21) * 1.5
    scale = max(0.5, min(scale, 2.0))
    return {
        "rsi_min_delta": round(RSI_MIN_DELTA_BASE * scale, 2),
        "stoch_min_kd": round(STOCH_MIN_KD_BASE * scale, 1),
        "cci_bull": CCI_BULL_BASE,
        "cci_bear": CCI_BEAR_BASE,
        "atr_scale": round(scale, 2),
    }


def learn_adaptive_thresholds():
    """Rebuilt adaptive learning for Gradual RSI+CCI strategy."""
    adaptive = {
        "adx_floor": 15.0,
        "htf_min_adx": 15.0,
        "rsi_min_delta_mult": 1.0,
        "cci_min_delta": 15,
        "require_both_support": False,
        "macd_only_wr": None,
        "stoch_only_wr": None,
        "both_support_wr": None,
        "small_cci_wr": None,
        "learned": False,
    }

    if not os.path.exists(TRADES_FILE):
        return adaptive

    try:
        with open(TRADES_FILE) as f:
            data = json.load(f)
    except:
        return adaptive

    all_trades = []
    for sess in data.get("sessions", []):
        all_trades.extend(sess.get("trades", []))
    recent = all_trades[-50:]

    if len(recent) < 5:
        return adaptive

    adaptive["learned"] = True

    def wr(trades):
        if not trades: return 50.0
        n = len(trades)
        total_w, total_wt = 0.0, 0.0
        for i, t in enumerate(trades):
            weight = 2.0 if i >= (n - 15) else 1.0
            total_wt += weight
            # Treat LATE_ENTRY_LOSS as a 'Win' for strategy evaluation, because the candle analysis was actually correct!
            if t.get("result") == "WIN" or t.get("trade_result_type") == "LATE_ENTRY_LOSS":
                total_w += weight
        return (total_w / total_wt * 100) if total_wt > 0 else 50.0

    # RSI delta learning
    small_rsi_delta = [t for t in recent if t.get("rsi_total_delta") is not None
                       and abs(t["rsi_total_delta"]) < 3]
    if len(small_rsi_delta) >= 3:
        wr_srd = wr(small_rsi_delta)
        if wr_srd < 35:
            adaptive["rsi_min_delta_mult"] = 2.0
        elif wr_srd < 45:
            adaptive["rsi_min_delta_mult"] = 1.5
        else:
            adaptive["rsi_min_delta_mult"] = 1.0

    # CCI delta learning
    small_cci_delta = [t for t in recent if t.get("cci_total_delta") is not None
                       and abs(t["cci_total_delta"]) < 25]
    if len(small_cci_delta) >= 3:
        wr_scd = wr(small_cci_delta)
        adaptive["small_cci_wr"] = round(wr_scd, 1)
        if wr_scd < 35:
            adaptive["cci_min_delta"] = 30
        elif wr_scd < 45:
            adaptive["cci_min_delta"] = 20
        else:
            adaptive["cci_min_delta"] = 15

    # ── DEEP PATTERN ADAPTIVE LEARNING ──
    wrong_analysis = [t for t in recent if t.get("trade_result_type") == "WRONG_ANALYSIS" and t.get("result") == "LOSS"]
    late_entries = [t for t in recent if t.get("trade_result_type") == "LATE_ENTRY_LOSS"]

    # 1. No Man's Land Block
    if len(wrong_analysis) >= 4:
        avg_rsi = sum(t.get("rsi", 50) for t in wrong_analysis) / len(wrong_analysis)
        avg_cci = sum(t.get("cci", 0) for t in wrong_analysis) / len(wrong_analysis)
        if 40 <= avg_rsi <= 60 and abs(avg_cci) < 30:
            adaptive["avoid_middle_zone"] = {"rsi_center": avg_rsi, "cci_center": avg_cci}

    # 2. Overextended Move Block
    if len(late_entries) >= 3:
        avg_cci_late = sum(t.get("cci", 0) for t in late_entries) / len(late_entries)
        if abs(avg_cci_late) >= 30:
            adaptive["avoid_overextended"] = True

    # 3. Support Count Learning
    support_1 = [t for t in recent if t.get("support_count", 0) == 1]
    if len(support_1) >= 4 and wr(support_1) < 48:
        adaptive["macd_mandatory"] = True

    # 5. Stoch Overextended Block
    stoch_ext = [t for t in recent if "stoch_overextended" in t.get("diagnosis", []) and t.get("result") == "LOSS"]
    if len(stoch_ext) >= 2:
        wr_se = wr(stoch_ext)
        if wr_se < 40:
            adaptive["block_stoch_overextended"] = True

    # 4. Conf 99 Smart Blacklist
    conf_99_losses = [t for t in recent if t.get("confidence", 0) >= 99 and t.get("result") == "LOSS"]
    conf_99_pairs = {}
    for t in conf_99_losses:
        a = t.get("asset")
        if a:
            conf_99_pairs[a] = conf_99_pairs.get(a, 0) + 1
    adaptive["conf_99_blacklist"] = [a for a, count in conf_99_pairs.items() if count >= 2]

    # Retain HTF learning & ADX floor as they are still useful
    low_adx = [t for t in recent if t.get("adx") is not None and t["adx"] < 22]
    if len(low_adx) >= 3:
        wr_adx = wr(low_adx)
        if wr_adx < 35: adaptive["adx_floor"] = 22.0
        elif wr_adx < 50: adaptive["adx_floor"] = 20.0
        else: adaptive["adx_floor"] = 18.0

    htf_weak = [t for t in recent if t.get("htf_adx") is not None and t["htf_adx"] < 20]
    if len(htf_weak) >= 3:
        wr_htf = wr(htf_weak)
        if wr_htf < 40: adaptive["htf_min_adx"] = 22.0
        elif wr_htf < 55: adaptive["htf_min_adx"] = 18.0
        else: adaptive["htf_min_adx"] = 14.0

    # ── SUPER ADAPTIVE: Dynamic Blocks ──
    adaptive["block_regimes"] = []
    adaptive["block_direction"] = []
    adaptive["micro_blacklist"] = []
    adaptive["htf_penalty"] = False

    try:
        current_time = datetime.now()
        
        # Helper to check if a trade is within the last 60 minutes
        def within_60_mins(time_str):
            if not time_str: return False
            try:
                t_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                return (current_time - t_time).total_seconds() < 3600
            except:
                return False

        # 1. Regime Block
        regime_trades = {}
        for t in recent:
            r = t.get("regime")
            if r:
                if r not in regime_trades: regime_trades[r] = []
                regime_trades[r].append(t)
        for r, trades in regime_trades.items():
            if len(trades) >= 4 and wr(trades) < 35:
                if within_60_mins(trades[-1].get("entry_time")):
                    adaptive["block_regimes"].append(r)

        # 2. Direction Block
        dir_trades = {"call": [], "put": []}
        for t in recent:
            d = t.get("direction", "").lower()
            if d in ["call", "put"]:
                dir_trades[d].append(t)
        for d, trades in dir_trades.items():
            if len(trades) >= 4 and wr(trades) < 35:
                if within_60_mins(trades[-1].get("entry_time")):
                    adaptive["block_direction"].append(d)

        # 3. Micro-Blacklist (Asset Level)
        asset_trades = {}
        for t in all_trades[-20:]:
            a = t.get("asset")
            if a:
                if a not in asset_trades: asset_trades[a] = []
                asset_trades[a].append(t)
        for a, trades in asset_trades.items():
            if len(trades) >= 2:
                if trades[-1].get("result") == "LOSS" and trades[-2].get("result") == "LOSS":
                    if within_60_mins(trades[-1].get("entry_time")):
                        adaptive["micro_blacklist"].append(a)

        # 4. HTF Penalty
        htf_trades = [t for t in recent if "(HTF\u2713)" in t.get("reason", "")]
        if len(htf_trades) >= 3 and wr(htf_trades) < 35:
            if within_60_mins(htf_trades[-1].get("entry_time")):
                adaptive["htf_penalty"] = True
                
    except Exception as e:
        pass # Safe fallback

    return adaptive


# ══════════════════════════════════════════════
# DECISION ENGINE v11.5
# 2-candle logic: prev + current only (prev2 fully removed)
# ══════════════════════════════════════════════
def decide(candles, name, entry_dur=60, htf_candles=None, adaptive=None):
    if len(candles)<MACD_SLOW+MACD_SIGNAL+5:
        return None,0,"FAIL — not enough candles",{}

    atr_abs,atr_pct=calc_atr(candles)
    if atr_pct is not None and atr_pct<0.04:
        return None,0,f"FAIL — flat market (ATR:{atr_pct:.4f}%)",{}

    htf_dir, htf_adx, htf_ema = htf_trend_check(htf_candles) if htf_candles else (None, None, None)

    adx,pdi,ndi                              = calc_adx(candles)
    macd_val,macd_sig_val,macd_hist,prev_hist,prev_macd_val = calc_macd(candles)
    rsi                                      = calc_rsi(candles)
    rsi_prev                                 = calc_rsi(candles[:-1]) if len(candles)>25 else rsi


    # === Stochastic (2-candle: current + prev only) ===
    stoch_k, stoch_d                         = calc_stochastic(candles)
    stoch_k_prev, stoch_d_prev               = calc_stochastic(candles[:-1]) if len(candles)>25 else (stoch_k, stoch_d)

    stoch_diff       = round((stoch_k - stoch_d), 2) if (stoch_k is not None and stoch_d is not None) else 0
    stoch_diff_prev  = round((stoch_k_prev - stoch_d_prev), 2) if (stoch_k_prev is not None and stoch_d_prev is not None) else 0
    stoch_total_delta = round(stoch_diff - stoch_diff_prev, 2)  # v11.5: current - prev (no prev2)

    # === MACD (2-candle) ===
    macd_val, macd_sig_val, macd_hist, prev_hist, prev_macd_val = calc_macd(candles)
    _, _, prev1_hist, _, _                                      = calc_macd(candles[:-1]) if len(candles)>25 else (None, None, macd_hist, None, None)

    macd_diff       = macd_hist if macd_hist is not None else 0
    macd_diff_prev  = prev1_hist if prev1_hist is not None else 0
    macd_total_delta = round(macd_diff - macd_diff_prev, 5)  # v11.5: current - prev (no prev2)

    # === CCI (2-candle: current + prev only) ===
    cci_val       = calc_cci(candles)
    cci_prev_val  = calc_cci(candles[:-1]) if len(candles) > 21 else cci_val

    cc_lookback = 15
    green,red,doji,cc_total,green_ratio,red_ratio,candle_dom=calc_candle_count(candles,cc_lookback)

    if adx is None or macd_hist is None or rsi is None:
        return None,0,"FAIL — Indicator calc error",{}

    current_trend = "neutral"
    decision = None
    strategy_used = ""
    conf = 0
    reason = ""

    if rsi_prev is None or stoch_k is None or stoch_d is None or macd_val is None or macd_sig_val is None:
        return None, 0, "FAIL — Missing Indicator Data", {}

    _regime = detect_market_regime(candles)
    _dyn = calc_dynamic_entry_thresholds(atr_pct)
    support_count = 0

    # ── SUPER ADAPTIVE EARLY BLOCKS ──
    if adaptive:
        if name in adaptive.get("micro_blacklist", []):
            return None, 0, f"Skipped — Adaptive Block ({name} 2x Loss)", {}
        if _regime in adaptive.get("block_regimes", []):
            return None, 0, f"Skipped — Adaptive Regime Block ({_regime})", {}

    # ── Market Noise Filter (Last 15 Candles) ──
    sub_c = candles[-15:] if len(candles) >= 15 else candles
    avg_body = sum(abs(c["close"] - c["open"]) for c in sub_c) / len(sub_c)
    max_body = max(abs(c["close"] - c["open"]) for c in sub_c)
    total_wick = sum((c["high"] - max(c["open"], c["close"])) + (min(c["open"], c["close"]) - c["low"]) for c in sub_c)
    total_body = sum(abs(c["close"] - c["open"]) for c in sub_c)

    too_big = max_body > (avg_body * 2.5) if avg_body > 0 else False
    too_much_wick = (total_body == 0) or (total_wick > total_body * 1.2)

    if too_big or too_much_wick:
        reason_str = "Huge Candle Spike" if too_big else "Too Much Wick Activity"
        return None, 0, f"Skipped — Market Noise ({reason_str})", {}

    # ── Dynamic ADX ──
    _adx_floor = adaptive.get("adx_floor", 15.0) if adaptive else 15.0
    atr_norm = min(max(atr_pct if atr_pct else 0.1, 0.05), 0.25)
    dynamic_adx_min = max(_adx_floor, 12 + ((atr_norm - 0.05) / 0.20) * 10)
    dynamic_adx_strong = 25 + ((atr_norm - 0.05) / 0.20) * 15

    if adx >= dynamic_adx_min:
        # ── Exhaustion Filters ──
        call_exhausted = (stoch_k >= 85) or (rsi >= 75)
        put_exhausted  = (stoch_k <= 15) or (rsi <= 25)

        last_candle = candles[-1]

        # ── Volatility Zone ──
        flat_market = atr_pct < 0.05
        wild_market = atr_pct > 0.35
        if flat_market or wild_market:
            return None, 0, f"Skipped — Market Volatility ({'Flat' if flat_market else 'Wild'})", {}

        # ── ATR-Scaled Thresholds ──
        _rsi_delta_req = _dyn["rsi_min_delta"]
        _cci_bull_req  = _dyn["cci_bull"]
        _cci_bear_req  = _dyn["cci_bear"]

        # ── Adaptive Overrides ──
        _rsi_delta_mult = adaptive.get("rsi_min_delta_mult", 1.0) if adaptive else 1.0
        _cci_min_delta = adaptive.get("cci_min_delta", 15) if adaptive else 15
        # ── v11.5 OVERRIDE: ALL 4 indicators mandatory (RSI+CCI+MACD+STOCH) ──
        _min_support = 2  # MACD + STOCH both required, always

        _rsi_delta_req = _rsi_delta_req * _rsi_delta_mult

        # ══════════════════════════════════════════════
        # v11.5 RSI Slope — 2-candle (prev + current)
        # ══════════════════════════════════════════════
        rsi_total_delta = (rsi - rsi_prev) if (rsi is not None and rsi_prev is not None) else 0
        rsi_call = (rsi is not None and rsi_prev is not None
                    and rsi > rsi_prev
                    and abs(rsi_total_delta) >= _rsi_delta_req)
        rsi_put  = (rsi is not None and rsi_prev is not None
                    and rsi < rsi_prev
                    and abs(rsi_total_delta) >= _rsi_delta_req)
        rsi_delta = rsi_total_delta

        _macd_delta_req  = 0.00003 * _dyn.get("atr_scale", 1.0)

        # ── MACD (Supporting - 1 Bar Direction - Histogram Delta) ──
        macd_call = (macd_diff is not None and macd_diff_prev is not None
                     and macd_diff > macd_diff_prev
                     and abs(macd_total_delta) >= _macd_delta_req)
        macd_put  = (macd_diff is not None and macd_diff_prev is not None
                     and macd_diff < macd_diff_prev
                     and abs(macd_total_delta) >= _macd_delta_req)

        # ── Stoch (Supporting - 1 Bar Direction) ──
        stoch_call = (stoch_k is not None and stoch_k_prev is not None
                      and stoch_k > stoch_k_prev)
        stoch_put  = (stoch_k is not None and stoch_k_prev is not None
                      and stoch_k < stoch_k_prev)

        # ══════════════════════════════════════════════
        # v11.5 CCI Slope — 2-candle (prev + current)
        # ══════════════════════════════════════════════
        cci_total_delta = (cci_val - cci_prev_val) if (cci_val is not None and cci_prev_val is not None) else 0
        cci_call = (cci_val is not None and cci_prev_val is not None
                    and cci_val > cci_prev_val
                    and abs(cci_total_delta) >= _cci_min_delta
                    and cci_val > _cci_bull_req)
        cci_put  = (cci_val is not None and cci_prev_val is not None
                    and cci_val < cci_prev_val
                    and abs(cci_total_delta) >= _cci_min_delta
                    and cci_val < _cci_bear_req)

        # ── CCI Extreme Exhaustion ──
        cci_exhausted_call = (cci_val is not None and cci_val > 200)
        cci_exhausted_put  = (cci_val is not None and cci_val < -200)

        # ── Big Spike Block ──
        if abs(rsi_total_delta) > 20 or abs(cci_total_delta) > 120:
            return None, 0, f"Skipped — Abnormal Spike (RSI Δ:{rsi_total_delta:.1f}, CCI Δ:{cci_total_delta:.1f})", {}

        # ── Current Candle Direction ──
        current_is_green = last_candle["close"] > last_candle["open"]
        current_is_red   = last_candle["close"] < last_candle["open"]
        candle_call = current_is_green
        candle_put  = current_is_red

        # ══════════════════════════════════════════════
        # CALL: RSI↑ + CCI↑ (mandatory) + (MACD or/and Stoch) + green candle
        # ══════════════════════════════════════════════
        if (not call_exhausted and not cci_exhausted_call
                and rsi_call and cci_call and candle_call):
            support_count = sum([macd_call, stoch_call])
            if support_count >= _min_support:
                decision = "call"
                strategy_used = "REMASTERED_SYNC"
                conf = 95 if support_count == 2 else 80
                conf_parts = []
                if macd_call:  conf_parts.append("MACD")
                if stoch_call: conf_parts.append("STOCH")
                shot_label = "SURE SHOT" if support_count == 2 else "CONFIRMED"
                regime_tag = f" [{_regime}]" if _regime != "TRENDING" else ""
                reason = f"🔥 {shot_label}! RSI↑({rsi_delta:+.1f})+CCI↑ + {'+'.join(conf_parts)}↑{regime_tag} -> CALL"

        # ══════════════════════════════════════════════
        # PUT: RSI↓ + CCI↓ (mandatory) + (MACD or/and Stoch) + red candle
        # ══════════════════════════════════════════════
        if (decision is None and not put_exhausted and not cci_exhausted_put
                and rsi_put and cci_put and candle_put):
            support_count = sum([macd_put, stoch_put])
            if support_count >= _min_support:
                decision = "put"
                strategy_used = "REMASTERED_SYNC"
                conf = 95 if support_count == 2 else 80
                conf_parts = []
                if macd_put:  conf_parts.append("MACD")
                if stoch_put: conf_parts.append("STOCH")
                shot_label = "SURE SHOT" if support_count == 2 else "CONFIRMED"
                regime_tag = f" [{_regime}]" if _regime != "TRENDING" else ""
                reason = f"🔥 {shot_label}! RSI↓({rsi_delta:+.1f})+CCI↓ + {'+'.join(conf_parts)}↓{regime_tag} -> PUT"

    if decision is None:
        return None, 0, f"Skipped — Strategy not met (ADX:{adx:.1f})", {}

    # ══════════════════════════════════════════════
    # HTF NULL BLOCK
    # Data: HTF null = 41% win rate — skip trade
    if htf_dir is None:
        return None, 0, "Skipped — HTF direction unclear (null)", {}

    # HTF ALIGNMENT BOOST
    # ══════════════════════════════════════════════
    _htf_min = adaptive.get("htf_min_adx", 18.0) if adaptive else 18.0
    if htf_dir:
        htf_is_strong = (htf_adx is not None and htf_adx >= _htf_min)
        if htf_dir == decision and htf_is_strong:
            if adaptive and adaptive.get("htf_penalty"):
                reason = reason.replace("SURE SHOT", "SURE SHOT [HTF Penalty]").replace("CONFIRMED", "CONFIRMED [HTF Penalty]")
            else:
                conf = min(conf + 5, 99)
                reason = reason.replace("SURE SHOT", "SUPER SURE SHOT (HTF✓)").replace("CONFIRMED", "CONFIRMED (HTF✓)")
        elif htf_dir != decision and adx >= 20:
            return None, 0, f"Skipped — Opposing HTF Trend (ADX > 20)", {}

    # ── SUPER ADAPTIVE DIRECTION BLOCK ──
    if adaptive and decision in adaptive.get("block_direction", []):
        return None, 0, f"Skipped — Adaptive Direction Block ({decision.upper()})", {}

    # ── DEEP PATTERN BLOCKS ──
    if adaptive:
        # 1. No Man's Land
        middle_zone = adaptive.get("avoid_middle_zone")
        if middle_zone:
            if abs(rsi - middle_zone["rsi_center"]) <= 5 and abs(cci_val - middle_zone["cci_center"]) <= 15:
                return None, 0, "FAIL — Blocked by Adaptive Pattern (Weak Momentum / No Man's Land)", {}

        # 2. Overextended
        if adaptive.get("avoid_overextended"):
            if (decision == "put" and cci_val < -30) or (decision == "call" and cci_val > 30):
                return None, 0, "FAIL — Blocked by Adaptive Pattern (Already Overextended / Late Entry)", {}

        # 3. Support Mandatory
        if adaptive.get("macd_mandatory"):
            macd_agreed = macd_call if decision == "call" else macd_put
            if not macd_agreed:
                return None, 0, "FAIL — Blocked by Adaptive Pattern (Single Support failing, MACD mandatory)", {}

        # 4. Conf 99 Pair Blacklist
        if conf >= 99 and name in adaptive.get("conf_99_blacklist", []):
            return None, 0, f"FAIL — Blocked by Adaptive Pattern (Conf 99 is failing on {name})", {}

        # 5. Stoch Overextended Block
        if adaptive.get("block_stoch_overextended"):
            is_stoch_overextended = (
                (stoch_k is not None and stoch_k_prev is not None)
                and (
                    (decision == "put"  and stoch_k < 20 and stoch_diff < -18)
                    or (decision == "call" and stoch_k > 80 and stoch_diff > 18)
                )
            )
            if is_stoch_overextended:
                return None, 0, "FAIL — Blocked by Adaptive Pattern (Stoch Overextended / Already exhausted)", {}

    is_sure_shot = True

    meta={
        "adx":adx,"pdi":pdi,"ndi":ndi,"strong_trend":(adx>=45),
        "macd_hist":macd_hist,"macd_fresh":False,"prev_hist":prev_hist,
        "macd_val":macd_val,"prev_macd_val":prev_macd_val,"macd_sig_val":macd_sig_val,
        "macd_diff": macd_diff, "macd_diff_prev": macd_diff_prev, "macd_total_delta": macd_total_delta,
        "rsi":rsi,"rsi_prev":rsi_prev,
        "stoch_k":stoch_k,"stoch_d":stoch_d,"stoch_k_prev":stoch_k_prev,
        "stoch_d_prev": stoch_d_prev,
        "stoch_diff": stoch_diff, "stoch_diff_prev": stoch_diff_prev, "stoch_total_delta": stoch_total_delta,
        "cci":cci_val,"cci_prev":cci_prev_val,
        "rsi_total_delta": round(rsi_total_delta, 2),
        "cci_total_delta": round(cci_total_delta, 2),
        "macd_agreed": macd_call if decision == "call" else macd_put if decision == "put" else False,
        "stoch_agreed": stoch_call if decision == "call" else stoch_put if decision == "put" else False,
        "atr_pct":atr_pct,
        "candle_green":green,"candle_red":red,"candle_doji":doji,
        "candle_total":cc_total,"green_ratio":green_ratio,"red_ratio":red_ratio,
        "higher_trend":"UPTREND" if current_trend=="call" else "DOWNTREND",
        "trend_strength":round(adx,2),
        "htf_trend":htf_dir,"htf_adx":htf_adx,"htf_ema":htf_ema,
        "strategy": strategy_used,
        "sure_shot": is_sure_shot,
        "regime": _regime,
        "support_count": support_count,
        "atr_scale": _dyn.get("atr_scale", 1.0),
    }

    # ══════════════════════════════════════════════
    # v11.5: _grad() updated — 2-point check only
    # ══════════════════════════════════════════════
    def _grad(v_prev, v_cur):
        if v_prev is None or v_cur is None: return "N/A"
        if v_cur > v_prev: return "Increasing"
        if v_cur < v_prev: return "Decreasing"
        return "Flat"

    meta["rsi_gradual"]   = _grad(rsi_prev, rsi)
    meta["cci_gradual"]   = _grad(cci_prev_val, cci_val)
    meta["stoch_gradual"] = _grad(stoch_diff_prev, stoch_diff)
    meta["macd_gradual"]  = _grad(macd_diff_prev, macd_diff)

    return decision, conf, reason, meta

# ══════════════════════════════════════════════
# ASSET STATS / TRADE LOG
# ══════════════════════════════════════════════
def update_stats(asset,result):
    d={}
    if os.path.exists(ASSET_STATS_FILE):
        with open(ASSET_STATS_FILE) as f: d=json.load(f)
    if asset not in d: d[asset]={"w":0,"l":0,"t":0}
    d[asset]["t"]+=1
    if result=="WIN": d[asset]["w"]+=1
    else:             d[asset]["l"]+=1
    with open(ASSET_STATS_FILE,"w") as f: json.dump(d,f,indent=2)

def is_blacklisted(asset):
    if not os.path.exists(ASSET_STATS_FILE): return False,""
    with open(ASSET_STATS_FILE) as f: d=json.load(f)
    if asset not in d: return False,""
    s=d[asset]
    if s["t"]<ASSET_MIN_TRADES: return False,""
    wr=s["w"]/s["t"]*100
    if wr<ASSET_MIN_WINRATE:
        return True,f"WR:{wr:.0f}%({s['t']}tr)"
    return False,""

def save_trade(entry):
    d={"sessions":[]}
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE) as f: d=json.load(f)
    today=datetime.now().strftime("%Y-%m-%d")
    for day in d["sessions"]:
        if day["date"]==today:
            day["trades"].append(entry); break
    else:
        d["sessions"].append({"date":today,"trades":[entry]})
    with open(TRADES_FILE,"w") as f: json.dump(d,f,indent=2)
    update_stats(entry["asset"],entry["result"])

# ══════════════════════════════════════════════
# SERVER TIME
# ══════════════════════════════════════════════
async def get_epoch(client):
    try:
        import calendar
        st=await client.get_server_time()
        if isinstance(st,(int,float)): return int(st)
        if isinstance(st,str):
            for fmt in ("%Y-%m-%d %H:%M:%S","%Y-%m-%dT%H:%M:%S"):
                try: return calendar.timegm(datetime.strptime(st,fmt).timetuple())
                except: pass
    except: pass
    return int(datetime.now().timestamp())

async def secs_until_close(client,dur):
    ep=await get_epoch(client)
    rem=dur-(ep%dur)
    if rem<=1: rem+=dur
    return rem

# ══════════════════════════════════════════════
# ASSET FETCH
# ══════════════════════════════════════════════
async def get_eligible(client, tf_label, min_payout=85):
    try:
        pk="5M" if tf_label=="5 min" else "1M"
        pay=client.get_payment(); out=[]
        for code,name in client.get_all_asset_name():
            if name not in pay: continue
            d=pay[name]
            if not d.get("open"): continue
            payout=d.get("profit",{}).get(pk,0)
            if payout>=min_payout: out.append((name,code,payout))
        out=sorted(out,key=lambda x:x[2],reverse=True)
        return out
    except Exception as e:
        return []

async def fetch_candles(client, name, code, payout, dur, count):
    for attempt in range(2):
        try:
            c = await asyncio.wait_for(
                client.get_candles(code, 0, count, dur), timeout=3.5
            )
            if c and len(c) >= 40:
                if not is_valid(c):
                    return None
                return {"asset_display": name, "asset_code": code, "payout": payout, "candles": c}
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            pass
        if attempt < 1:
            await asyncio.sleep(0.2)
    return None

async def fetch_htf_candles(client, code, htf_dur):
    # v11.6: 3 attempts, 15s timeout, min candles relaxed to 28
    min_candles = max(ADX_PERIOD * 2, 28)
    for attempt in range(3):
        try:
            c = await asyncio.wait_for(
                client.get_candles(code, 0, HTF_CANDLES, htf_dur), timeout=15.0
            )
            if c and len(c) >= min_candles:
                if is_valid(c):
                    return c
        except asyncio.TimeoutError:
            pass
        except:
            pass
        if attempt < 2:
            await asyncio.sleep(0.3 * (attempt + 1))
    return None


# ══════════════════════════════════════════════
# BOT ENGINE CLASS
# ══════════════════════════════════════════════
class BotEngine:
    """Wraps the trading bot logic with event callbacks for WebSocket streaming."""

    def __init__(self):
        self.client = None
        self.running = False
        self.config = {}
        self.session = []
        self.pnl = 0.0
        self.amount = 0
        self.mg_step = 0
        self.consec_loss = 0
        self.api_failures = 0
        self.balance = 0.0
        self.profile = None
        self._event_callback = None
        self._stop_event = asyncio.Event()
        self.asset_cooldown = {}
        self.htf_cache = {}
        self.regime_history = {}
        self.adaptive = {}

    def set_event_callback(self, callback):
        self._event_callback = callback

    async def emit(self, event_type, data=None):
        if self._event_callback:
            try:
                await self._event_callback(event_type, data or {})
            except Exception:
                pass

    async def connect(self):
        await self.emit("log", {"msg": "Connecting to Quotex..."})
        self.client = Quotex(email=EMAIL, password=PASSWORD)
        ok, msg = await self.client.connect()
        if not ok:
            await self.emit("error", {"msg": f"Connection failed: {msg}"})
            return False
        await self.emit("log", {"msg": "Connected successfully!"})
        return True

    async def start(self, config):
        self.config = config
        self.running = True
        self._stop_event.clear()
        self.session = []
        self.pnl = 0.0
        self.consec_loss = 0
        self.mg_step = 0
        self.api_failures = 0
        account = config["account"]
        ACCOUNT_TYPE = "PRACTICE" if account == "Demo" else "REAL"
        SYM = "₹"
        tf = config["timeframe"]
        ENTRY_DUR = get_tf_seconds(tf)
        BASE = config["amount"]
        SL = config["stop_loss"]
        TP = config["take_profit"]
        USE_MARTINGALE = config.get("martingale", False)
        USE_ADAPTIVE = config.get("adaptive_learning", False)
        self.min_payout = config.get("min_payout", 85)

        # ── Adaptive Learning ──
        if USE_ADAPTIVE:
            self.adaptive = learn_adaptive_thresholds()
            if self.adaptive.get("learned"):
                await self.emit("log", {"msg": f"🧠 ADAPTIVE v11.5 — Learned from recent trades"})
                _rsi_mul = self.adaptive.get('rsi_min_delta_mult', 1.0)
                _cci_del = self.adaptive.get('cci_min_delta', 15)
                _req_both = self.adaptive.get('require_both_support', False)
                _sup_str = "BOTH (MACD+STOCH)" if _req_both else "MACD|STOCH (1 of 2)"
                await self.emit("log", {"msg": f"   ADX Floor: {self.adaptive.get('adx_floor', 15.0):.0f} | HTF Min: {self.adaptive.get('htf_min_adx', 15.0):.0f}"})
                await self.emit("log", {"msg": f"   RSI Δ Mult: {_rsi_mul:.1f}x | CCI Δ: ≥{_cci_del}"})

                _wm = self.adaptive.get('macd_only_wr')
                _ws = self.adaptive.get('stoch_only_wr')
                _wb = self.adaptive.get('both_support_wr')
                wr_parts = []
                if _wm is not None: wr_parts.append(f"MACD:{_wm:.0f}%")
                if _ws is not None: wr_parts.append(f"STOCH:{_ws:.0f}%")
                if _wb is not None: wr_parts.append(f"Both:{_wb:.0f}%")
                wr_info = " | ".join(wr_parts) if wr_parts else "No Support WR Data"

                await self.emit("log", {"msg": f"   Support Req: {_sup_str} | WR[{wr_info}]"})
                await self.emit("log", {"msg": f"   [v11.5] 2-Candle Logic: prev+current only (prev2 removed)"})
            else:
                await self.emit("log", {"msg": "🧠 ADAPTIVE ON — Not enough history, using safe defaults"})
                await self.emit("log", {"msg": "   [v11.5] 2-Candle Logic: prev+current only (prev2 removed)"})
        else:
            self.adaptive = {}
            await self.emit("log", {"msg": "🧠 ADAPTIVE OFF — Using fixed default thresholds"})
            await self.emit("log", {"msg": "   [v11.5] 2-Candle Logic: prev+current only (prev2 removed)"})

        self.amount = BASE

        if not await self.connect():
            self.running = False
            return

        self.client.set_account_mode(ACCOUNT_TYPE)
        self.profile = await self.client.get_profile()
        self.balance = get_balance(self.profile, ACCOUNT_TYPE)

        htf_dur = get_htf_seconds(ENTRY_DUR)

        await self.emit("connected", {
            "name": self.profile.nick_name,
            "account": account,
            "balance": round(self.balance, 2),
            "timeframe": tf,
            "htf": f"{htf_dur//60}min",
            "amount": BASE,
            "stop_loss": SL,
            "take_profit": TP,
            "martingale": USE_MARTINGALE,
        })

        await self.emit("status_update", {
            "balance": round(self.balance, 2),
            "pnl": 0.0,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "amount": BASE,
            "mg_step": 0,
            "running": True,
        })

        while self.running and not self._stop_event.is_set():
            try:
                if self.pnl <= -abs(SL):
                    await self.emit("bot_stopped", {"reason": "stop_loss", "pnl": round(self.pnl, 2)})
                    break
                if self.pnl >= abs(TP):
                    await self.emit("bot_stopped", {"reason": "take_profit", "pnl": round(self.pnl, 2)})
                    break

                if self.consec_loss >= CONSEC_LOSS_LIMIT:
                    await self.emit("log", {"msg": f"⚠ {self.consec_loss} losses — cooling 1 candle"})
                    self.consec_loss = 0
                    rem = await secs_until_close(self.client, ENTRY_DUR)
                    for r in range(rem, 0, -1):
                        if self._stop_event.is_set(): break
                        await self.emit("countdown", {"seconds": r, "label": "Cooldown"})
                        await asyncio.sleep(1)
                    continue

                rem = await secs_until_close(self.client, ENTRY_DUR)
                await self.emit("log", {"msg": f"[{now_str()}] Next candle in {rem}s"})

                if USE_MARTINGALE and self.mg_step > 0:
                    await self.emit("log", {
                        "msg": f"Martingale Step {self.mg_step}/{MARTINGALE_MAX_STEPS} — Amount: {SYM}{self.amount}"
                    })

                eligible = await get_eligible(self.client, tf, self.min_payout)
                if not eligible:
                    await self.emit("log", {"msg": "No eligible assets found"})
                    rem = await secs_until_close(self.client, ENTRY_DUR)
                    for r in range(rem, 0, -1):
                        if self._stop_event.is_set(): break
                        await self.emit("countdown", {"seconds": r, "label": "Waiting"})
                        await asyncio.sleep(1)
                    continue

                await self.emit("log", {"msg": f"Eligible assets: {len(eligible)}"})

                rem = await secs_until_close(self.client, ENTRY_DUR)
                for r in range(rem, 0, -1):
                    if self._stop_event.is_set(): break
                    await self.emit("countdown", {"seconds": r, "label": "Candle closes"})
                    await asyncio.sleep(1)

                if self._stop_event.is_set(): break

                await asyncio.sleep(1)

                if self._stop_event.is_set(): break

                await self.emit("log", {"msg": f"[{now_str()}] CANDLE CLOSED ✓"})

                t_close = datetime.now()

                await self.emit("scan_start", {"total": len(eligible)})

                result, elapsed = await self._fetch_and_analyze(
                    eligible, ENTRY_DUR, tf, htf_dur
                )

                if result == "RECONNECT":
                    await self.emit("log", {"msg": "🔄 Fetch failed for all assets. Reconnecting API..."})
                    try:
                        await self.client.close()
                    except: pass
                    await asyncio.sleep(2)
                    if await self.connect():
                        acc_str = self.config.get("account", "Demo")
                        self.client.set_account_mode("PRACTICE" if acc_str == "Demo" else "REAL")
                    continue

                if result is None:
                    await self.emit("log", {"msg": "No signal — next candle"})
                    continue

                elapsed = (datetime.now() - t_close).total_seconds()
                if elapsed > TRADE_ENTRY_LIMIT:
                    await self.emit("log", {"msg": f"⚠ Too late! {elapsed:.1f}s"})
                    continue

                best = result
                entry_time = now_full()
                dl = "CALL ▲" if best["signal"] == "call" else "PUT ▼"

                await self.emit("signal_found", {
                    "asset": best["asset_display"],
                    "signal": best["signal"],
                    "direction_label": dl,
                    "confidence": best["confidence"],
                    "payout": best["payout"],
                    "adx": best["adx"],
                    "pdi": best["pdi"],
                    "ndi": best["ndi"],
                    "macd_hist": best["macd_hist"],
                    "macd_fresh": best["macd_fresh"],
                    "rsi": best["rsi"],
                    "cci": best.get("cci"),
                    "stoch_k": best.get("stoch_k"),
                    "stoch_d": best.get("stoch_d"),
                    "strong_trend": best.get("strong_trend", False),
                    "higher_trend": best["higher_trend"],
                    "htf_trend": best.get("htf_trend"),
                    "htf_adx": best.get("htf_adx"),
                    "pattern": best.get("pattern", "NONE"),
                    "divergence": best.get("divergence"),
                    "momentum": best.get("momentum"),
                    "trend_consistency": best.get("trend_consistency"),
                    "candle_green": best["candle_green"],
                    "candle_red": best["candle_red"],
                    "candle_doji": best["candle_doji"],
                    "candle_total": best["candle_total"],
                    "green_ratio": best["green_ratio"],
                    "red_ratio": best["red_ratio"],
                    "sr_support": best.get("sr_support"),
                    "sr_resist": best.get("sr_resist"),
                    "reason": best["reason"],
                    "amount": self.amount,
                    "mg_step": self.mg_step,
                    "entry_time": entry_time,
                    "elapsed": round(elapsed, 1),
                })

                trade_amount = self.amount

                await self.emit("trade_entry", {
                    "asset": best["asset_display"],
                    "signal": best["signal"],
                    "amount": trade_amount,
                    "confidence": best["confidence"],
                })

                status, trade_info = await self.client.buy(
                    trade_amount, best["asset_code"], best["signal"], ENTRY_DUR
                )
                if not status:
                    self.api_failures += 1
                    err_msg = str(trade_info) if trade_info else "Unknown API Error"
                    await self.emit("error", {"msg": f"Trade failed! Reason: {err_msg} (Failures: {self.api_failures})"})
                    if self.api_failures >= 3:
                        await self.emit("log", {"msg": "🔄 Max failures reached. Auto-reconnecting API..."})
                        await asyncio.sleep(2)
                        if await self.connect():
                            acc_str = self.config.get("account", "Demo")
                            self.client.set_account_mode("PRACTICE" if acc_str == "Demo" else "REAL")
                        self.api_failures = 0
                    continue
                else:
                    self.api_failures = 0

                trade_id = (
                    trade_info.get("id") or trade_info.get("requestId")
                    if isinstance(trade_info, dict) else trade_info
                )
                if not trade_id:
                    await self.emit("error", {"msg": "No trade ID!"})
                    continue

                fe = (datetime.now() - t_close).total_seconds()
                await self.emit("log", {"msg": f"✔ Entered at +{fe:.1f}s"})

                for r in range(ENTRY_DUR + 2, 0, -1):
                    if self._stop_event.is_set(): break
                    await self.emit("countdown", {"seconds": r, "label": "Result"})
                    await asyncio.sleep(1)

                result_amount = None
                for retry in range(3):
                    try:
                        result_amount = await self.client.check_win(trade_id)
                        break
                    except Exception as e:
                        if retry < 2:
                            await self.emit("log", {"msg": f"⚠ check_win retry {retry+1}: {e}"})
                            await asyncio.sleep(2)

                if result_amount is None:
                    await self.emit("log", {"msg": "⚠ Could not determine trade result"})
                    continue

                is_win = result_amount > 0
                profit = round(trade_amount * best["payout"] / 100, 2) if is_win else -trade_amount
                self.pnl += profit
                current_mg_step = self.mg_step

                trade_candle_color = None
                trade_result_type = None

                try:
                    target_epoch = (int(t_close.timestamp()) // ENTRY_DUR) * ENTRY_DUR
                    c_data = await asyncio.wait_for(
                        self.client.get_candles(best["asset_code"], 0, 4, ENTRY_DUR), timeout=5.0
                    )
                    tc = None
                    if c_data:
                        for c in c_data:
                            if c.get("time") == target_epoch:
                                tc = c
                                break
                        if not tc and len(c_data) >= 1:
                            tc = c_data[-2] if len(c_data) >= 2 else c_data[-1]

                    if tc:
                        if tc["close"] > tc["open"]: trade_candle_color = "GREEN"
                        elif tc["close"] < tc["open"]: trade_candle_color = "RED"
                        else: trade_candle_color = "DOJI"

                        if best["signal"] == "call":
                            if trade_candle_color == "GREEN":
                                trade_result_type = "NORMAL_WIN" if is_win else "LATE_ENTRY_LOSS"
                            elif trade_candle_color == "RED":
                                trade_result_type = "LUCKY_WIN" if is_win else "WRONG_ANALYSIS"
                            else:
                                trade_result_type = "DOJI_WIN" if is_win else "DOJI_LOSS"
                        elif best["signal"] == "put":
                            if trade_candle_color == "RED":
                                trade_result_type = "NORMAL_WIN" if is_win else "LATE_ENTRY_LOSS"
                            elif trade_candle_color == "GREEN":
                                trade_result_type = "LUCKY_WIN" if is_win else "WRONG_ANALYSIS"
                            else:
                                trade_result_type = "DOJI_WIN" if is_win else "DOJI_LOSS"
                except Exception as e:
                    pass

                if is_win:
                    self.consec_loss = 0
                    reason_log = f" [{trade_result_type}]" if trade_result_type else ""
                    await self.emit("log", {"msg": f"✔ {best['asset_display']}{reason_log} — Won {SYM}{profit}"})
                    if USE_MARTINGALE and self.mg_step > 0:
                        await self.emit("log", {"msg": f"Martingale RESET → base {SYM}{BASE}"})
                    self.mg_step = 0
                    self.amount = BASE
                else:
                    self.consec_loss += 1
                    lost_asset = best["asset_display"]
                    cooldown_until = time.time() + 300
                    self.asset_cooldown[lost_asset] = cooldown_until
                    reason_log = f" [{trade_result_type}]" if trade_result_type else ""
                    await self.emit("log", {"msg": f"🚫 {lost_asset}{reason_log} — cooldown 5min"})
                    if USE_MARTINGALE:
                        if self.mg_step < MARTINGALE_MAX_STEPS:
                            self.mg_step += 1
                            self.amount = calc_martingale_amount(BASE, self.mg_step)
                            await self.emit("log", {
                                "msg": f"Martingale Step {self.mg_step} → next: {SYM}{self.amount}"
                            })
                        else:
                            self.mg_step = 0
                            self.amount = BASE
                            await self.emit("log", {"msg": "Martingale MAX (2) — resetting to base"})

                self.profile = await self.client.get_profile()
                self.balance = get_balance(self.profile, ACCOUNT_TYPE)

                wins = sum(1 for t in self.session if t["result"] == "WIN") + (1 if is_win else 0)
                total_trades = len(self.session) + 1
                wr = wins / total_trades * 100

                await self.emit("trade_result", {
                    "result": "WIN" if is_win else "LOSS",
                    "profit": round(profit, 2),
                    "pnl": round(self.pnl, 2),
                    "balance": round(self.balance, 2),
                    "asset": best["asset_display"],
                    "signal": best["signal"],
                    "confidence": best["confidence"],
                    "payout": best["payout"],
                    "amount": trade_amount,
                    "mg_step": current_mg_step,
                    "trade_no": total_trades,
                    "entry_time": entry_time,
                    "adx": best["adx"],
                    "rsi": best["rsi"],
                    "pattern": best.get("pattern"),
                })

                await self.emit("status_update", {
                    "balance": round(self.balance, 2),
                    "pnl": round(self.pnl, 2),
                    "trades": total_trades,
                    "wins": wins,
                    "losses": total_trades - wins,
                    "win_rate": round(wr, 1),
                    "amount": self.amount,
                    "mg_step": self.mg_step,
                    "running": True,
                })

                # ── Diagnostic Tags ──
                _sig = best["signal"].lower()
                _sk = best.get("stoch_k")
                _htf = best.get("htf_trend")
                _diag = []
                if _htf and _htf != _sig:
                    _diag.append("htf_opposing")
                elif _htf and _htf == _sig:
                    _diag.append("htf_aligned")
                if _sk is not None:
                    if (_sig == "call" and _sk > 75) or (_sig == "put" and _sk < 25):
                        _diag.append("stoch_overextended")
                _rsi_d = abs(best.get("rsi", 0) - best.get("rsi_prev", 0))
                _stoch_d = abs(best.get("stoch_k", 0) - best.get("stoch_k_prev", 0))
                if _rsi_d > 8 or _stoch_d > 40:
                    _diag.append("big_move_entry")

                save_trade({
                    "trade_no": total_trades, "entry_time": entry_time,
                    "asset": best["asset_display"], "account": account,
                    "entry_tf": tf, "direction": best["signal"].upper(),
                    "trend": best["higher_trend"], "strong_trend": best.get("strong_trend"),
                    "adx": best["adx"], "pdi": best["pdi"], "ndi": best["ndi"],
                    "macd_hist": best.get("macd_hist"), "macd_fresh": best.get("macd_fresh"),
                    "macd_val": best.get("macd_val"), "prev_macd_val": best.get("prev_macd_val"),
                    "macd_diff": best.get("macd_diff"), "macd_diff_prev": best.get("macd_diff_prev"), "macd_total_delta": best.get("macd_total_delta"),
                    "rsi": best.get("rsi"), "rsi_prev": best.get("rsi_prev"),
                    "stoch_k": best.get("stoch_k"), "stoch_k_prev": best.get("stoch_k_prev"), "stoch_d": best.get("stoch_d"),
                    "stoch_d_prev": best.get("stoch_d_prev"),
                    "stoch_diff": best.get("stoch_diff"), "stoch_diff_prev": best.get("stoch_diff_prev"), "stoch_total_delta": best.get("stoch_total_delta"),
                    "cci": best.get("cci"), "cci_prev": best.get("cci_prev"),
                    "rsi_total_delta": best.get("rsi_total_delta"),
                    "cci_total_delta": best.get("cci_total_delta"),
                    "rsi_gradual": best.get("rsi_gradual"),
                    "cci_gradual": best.get("cci_gradual"),
                    "stoch_gradual": best.get("stoch_gradual"),
                    "macd_gradual": best.get("macd_gradual"),
                    "rsi_log_str": best.get("rsi_disp"),
                    "cci_log_str": best.get("cci_disp"),
                    "stoch_log_str": best.get("stoch_disp"),
                    "macd_log_str": best.get("macd_disp"),
                    "macd_agreed": best.get("macd_agreed"),
                    "stoch_agreed": best.get("stoch_agreed"),
                    "candle_green": best.get("candle_green"), "candle_red": best.get("candle_red"),
                    "candle_doji": best.get("candle_doji"),
                    "green_ratio": best.get("green_ratio"), "red_ratio": best.get("red_ratio"),
                    "atr_pct": best.get("atr_pct"), "confidence": best.get("confidence"),
                    "reason": best.get("reason"), "payout_pct": best.get("payout"),
                    "amount": trade_amount, "profit": round(profit, 2),
                    "result": "WIN" if is_win else "LOSS",
                    "balance": round(self.balance, 2), "pnl": round(self.pnl, 2),
                    "mg_step": current_mg_step, "mg_active": USE_MARTINGALE,
                    "htf_trend": best.get("htf_trend"),
                    "htf_adx": best.get("htf_adx"),
                    "divergence": best.get("divergence"),
                    "pattern": best.get("pattern"),
                    "momentum": best.get("momentum"),
                    "trend_consistency": best.get("trend_consistency"),
                    "strategy": best.get("strategy"),
                    "regime": best.get("regime"),
                    "support_count": best.get("support_count"),
                    "atr_scale": best.get("atr_scale"),
                    "diagnosis": _diag,
                    "trade_result_type": trade_result_type
                })

                # ── Adaptive Re-Learn (only if enabled) ──
                if USE_ADAPTIVE:
                    old_adaptive = self.adaptive.copy()
                    self.adaptive = learn_adaptive_thresholds()
                    if self.adaptive.get("learned"):
                        changes = []
                        if old_adaptive.get("adx_floor") != self.adaptive.get("adx_floor"):
                            changes.append(f"ADX:{self.adaptive['adx_floor']:.0f}")
                        if old_adaptive.get("htf_min_adx") != self.adaptive.get("htf_min_adx"):
                            changes.append(f"HTF:{self.adaptive['htf_min_adx']:.0f}")
                        if old_adaptive.get("rsi_min_delta_mult") != self.adaptive.get("rsi_min_delta_mult"):
                            changes.append(f"RSI_Δx{self.adaptive['rsi_min_delta_mult']:.1f}")
                        if old_adaptive.get("cci_min_delta") != self.adaptive.get("cci_min_delta"):
                            changes.append(f"CCI_Δ≥{self.adaptive['cci_min_delta']}")
                        if old_adaptive.get("require_both_support") != self.adaptive.get("require_both_support"):
                            mode = "MACD+STOCH" if self.adaptive["require_both_support"] else "MACD|STOCH"
                            changes.append(f"Support:{mode}")
                        wr_parts = []
                        _wm = self.adaptive.get("macd_only_wr")
                        _ws = self.adaptive.get("stoch_only_wr")
                        _wb = self.adaptive.get("both_support_wr")
                        if _wm is not None: wr_parts.append(f"MACD:{_wm:.0f}%")
                        if _ws is not None: wr_parts.append(f"STOCH:{_ws:.0f}%")
                        if _wb is not None: wr_parts.append(f"BOTH:{_wb:.0f}%")
                        if wr_parts:
                            changes.append(f"WR[{' | '.join(wr_parts)}]")
                        
                        if old_adaptive.get("block_regimes") != self.adaptive.get("block_regimes"):
                            changes.append(f"BlockedRegimes:{self.adaptive.get('block_regimes', [])}")
                        if old_adaptive.get("block_direction") != self.adaptive.get("block_direction"):
                            changes.append(f"BlockedDirs:{self.adaptive.get('block_direction', [])}")
                        if old_adaptive.get("block_stoch_overextended") != self.adaptive.get("block_stoch_overextended"):
                            changes.append(f"StochOverextended:{self.adaptive.get('block_stoch_overextended', False)}")
                        if old_adaptive.get("micro_blacklist") != self.adaptive.get("micro_blacklist"):
                            changes.append(f"BlacklistedPairs:{len(self.adaptive.get('micro_blacklist', []))}")
                        if old_adaptive.get("htf_penalty") != self.adaptive.get("htf_penalty"):
                            changes.append(f"HTF_Penalty:{self.adaptive.get('htf_penalty')}")

                        if changes:
                            await self.emit("log", {"msg": f"🧠 ADAPTIVE UPDATE — {' | '.join(changes)}"})

                self.session.append({
                    "result": "WIN" if is_win else "LOSS",
                    "profit": profit,
                    "asset": best["asset_display"],
                    "confidence": best["confidence"],
                })

            except Exception as e:
                await self.emit("error", {"msg": f"Error: {e}"})
                await asyncio.sleep(5)

        self.running = False
        wins = sum(1 for t in self.session if t["result"] == "WIN")
        total_trades = len(self.session)
        wr = wins / total_trades * 100 if total_trades else 0

        await self.emit("status_update", {
            "balance": round(self.balance, 2),
            "pnl": round(self.pnl, 2),
            "trades": total_trades,
            "wins": wins,
            "losses": total_trades - wins,
            "win_rate": round(wr, 1),
            "amount": self.amount,
            "mg_step": self.mg_step,
            "running": False,
        })

        await self.emit("bot_stopped", {
            "reason": "manual",
            "pnl": round(self.pnl, 2),
        })

        try:
            await self.client.close()
        except:
            pass

    async def stop(self):
        self.running = False
        self._stop_event.set()
        await self.emit("log", {"msg": "⛔ Bot stopping..."})

    async def _fetch_and_analyze(self, eligible, entry_dur, tf_label, htf_dur):
        t0 = datetime.now()
        total = len(eligible)
        htf_label = f"{htf_dur//60}min"

        await self.emit("log",
            {"msg": f"[{now_str()}] SCANNING v11.6 — TF:{tf_label} HTF:{htf_label} (PDI/NDI Primary, RSI Optional)"}
        )

        done = 0
        sem = asyncio.Semaphore(3)

        async def fetch_one(name, code, payout):
            nonlocal done
            async with sem:
                await asyncio.sleep(0.05)
                entry = await fetch_candles(self.client, name, code, payout, entry_dur, ENTRY_CANDLES)
                htf_c = None
                if entry:
                    now_ts = time.time()
                    cache = self.htf_cache.get(name)
                    # v11.6: cache expiry = htf_dur * 0.75 (refresh more often, less stale)
                    cache_expired = not cache or (now_ts - cache["time"]) >= (htf_dur * 0.75)
                    if cache_expired:
                        htf_c = await fetch_htf_candles(self.client, code, htf_dur)
                        if htf_c:
                            self.htf_cache[name] = {"candles": htf_c, "time": now_ts}
                        else:
                            await self.emit("log", {"msg": f"⚠️ HTF fetch failed for {name} — trade will proceed without HTF confirmation"})
                    else:
                        htf_c = cache["candles"]
                    entry["htf_candles"] = htf_c
                done += 1
                await self.emit("scan_progress", {"done": done, "total": total})
                return entry

        results = await asyncio.gather(*[fetch_one(n, c, p) for n, c, p in eligible])
        assets = [a for a in results if a][:MAX_SCAN_ASSETS]

        if not assets and total > 0:
            elapsed = (datetime.now() - t0).total_seconds()
            await self.emit("error", {"msg": f"⚠️ All {total} assets failed to load (took {elapsed:.1f}s). Connection dropped."})
            return "RECONNECT", elapsed

        await self.emit("log", {"msg": f"Analyzing {len(assets)} assets..."})

        signals = []
        for a in assets:
            name = a["asset_display"]; candles = a["candles"]
            htf_c = a.get("htf_candles")
            bl, bl_r = is_blacklisted(name)
            if bl:
                await self.emit("asset_update", {"asset": name, "status": "blacklisted", "reason": bl_r})
                continue

            if name in self.asset_cooldown:
                if time.time() < self.asset_cooldown[name]:
                    remain = int(self.asset_cooldown[name] - time.time())
                    await self.emit("asset_update", {"asset": name, "status": "blacklisted", "reason": f"Cooldown {remain}s"})
                    continue
                else:
                    del self.asset_cooldown[name]

            current_regime = detect_market_regime(candles)
            reg_hist = self.regime_history.get(name, [])
            if len(reg_hist) >= 2 and reg_hist[-1] == "RANGING" and reg_hist[-2] == "RANGING" and current_regime == "BREAKOUT":
                await self.emit("log", {"msg": f"⚡ Regime Transition: RANGING → BREAKOUT on {name}"})
            reg_hist.append(current_regime)
            self.regime_history[name] = reg_hist[-10:]

            adx_v,_,_     = calc_adx(candles)
            rsi_v         = calc_rsi(candles)

            stoch_kv,_    = calc_stochastic(candles)
            strong = (adx_v is not None and adx_v >= ADX_STRONG)

            htf_d, htf_a, _ = htf_trend_check(htf_c) if htf_c else (None, None, None)

            decision, conf, reason, meta = decide(candles, name, entry_dur, htf_c, adaptive=self.adaptive)

            await self.emit("asset_update", {
                "asset": name,
                "adx": adx_v,
                "rsi": rsi_v,

                "stoch_k": stoch_kv,
                "cci": calc_cci(candles),
                "strong": strong,
                "htf_trend": htf_d,
                "decision": decision,
                "confidence": conf if decision else 0,
                "reason": reason,
                "status": "signal" if decision else "rejected",
            })

            if decision is None:
                continue

            rsi_dir  = "⬆️" if meta["rsi"] > meta["rsi_prev"] else ("⬇️" if meta["rsi"] < meta["rsi_prev"] else "▬")
            stk_dir  = "🟢" if meta["stoch_k"] > meta["stoch_d"] else ("🔴" if meta["stoch_k"] < meta["stoch_d"] else "▬")
            macd_dir = "🟢" if meta["macd_val"] > meta["macd_sig_val"] else ("🔴" if meta["macd_val"] < meta["macd_sig_val"] else "▬")
            cci_dir  = "🟢" if (meta.get("cci") is not None and meta.get("cci_prev") is not None and meta["cci"] > meta["cci_prev"]) else "🔴"

            # ── v11.5: 2 timestamps only (prev + current) ──
            t2 = datetime.fromtimestamp(candles[-2]["time"]).strftime("%H:%M:%S") if len(candles) >= 2 else ""
            t3 = datetime.fromtimestamp(candles[-1]["time"]).strftime("%H:%M:%S") if len(candles) >= 1 else ""

            rsi_grad   = f"({meta.get('rsi_gradual', 'N/A')})"
            cci_grad   = f"({meta.get('cci_gradual', 'N/A')})"
            stoch_grad = f"({meta.get('stoch_gradual', 'N/A')})"
            macd_grad  = f"({meta.get('macd_gradual', 'N/A')})"

            # ── v11.5: 2-point history display ──
            rsi_history   = f"{t2}: {meta.get('rsi_prev', 0):.1f} ➔ {t3}: {meta.get('rsi', 0):.1f}"
            cci_history   = f"{t2}: {meta.get('cci_prev', 0):.1f} ➔ {t3}: {meta.get('cci', 0):.1f}"
            stoch_history = f"{t2}: {meta.get('stoch_diff_prev', 0):.1f} ➔ {t3}: {meta.get('stoch_diff', 0):.1f}"
            macd_history  = f"{t2}: {meta.get('macd_diff_prev', 0):+.5f} ➔ {t3}: {meta.get('macd_diff', 0):+.5f}"

            rsi_disp   = f"RSI: [{rsi_history}] {rsi_grad} Δ{meta.get('rsi_total_delta', 0):+.1f}{rsi_dir}"
            cci_disp   = f"CCI: [{cci_history}] {cci_grad} Δ{meta.get('cci_total_delta', 0):+.1f}{cci_dir}"
            stoch_disp = f"Stoch(Diff): [{stoch_history}] {stoch_grad} Δ{meta.get('stoch_total_delta', 0):+.1f}{stk_dir}"
            macd_disp  = f"MACD(Hist): [{macd_history}] {macd_grad} Δ{meta.get('macd_total_delta', 0):+.5f}{macd_dir}"

            meta["rsi_disp"]   = rsi_disp
            meta["cci_disp"]   = cci_disp
            meta["stoch_disp"] = stoch_disp
            meta["macd_disp"]  = macd_disp

            ind_log = (
                f"📊 {name} {decision.upper()} | "
                f"ADX:{meta['adx']:.1f} | "
                f"{rsi_disp} | "
                f"{cci_disp} | "
                f"{macd_disp} | "
                f"{stoch_disp}"
            )
            await self.emit("log", {"msg": ind_log})

            signals.append({
                "asset_display": name, "asset_code": a["asset_code"],
                "payout": a["payout"], "signal": decision,
                "confidence": conf, "reason": reason, **meta,
            })

        elapsed = (datetime.now() - t0).total_seconds()
        await self.emit("log", {
            "msg": f"Scan: {elapsed:.1f}s — Signals: {len(signals)}/{len(assets)}"
        })

        if not signals:
            return None, elapsed

        best = max(signals, key=lambda x: (x["confidence"], x["payout"]))
        return best, elapsed