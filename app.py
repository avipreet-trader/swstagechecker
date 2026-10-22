"""Weinstein Stage Checker — Yahoo Finance edition.

Run locally:   streamlit run app.py
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots

from stages import MIN_WEEKS, NAMES, analyse, evaluate, to_weekly

try:
    from streamlit_searchbox import st_searchbox
except Exception:  # component missing: fall back to text box + list
    st_searchbox = None

st.set_page_config(page_title="Weinstein Stage Checker", layout="wide")

BENCH = ("^NSEI", "Nifty 50")
SUFFIX = {"NSE": ".NS", "BSE": ".BO"}
STAGE_COLORS = {1: "#5d7396", 2: "#2c9a65", 3: "#d08a14", 4: "#c8473d"}
UP, DOWN, MA_COLOR = "#2c9a65", "#c8473d", "#3b6fd4"

st.markdown(
    """
<style>
.block-container{padding-top:1.6rem;padding-bottom:1rem}
.stage-pill{display:inline-block;padding:4px 14px;border-radius:999px;color:#fff;font-weight:700;font-size:1.15rem}
.ticker{font-family:ui-monospace,Menlo,monospace;font-weight:600;font-size:1.05rem}
.muted{opacity:.7;font-size:.85rem}
.lvl{display:inline-block;font-family:ui-monospace,Menlo,monospace;font-size:.82rem;border:1px dashed rgba(128,128,128,.5);border-radius:6px;padding:2px 8px;margin:2px 4px 2px 0}
.chk{display:grid;grid-template-columns:22px 1fr;gap:8px;margin:6px 0;align-items:start}
.mk{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;font-size:.72rem;font-weight:700;color:#fff}
.chk small{display:block;opacity:.7;font-family:ui-monospace,Menlo,monospace}
.keycard{border:1px solid rgba(128,128,128,.3);border-top:4px solid var(--k);border-radius:8px;padding:10px 12px;height:100%}
.keycard h4{margin:0 0 6px 0;font-size:1rem}
.keycard p{margin:0 0 6px 0;font-size:.86rem}
.keycard b.k{color:var(--k)}
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- data
@st.cache_data(ttl=24 * 3600, show_spinner=False)
def yahoo_search(term: str, exchange: str) -> list[tuple[str, str]]:
    """Return [(label, yahoo_symbol)] for equities on the chosen exchange."""
    term = term.strip()
    if len(term) < 2:
        return []
    quotes: list[dict] = []
    try:
        quotes = yf.Search(term, max_results=25, news_count=0).quotes
    except Exception:
        try:
            r = requests.get(
                "https://query2.finance.yahoo.com/v1/finance/search",
                params={"q": term, "quotesCount": 25, "newsCount": 0},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=8,
            )
            quotes = r.json().get("quotes", [])
        except Exception:
            quotes = []
    sfx = SUFFIX[exchange]
    out, seen = [], set()
    for q in quotes:
        sym = q.get("symbol", "")
        if not sym.endswith(sfx) or q.get("quoteType") not in (None, "EQUITY") or sym in seen:
            continue
        seen.add(sym)
        name = q.get("shortname") or q.get("longname") or ""
        out.append((f"{sym[: -len(sfx)]} · {name}", sym))
    typed = term.upper().replace(" ", "") + sfx
    if typed not in seen and term.replace(" ", "").isalnum():
        out.append((f"{typed[: -len(sfx)]} · use this symbol as typed", typed))
    return out


@st.cache_data(ttl=15 * 60, show_spinner=False)
def daily_history(symbol: str, years: int) -> pd.DataFrame:
    df = yf.Ticker(symbol).history(period=f"{years}y", interval="1d", auto_adjust=False)
    if df is None or df.empty:
        return pd.DataFrame()
    return df[["Open", "High", "Low", "Close", "Volume"]]


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def company_name(symbol: str) -> str:
    try:
        info = yf.Ticker(symbol).get_info()
        return info.get("longName") or info.get("shortName") or ""
    except Exception:
        return ""


# ---------------------------------------------------------------- chart
def build_chart(a, title: str) -> go.Figure:
    w = a.w
    x = w.index
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.66, 0.14, 0.20])

    # stage bands
    half = pd.Timedelta(days=3.5)
    start = 0
    for i in range(1, len(w) + 1):
        if i == len(w) or a.stage[i] != a.stage[start]:
            s = a.stage[start]
            if s:
                fig.add_vrect(x0=x[start] - half, x1=x[i - 1] + half, fillcolor=STAGE_COLORS[s],
                              opacity=0.13, line_width=0, layer="below", row=1, col=1)
                if i - start >= 4:
                    fig.add_annotation(x=x[start] + (x[i - 1] - x[start]) / 2, y=1, yref="y domain",
                                       text=f"<b>S{s}</b>", showarrow=False,
                                       font=dict(color=STAGE_COLORS[s], size=12), yanchor="top",
                                       row=1, col=1)
            start = i

    hover = [
        f"Stage {s} · {NAMES[s]}" if s else "MA not formed yet" for s in a.stage
    ]
    fig.add_trace(go.Candlestick(
        x=x, open=w["Open"], high=w["High"], low=w["Low"], close=w["Close"], name="Weekly",
        increasing=dict(line=dict(color=UP), fillcolor="rgba(0,0,0,0)"),
        decreasing=dict(line=dict(color=DOWN), fillcolor=DOWN),
        text=hover, hoverinfo="x+y+text",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=a.ma, name="30-week MA", line=dict(color=MA_COLOR, width=2),
                             hovertemplate="30w MA %{y:,.2f}<extra></extra>"), row=1, col=1)

    # breakout / breakdown markers
    for e in a.events:
        if e.to not in (2, 4):
            continue
        up = e.to == 2
        y = float(w["Low"].iloc[e.i]) * 0.97 if up else float(w["High"].iloc[e.i]) * 1.03
        label = ("Breakout" + (f" {e.vol_ratio:.1f}× vol" if e.vol_ratio else "")) if up else "Breakdown"
        fig.add_trace(go.Scatter(
            x=[x[e.i]], y=[y], mode="markers+text", text=[label],
            textposition="bottom center" if up else "top center",
            marker=dict(symbol="triangle-up" if up else "triangle-down", size=12, color=STAGE_COLORS[e.to]),
            textfont=dict(color=STAGE_COLORS[e.to], size=11), showlegend=False, hoverinfo="skip",
        ), row=1, col=1)
        if e.level is not None and np.isfinite(e.level):
            x0 = x[max(0, e.i - 12)]
            x1 = x[min(len(x) - 1, e.i + 3)]
            fig.add_shape(type="line", x0=x0, x1=x1, y0=e.level, y1=e.level,
                          line=dict(color=STAGE_COLORS[e.to], width=1, dash="dash"), row=1, col=1)

    vol_colors = [UP if c >= o else DOWN for o, c in zip(w["Open"], w["Close"])]
    vol_opacity = [0.95 if (vr == vr and vr >= 2) else 0.45 for vr in a.vr]
    fig.add_trace(go.Bar(x=x, y=w["Volume"], marker=dict(color=vol_colors, opacity=vol_opacity),
                         name="Volume", hovertemplate="Vol %{y:,.0f}<extra></extra>", showlegend=False),
                  row=2, col=1)

    fig.add_trace(go.Scatter(x=x, y=a.mrs, name=f"Mansfield RS vs {BENCH[1]}", line=dict(color="#7b5cc4", width=1.6),
                             fill="tozeroy", fillcolor="rgba(123,92,196,0.12)",
                             hovertemplate="RS %{y:.1f}<extra></extra>", showlegend=False), row=3, col=1)
    fig.add_hline(y=0, line=dict(color="gray", width=1, dash="dot"), row=3, col=1)

    fig.update_layout(
        height=640, margin=dict(l=8, r=8, t=30, b=8), hovermode="x unified",
        xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.04, x=0, yanchor="bottom"),
        title=dict(text=title, x=0, font=dict(size=13)),
    )
    fig.update_yaxes(side="right", row=1, col=1)
    fig.update_yaxes(side="right", title_text="Vol", title_font=dict(size=10), row=2, col=1)
    fig.update_yaxes(side="right", title_text="RS", title_font=dict(size=10), row=3, col=1)
    return fig


