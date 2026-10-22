"""Friendly-features API: eco score, budget, challenges, recap, bill explainer, scheduler, compare, devices."""
from datetime import datetime
import numpy as np
import pandas as pd
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel
import core, config

EXPLAIN = {
    "Electricity (generation, capacity, network)": "The cost of making the power and delivering it to your home.",
    "Fuel adjustment (AFA)": "A monthly adjustment for fuel prices. It changes every month and is not charged at or below 600 kWh.",
    "Retail charge": "A flat RM10 a month to cover billing and customer service. Waived at or below 600 kWh.",
    "Renewable energy fund (1.6%)": "A small levy that funds renewable energy. Not charged at or below 300 kWh.",
    "Service tax (8%)": "Tax on the part of your usage above 600 kWh only.",
}


def _budget():
    with core.conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)")
        r = c.execute("SELECT v FROM settings WHERE k='budget'").fetchone()
    return float(r[0]) if r else 150.0


def _kwh_for(rm):
    lo, hi = 0.0, 3000.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if core.bill(mid) < rm else (lo, mid)
    return lo


def _score(df, last, proj, st, budget):
    pace = core.bill(proj) / budget
    b = max(0, min(100, 100 - (pace - .8) * 250))
    a = max(0, 100 - 40 * int((st.status == "abnormal").sum()) - 15 * int((st.status == "high").sum()))
    prev = df[df.date.dt.to_period("M") == last.to_period("M") - 1].kwh.sum()
    t = 100 if not prev else max(0, min(100, 100 - (proj / prev - .9) * 250))
    s = round(.5 * b + .3 * a + .2 * t)
    return s, "A" if s >= 85 else "B" if s >= 70 else "C" if s >= 55 else "D" if s >= 40 else "E", \
        "happy" if s >= 70 else "ok" if s >= 45 else "worried", dict(budget=round(b), alerts=round(a), trend=round(t)), pace, prev


class Budget(BaseModel):
    budget: float


class Bill(BaseModel):
    kwh: float
    amount: float


class Reading(BaseModel):
    appliance: str
    kwh: float
    ts: str | None = None


