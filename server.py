"""EcoWatt AI web server. Run: uvicorn server:app --reload"""
import logging, math, os, time
from datetime import datetime
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import core
from config import GEMINI_API_KEY, GRID_KG_PER_KWH as EF

HERE = os.path.dirname(__file__)
app = FastAPI(title="EcoWatt AI")
logger = logging.getLogger(__name__)
core.init_db()
_c = {"t": 0, "df": None}


def data():
    if time.time() - _c["t"] > 30:
        _c["df"], _c["t"] = core.load_readings(), time.time()
    return _c["df"]


def clean(o):
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, datetime): return o.strftime("%Y-%m-%d")
    if isinstance(o, (float, np.floating)): return round(float(o), 3) if math.isfinite(o) else None
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.bool_): return bool(o)
    return o


def ctx():
    df = data()
    last = df.date.max()
    cur = df[df.date.dt.to_period("M") == last.to_period("M")]
    return df, last, cur, cur.kwh.sum() / last.day * last.days_in_month, core.appliance_stats(df)


@app.get("/api/overview")
def overview():
    df, last, cur, proj, st = ctx()
    fl = st[st.status.isin(["abnormal", "high"])].sort_values("extra_month_rm", ascending=False)
    t30 = df[df.date > last - pd.Timedelta(days=30)].groupby(["date", "appliance"]).kwh.sum().unstack().fillna(0)
    return clean(dict(
        month=last.strftime("%B %Y"), day=last.day, days=last.days_in_month,
        kwh=cur.kwh.sum(), bill=core.bill(cur.kwh.sum()), proj_kwh=proj, proj_bill=core.bill(proj),
        savings=fl.extra_month_rm.sum(), simulated=bool((df.source == "simulated").all()),
        by_appliance=cur.groupby("appliance").kwh.sum().to_dict(),
        trend=dict(dates=list(t30.index), series={c: list(t30[c]) for c in t30}),
        alerts=[dict(appliance=r.appliance, status=r.status, why=r.why, rec=core.RECS[r.appliance], rm=r.extra_month_rm) for r in fl.itertuples()]))


@app.get("/api/months")
def months():
    return sorted(df_m for df_m in data().date.dt.strftime("%Y-%m").unique())[::-1]


@app.get("/api/monthly")
def monthly(month: str):
    df, last, *_ = ctx()
    d = df[df.date.dt.strftime("%Y-%m") == month]
    if d.empty:
        raise HTTPException(404, "No data for that month")
    daily = d.groupby(["date", "appliance"]).kwh.sum().unstack().fillna(0)
    dd = daily.sum(axis=1)
    hm = d.groupby(["hour", "date"]).kwh.sum().unstack().fillna(0)
    tot = d.kwh.sum()
    return clean(dict(
        total=tot, bill=core.bill(tot), avg=dd.mean(), peak_day=dd.idxmax(), peak_kwh=dd.max(),
        top=d.groupby("appliance").kwh.sum().idxmax(), partial=month == last.strftime("%Y-%m"), days_recorded=len(dd),
        dates=list(daily.index), series={c: list(daily[c]) for c in daily}, cum_rm=[core.bill(k) for k in dd.cumsum()],
        heat=dict(x=list(hm.columns), y=list(hm.index), z=hm.values.tolist()),
        breakdown=core.tier_rows(tot).to_dict("records"),
        table=[dict(date=i, **{c: round(r[c], 2) for c in daily.columns}, total=round(r.sum(), 2)) for i, r in daily.iterrows()]))


@app.get("/api/appliances")
def appliances():
    df, last, cur, proj, st = ctx()
    out = []
    for name, w, room in core.APPLIANCES.values():
        a, r = df[df.appliance == name], st[st.appliance == name].iloc[0]
        d = a.groupby("date").kwh.sum().tail(30)
        out.append(dict(name=name, room=room, rated_w=w, power_w=a.sort_values("ts").power_w.iloc[-1],
                        month_kwh=cur[cur.appliance == name].kwh.sum(), status=r.status, baseline=r.baseline, recent=r.recent,
                        pct=r.pct, why=r.why, rec=core.RECS[name], extra_rm=r.extra_month_rm, dates=list(d.index), kwh=list(d.values)))
    return clean(out)


class Act(BaseModel):
    appliance: str
    note: str


@app.post("/api/actions")
def add_action(a: Act):
    if a.appliance not in [v[0] for v in core.APPLIANCES.values()] or not a.note.strip():
        raise HTTPException(400, "Invalid action")
    core.add_action(a.appliance, a.note.strip()[:200])
    return {"ok": True}


@app.get("/api/actions")
def actions():
    df, acts, out = data(), core.load_actions(), []
    for x in acts.itertuples():
        b, a, n = core.review_action(df, x.appliance, x.ts)
        out.append(dict(ts=x.ts, appliance=x.appliance, note=x.note, before=b, after=a, days_after=n))
    return clean(out)


class Q(BaseModel):
    question: str


@app.post("/api/chat")
def chat(q: Q):
    df = data()
    if not GEMINI_API_KEY:
        ans = core.fallback_answer(df, None, q.question)
        ans += "\n\n_Gemini key is not set; showing rule-based advice instead._"
    else:
        try:
            ans = core.ask_gemini(q.question[:1000], core.build_context(df), GEMINI_API_KEY)
        except Exception:
            logger.exception("Gemini chat request failed; using rule-based fallback")
            ans = core.fallback_answer(df, None, q.question)
            ans += "\n\n_Gemini request failed; showing rule-based advice instead. Check the Uvicorn terminal for the error._"
    return {"answer": ans}


@app.get("/api/simulate")
def simulate(hours: float = 1, setpoint: int = 1, heater: int = 20):
    df, last, cur, proj, st = ctx()
    day = lambda n: df[df.appliance == n].groupby("date").kwh.sum().iloc[-8:-1].mean()
    ac, wh = day("Air conditioner"), day("Water heater")
    hrs = df[(df.appliance == "Air conditioner") & (df.kwh > 0.05)].groupby("date").size().iloc[-8:-1].mean()
    per = ac / max(hrs, 1)
    raw = [("Fewer AC hours", hours * per * 30), ("Higher AC setpoint", max(0, ac - hours * per) * 0.06 * setpoint * 30),
           ("Shorter water heating", wh * heater / 100 * 30)]
    total = sum(k for _, k in raw)
    return clean(dict(items=[dict(action=a, kwh=k, rm=core.saving_rm(proj, k)) for a, k in raw], total_kwh=total,
                      total_rm=core.saving_rm(proj, total), bill_now=core.bill(proj), bill_after=core.bill(proj - total)))


@app.get("/api/sustainability")
def sustainability():
    df, last, cur, proj, st = ctx()
    prev = df[df.date.dt.to_period("M") == last.to_period("M") - 1].kwh.sum() * EF
    kg = proj * EF
    fl = st[st.status.isin(["abnormal", "high"])].sort_values("extra_month_kwh", ascending=False)
    mon = df.groupby(df.date.dt.strftime("%Y-%m")).kwh.sum() * EF
    return clean(dict(kg=kg, prev=prev, change=(kg / prev - 1) if prev else None, km=kg / 0.17, trees=kg / 21, ef=EF,
                      wins=[dict(appliance=r.appliance, rec=core.RECS[r.appliance], rm=r.extra_month_rm, kg=r.extra_month_kwh * EF) for r in fl.itertuples()],
                      months=list(mon.index), month_kg=list(mon.values)))


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))