# ---------------------------------------------------------------- UI
st.markdown("## Weinstein Stage Checker")
st.caption("Weekly candles · 30-week moving average · Mansfield relative strength vs Nifty 50 · "
           "free data from Yahoo Finance (may be delayed)")

qp = st.query_params
default_ex = "BSE" if qp.get("s", "").endswith(".BO") else "NSE"

c1, c2, c3 = st.columns([1.1, 4, 1.6])
with c1:
    exchange = st.radio("Exchange", ["NSE", "BSE"], horizontal=True,
                        index=["NSE", "BSE"].index(default_ex), key="exchange")
with c3:
    years = st.radio("History", [2, 3, 5], index=1, horizontal=True, format_func=lambda y: f"{y}Y", key="years")
with c2:
    picked = None
    if st_searchbox is not None:
        picked = st_searchbox(
            lambda term: yahoo_search(term or "", exchange),
            placeholder="Type a symbol or company name, e.g. leela or TARIL",
            key=f"search_{exchange}",
        )
    else:
        term = st.text_input("Stock", placeholder="Type a symbol or company name and press Enter")
        opts = yahoo_search(term, exchange) if term else []
        if opts:
            labels = [o[0] for o in opts]
            choice = st.selectbox("Matches", labels, key="match")
            picked = dict(opts)[choice]
        elif term:
            st.info("No matches. Try part of the company name.")