def register(app, data, ctx, clean, invalidate, require_resident):
    _budget()

    @app.get("/api/home", dependencies=[Depends(require_resident)])
    def home():
        df, last, cur, proj, st = ctx()
        bud = _budget()
        s, g, mood, parts, pace, prev = _score(df, last, proj, st, bud)
        rate = core.bill(proj) / proj
        ac = st[st.appliance == "Air conditioner"].iloc[0]
        y = df[df.date == last - pd.Timedelta(days=1)].kwh.sum()
        h = datetime.now().hour
        head = {"happy": "Your home is on track this month. Nice work.", "ok": "You're doing okay, with room to improve.",
                "worried": "Your usage needs attention. A few small changes will help."}[mood]
        return clean(dict(greet="Good morning" if h < 12 else "Good afternoon" if h < 18 else "Good evening", score=s, grade=g, mood=mood,
                          parts=parts, headline=head, budget=bud, bill=core.bill(cur.kwh.sum()), proj_bill=core.bill(proj), pace=pace,
                          yesterday_rm=y * rate, ac_day_rm=ac.recent * rate, teh=ac.recent * rate / 3))

    @app.get("/api/budget", dependencies=[Depends(require_resident)])
    def budget():
        df, last, cur, proj, st = ctx()
        bud, spent = _budget(), core.bill(cur.kwh.sum())
        left = last.days_in_month - last.day
        allow = max(0, _kwh_for(bud) - cur.kwh.sum())
        pace = core.bill(proj) / bud
        msg = (f"At this pace you'll finish about RM {core.bill(proj) - bud:.0f} over budget." if pace > 1
               else f"You're on track to finish about RM {bud - core.bill(proj):.0f} under budget.")
        return clean(dict(budget=bud, spent=spent, proj_bill=core.bill(proj), left=left, msg=msg, pace=pace,
                          daily_kwh=allow / left if left else 0, allow_kwh=allow))

    @app.post("/api/budget", dependencies=[Depends(require_resident)])
    def set_budget(b: Budget):
        if not 20 <= b.budget <= 5000:
            raise HTTPException(400, "Budget must be between RM 20 and RM 5000")
        with core.conn() as c:
            c.execute("INSERT OR REPLACE INTO settings VALUES('budget',?)", (str(b.budget),))
        return {"ok": True}

    @app.get("/api/challenges", dependencies=[Depends(require_resident)])
    def challenges():
        df, last, cur, proj, st = ctx()
        bud = _budget()
        s, g, mood, parts, pace, prev = _score(df, last, proj, st, bud)
        target = _kwh_for(bud) / last.days_in_month
        d = df[df.date < last].groupby("date").kwh.sum()
        ok = d <= target
        streak = 0
        for v in ok.iloc[::-1]:
            if not v: break
            streak += 1
        good, acts = int(ok.tail(7).sum()), len(core.load_actions())
        ac = st[st.appliance == "Air conditioner"].iloc[0]
        bad = int(st.status.isin(["abnormal", "high"]).sum())
        B = [("week", "Week Warrior", "5 of the last 7 days under your daily target", good >= 5),
             ("roll", "On a Roll", "3 days in a row under target", streak >= 3),
             ("clear", "All Clear", "No appliance alerts right now", bad == 0),
             ("beat", "Beat Last Month", "On pace to use less than last month", bool(prev) and proj < prev),
             ("hero", "Action Hero", "Recorded an energy-saving action", acts >= 1),
             ("keeper", "Budget Keeper", "On pace to stay within your budget", pace <= 1)]
        xp = int(ok.sum()) * 10 + acts * 25 + sum(b[3] for b in B) * 50
        return clean(dict(target=target, streak=streak, xp=xp, level=xp // 200 + 1, to_next=200 - xp % 200,
                          badges=[dict(id=i, name=n, desc=t, got=bool(o)) for i, n, t, o in B],
                          missions=[dict(name=f"Stay under {target:.1f} kWh a day on 5 of 7 days", done=min(good, 5), goal=5),
                                    dict(name="Record one action on an appliance", done=min(acts, 1), goal=1),
                                    dict(name="Keep the air conditioner within 15% of its baseline", done=int(pd.notna(ac.pct) and ac.pct <= .15), goal=1)]))

    @app.get("/api/recap", dependencies=[Depends(require_resident)])
    def recap():
        df, last, cur, proj, st = ctx()
        d = df[df.date < last]
        end = d.date.max()
        w1, w0 = d[d.date > end - pd.Timedelta(days=7)], d[(d.date <= end - pd.Timedelta(days=7)) & (d.date > end - pd.Timedelta(days=14))]
        day = w1.groupby("date").kwh.sum()
        rate = core.bill(proj) / proj
        ch = w1.kwh.sum() / w0.kwh.sum() - 1 if w0.kwh.sum() else 0
        night = w1[(w1.hour >= 21) | (w1.hour < 6)].kwh.sum() / w1.kwh.sum()
        top = w1.groupby("appliance").kwh.sum().idxmax()
        persona = "The Energy Saver" if ch <= -.05 else "The Night Owl" if night > .5 else "The All-Rounder"
        return clean(dict(persona=persona, kwh=w1.kwh.sum(), rm=w1.kwh.sum() * rate, change=ch, best=day.idxmin(), best_kwh=day.min(),
                          worst=day.idxmax(), worst_kwh=day.max(), top=top, night=night, tip=core.RECS[top],
                          start=end - pd.Timedelta(days=6), end=end, dates=list(day.index), vals=list(day.values)))

    @app.post("/api/bill-check", dependencies=[Depends(require_resident)])
    def bill_check(b: Bill):
        est = core.bill(b.kwh)
        diff = b.amount - est
        close = abs(diff) <= max(3, .05 * est)
        verdict = ("Your bill is close to our estimate." if close else
                   f"Your bill is RM {abs(diff):.2f} {'higher' if diff > 0 else 'lower'} than our estimate. Possible reasons: a different AFA rate, "
                   "rebates or incentives, arrears or other charges, or meter-reading dates. Compare line by line with your TNB bill.")
        rows = [dict(name=r["Charge"], rm=r["Amount (RM)"], why=EXPLAIN.get(r["Charge"], "")) for r in core.tier_rows(b.kwh).to_dict("records")]
        return clean(dict(estimate=est, diff=diff, close=close, verdict=verdict, rows=rows))

    @app.get("/api/scheduler", dependencies=[Depends(require_resident)])
    def scheduler():
        df, last, *_ = ctx()
        d = df[df.date >= last - pd.Timedelta(days=14)]
        hr = d.groupby(["date", "hour"]).kwh.sum().groupby("hour").mean()
        win = sorted(((h, hr[h] + hr[(h + 1) % 24]) for h in range(8, 21)), key=lambda x: x[1])[:3]
        return clean(dict(hours=[int(h) for h in hr.index], load=list(hr.values),
                          windows=[dict(start=f"{h:02d}:00", end=f"{h + 2:02d}:00", load=v) for h, v in win]))

    @app.get("/api/compare", dependencies=[Depends(require_resident)])
    def compare():
        df, last, cur, proj, st = ctx()
        pm = df[(df.date.dt.to_period("M") == last.to_period("M") - 1) & (df.date.dt.day <= last.day)]
        a, b = cur.groupby("appliance").kwh.sum(), pm.groupby("appliance").kwh.sum()
        dd = df[df.date < last].groupby("date").kwh.sum().tail(28)
        wk = dd[dd.index.weekday >= 5].mean()
        return clean(dict(day=last.day, this=a.to_dict(), prev=b.to_dict(), this_total=a.sum(), prev_total=b.sum(),
                          weekday=dd[dd.index.weekday < 5].mean(), weekend=wk))

    @app.get("/api/devices", dependencies=[Depends(require_resident)])
    def devices():
        df = data()
        g = df.groupby("appliance").agg(last=("ts", "max"), n=("kwh", "size"), src=("source", lambda s: ", ".join(sorted(set(s)))))
        return clean([dict(name=n, room=r[2], last=str(g.loc[n, "last"]), n=g.loc[n, "n"], src=g.loc[n, "src"]) for n, r in
                      ((v[0], v) for v in core.APPLIANCES.values())])

    @app.post("/api/readings", dependencies=[Depends(require_resident)])
    def ingest(r: Reading, x_token: str = Header(default="")):
        if not config.INGEST_TOKEN:
            raise HTTPException(503, "Reading ingestion is not configured")
        if x_token != config.INGEST_TOKEN:
            raise HTTPException(401, "Bad token")
        ids = {v[0]: k for k, v in core.APPLIANCES.items()}
        if r.appliance not in ids or not 0 <= r.kwh <= 20:
            raise HTTPException(400, "Unknown appliance or invalid kWh")
        ts = pd.Timestamp(r.ts) if r.ts else pd.Timestamp.now().floor("h")
        with core.conn() as c:
            c.execute("INSERT INTO readings VALUES(?,?,?,?,?)", (ids[r.appliance], ts.isoformat(), r.kwh, r.kwh * 1000, "sensor"))
        invalidate()
        return {"ok": True}