symbol = picked or qp.get("s") or "THELEELA.NS"
if not symbol.endswith((".NS", ".BO")):
    symbol = symbol.upper() + SUFFIX[exchange]
if picked:
    st.query_params["s"] = symbol

with st.spinner(f"Loading {symbol}…"):
    try:
        daily = daily_history(symbol, years)
        bench = daily_history(BENCH[0], years)
    except Exception as exc:  # network / rate limit
        st.error(f"Yahoo Finance didn't return data ({type(exc).__name__}). "
                 "It sometimes throttles requests; wait a minute and press R to rerun.")
        st.stop()

if daily.empty:
    st.warning(f"No price history found for **{symbol}**. Check the symbol, or try the other exchange.")
    st.stop()

w = to_weekly(daily)
bw = to_weekly(bench) if not bench.empty else None
a = analyse(w, bw)
name = company_name(symbol)

left, right = st.columns([1, 2.6], gap="medium")

with right:
    st.plotly_chart(build_chart(a, f"{symbol}  {name}"), config={"displaylogo": False})
    if a.events:
        st.caption("Stage changes: " + " · ".join(
            f"{e.date:%d %b %y} {e.frm}→{e.to} @ ₹{e.close:,.2f}" + (f" ({e.vol_ratio:.1f}× vol)" if e.to == 2 and e.vol_ratio else "")
            for e in a.events[-6:]))

with left:
    if len(w) < MIN_WEEKS:
        st.warning(f"{symbol} has only {len(w)} weeks of history. A Weinstein reading needs at least "
                   f"{MIN_WEEKS} weeks (30 for the moving average plus 4 to judge its slope).")
    else:
        r = evaluate(a)
        s = r["stage"]
        st.markdown(
            f'<span class="stage-pill" style="background:{STAGE_COLORS[s]}">Stage {s} · {NAMES[s]}</span>'
            f'<div class="ticker" style="margin-top:8px">{symbol}</div>'
            f'<div class="muted">{name} · week ending {r["date"]:%d %b %Y}</div>',
            unsafe_allow_html=True,
        )
        slope_word = "rising" if r["slope"] > 1.5 else "falling" if r["slope"] < -1.5 else "flat"
        text = {
            1: f"Basing. The 30-week MA is {slope_word} and price is moving sideways around it. Weinstein waits for a weekly close above the top of the base on strong volume.",
            2: f"Advancing. Price is above a {slope_word} 30-week MA. This is the only stage Weinstein buys in; best entries are the breakout and the first pullback toward it.",
            3: "Topping. The Stage 2 advance has stalled and price is chopping around or below the MA. Weinstein stops buying, and holders tighten stops.",
            4: f"Declining. Price is below a {slope_word} 30-week MA. Weinstein never buys or holds in Stage 4.",
        }[s]
        st.write(f"{text} In Stage {s} for {r['weeks_in']} week{'s' if r['weeks_in'] > 1 else ''}.")

        m1, m2 = st.columns(2)
        m1.metric("Last close", f"₹{r['close']:,.2f}")
        m2.metric("30-week MA", f"₹{r['ma']:,.2f}")
        m1.metric("Price vs MA", f"{r['dist']:+.1f}%")
        m2.metric("MA slope (4 wk)", f"{r['slope']:+.2f}%")
        m1.metric("Mansfield RS", "–" if r["mrs"] is None else f"{r['mrs']:.1f}")
        m2.metric("52-week range", f"₹{r['lo52']:,.0f}–{r['hi52']:,.0f}")

        if r["levels"]:
            st.markdown("".join(f'<span class="lvl"><b>{k}</b> ₹{v:,.2f}</span>' for k, v in r["levels"]),
                        unsafe_allow_html=True)

        st.markdown(f"**Stage 2 checklist · {r['passed']}/{r['total']}**")
        rows = []
        for label, ok, detail in r["checks"]:
            color = "#9aa3a0" if ok is None else STAGE_COLORS[2] if ok else STAGE_COLORS[4]
            mark = "–" if ok is None else "✓" if ok else "✕"
            rows.append(f'<div class="chk"><span class="mk" style="background:{color}">{mark}</span>'
                        f'<div>{label}<small>{detail}</small></div></div>')
        st.markdown("".join(rows), unsafe_allow_html=True)

# ---------------------------------------------------------------- stage key
st.markdown("#### Stage key")
KEY = [
    (1, "Basing", "After a long fall, price stops making new lows and moves sideways.",
     "Stops falling and flattens; price crosses back and forth over it.",
     "Dries up, then picks up near the top of the range.",
     "Don't buy yet. Watch for the breakout."),
    (2, "Advancing", "Breaks out above the base, then makes higher highs and higher lows.",
     "Turns up and keeps rising. Pullbacks hold above it.",
     "Breakout week at least 2× normal; heavier on up-weeks.",
     "The only stage to buy: the breakout or the first pullback. Trail a stop below the MA."),
    (3, "Topping", "The advance stalls; swings widen and price stops making progress.",
     "Loses its upslope and flattens; price slips below and back.",
     "Big volume on down days: sellers are distributing.",
     "No new buying. Take partial profits and tighten stops."),
    (4, "Declining", "Breaks below the Stage 3 range; lower highs and lower lows.",
     "Turns down; rallies fail at or below it.",
     "Breakdowns don't need high volume; bounces come on light volume.",
     "Never buy or hold. Don't bottom-fish."),
]
cols = st.columns(4)
for col, (n, nm, looks, ma_txt, vol, act) in zip(cols, KEY):
    col.markdown(
        f'<div class="keycard" style="--k:{STAGE_COLORS[n]}"><h4>{n} · {nm}</h4>'
        f"<p><b>Looks like:</b> {looks}</p><p><b>30-week MA:</b> {ma_txt}</p>"
        f'<p><b>Volume:</b> {vol}</p><p><b class="k">Weinstein:</b> {act}</p></div>',
        unsafe_allow_html=True,
    )

with st.expander("How stages are marked"):
    st.markdown(
        """
1. **Weekly bars and a 30-week simple moving average.** MA slope is its % change over 4 weeks; within ±1.5% counts as flat.
2. **Stage 2:** close above a rising MA. Entry from Stage 1 needs a weekly close above the top of the base with the MA no longer falling.
3. **Stage 3:** after Stage 2, 3+ closes below the MA in the last 10 weeks, or a close below a falling 10-week MA while 25%+ off the Stage 2 high.
4. **Stage 4:** close below a falling MA, or below the bottom of the Stage 3 range.
5. **Stage 1:** after Stage 4, the MA flattens with price closing above it, or 3+ closes above it in 10 weeks.
6. **Mansfield RS:** stock/Nifty 50 ratio vs its own 52-week average. Above zero = beating the market.

These rules approximate how Weinstein reads a chart; borderline weeks can flip. Data comes from Yahoo Finance and is
unofficial and may be delayed. This is a charting aid, not investment advice.
"""
    )

st.caption(f"Tip: share a stock directly by copying this page's address after picking it (it ends in ?s={symbol}).")
