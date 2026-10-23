"""Friendly-features API: eco score, budget, challenges, recap, scheduler, compare, devices."""
from datetime import datetime
import numpy as np
import pandas as pd
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel
import core, config

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


class Reading(BaseModel):
    appliance: str
    kwh: float
    ts: str | None = None


def _scheduler_plan(df):
    flexible = ("Washing machine", "Water heater", "Television", "Lights", "Fans")
    monitored = ("Air conditioner", "Refrigerator", *flexible)
    last = pd.Timestamp(df.date.max()).normalize()
    history_start = last - pd.Timedelta(days=55)
    history = df[df.date >= history_start].copy()
    history["appliance"] = history.appliance.map(core.appliance_category)
    history = history.groupby(["date", "hour", "appliance"], as_index=False).agg(
        kwh=("kwh", "sum"),
        source=("source", lambda sources: "simulated" if (sources == "simulated").all() else "sensor"),
    )
    dates = pd.date_range(history.date.min(), last, freq="D")
    if len(dates) < 28:
        raise ValueError("At least 28 days of usage history are needed to learn scheduling behavior.")

    recent_start = last - pd.Timedelta(days=6)
    recent = history[history.date >= recent_start]
    stable = history[history.date < recent_start]
    stable_dates = pd.date_range(stable.date.min(), stable.date.max(), freq="D")
    weeks = len(stable_dates) / 7
    minimum_events = max(2, int(weeks * 0.25))
    templates = []
    behavior = []
    for appliance in flexible:
        readings = stable[stable.appliance == appliance]
        events = {}
        for date, day in readings.groupby("date"):
            active = day[day.kwh >= 0.01].sort_values("hour")
            if active.empty:
                continue
            hours = active.hour.astype(int).tolist()
            groups = []
            for hour in hours:
                if not groups or hour != groups[-1][-1] + 1:
                    groups.append([hour])
                else:
                    groups[-1].append(hour)
            for group in groups:
                start, duration = group[0], len(group)
                profile = [float(active.loc[active.hour == hour, "kwh"].sum()) for hour in group]
                key = (int(pd.Timestamp(date).dayofweek), start, duration)
                events.setdefault(key, []).append(profile)

        for (weekday, start, duration), profiles in events.items():
            if len(profiles) < minimum_events:
                continue
            typical_profile = np.mean(np.asarray(profiles), axis=0).tolist()
            templates.append({
                "appliance": appliance,
                "weekday": weekday,
                "preferred_start": start,
                "duration": duration,
                "profile": typical_profile,
                "event_count": len(profiles),
            })

    day_names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    behavior = []
    for appliance in monitored:
        readings = stable[stable.appliance == appliance]
        threshold = 0.01 if appliance in ("Refrigerator", "Lights", "Fans", "Television") else 0.1
        active = readings[readings.kwh >= threshold]
        learned = [item for item in templates if item["appliance"] == appliance]
        if active.empty:
            continue

        daily_use = active.groupby("date").kwh.sum()
        active_days = set(pd.to_datetime(daily_use.index).dayofweek)
        hour_use_days = active.groupby("hour").date.nunique()
        common_hours = sorted(
            int(hour) for hour, count in hour_use_days.items()
            if count / max(1, len(stable_dates)) >= (0.9 if appliance == "Refrigerator" else 0.25)
        )
        if len(common_hours) == 24:
            time_windows = ["all day"]
        else:
            time_windows = []
            windows = []
            for hour in common_hours:
                if not windows or hour != windows[-1][-1] + 1:
                    windows.append([hour])
                else:
                    windows[-1].append(hour)
            if appliance == "Air conditioner" and len(windows) > 1 and windows[0][0] == 0 and windows[-1][-1] == 23:
                time_windows = [f"{windows[-1][0]:02d}:00–{(windows[0][-1] + 1) % 24:02d}:00"]
                windows = windows[1:-1]
            time_windows.extend(
                f"{window[0]:02d}:00–{(window[-1] + 1) % 24:02d}:00"
                for window in windows
            )

        routine = {
            "appliance": appliance,
            "room": {
                "Air conditioner": "Bedroom",
                "Refrigerator": "Kitchen",
                "Water heater": "Bathroom",
                "Washing machine": "Laundry",
                "Television": "Living room",
                "Lights": "All rooms",
                "Fans": "All rooms",
            }[appliance],
            "preferred_days": [day_names[day] for day in sorted(active_days)],
            "preferred_windows": time_windows or ["throughout the day"],
            "active_readings": int(len(active)),
            "typical_weekly_kwh": round(float(daily_use.mean() * 7), 2),
        }
        if appliance == "Refrigerator":
            routine.update({
                "routine_type": "continuous",
                "routine_tip": "This appliance uses energy throughout the day. Keep the door closed, check the seal, and leave airflow around it; it is not a device to schedule off.",
            })
        elif appliance == "Air conditioner":
            routine.update({
                "routine_type": "comfort-guidance",
                "routine_tip": "These are the usual cooling periods in the stable history. Keep comfort and health first; if a room is empty, consider a suitable timer or a modest setpoint adjustment.",
            })
        elif appliance in ("Lights", "Fans", "Television"):
            preferred_hours = {}
            for item in learned:
                preferred_hours.setdefault(item["preferred_start"], 0)
                preferred_hours[item["preferred_start"]] += item["event_count"]
            routine.update({
                "routine_type": "flexible",
                "preferred_hours": sorted(preferred_hours) or common_hours,
                "typical_duration_hours": round(
                    float(np.median([item["duration"] for item in learned]))
                    if learned else 1,
                    1,
                ),
                "weekly_runs": len(learned),
                "routine_tip": {
                    "Lights": "Switch lights off when rooms are empty and use daylight when practical. Typical active hours are not a reason to keep lights on.",
                    "Fans": "Switch fans off when rooms are empty and use a comfortable speed. Typical active hours are not a reason to run a fan unnecessarily.",
                    "Television": "Turn the television off when nobody is watching instead of leaving it on standby.",
                }[appliance],
            })
        else:
            preferred_hours = {}
            for item in learned:
                preferred_hours.setdefault(item["preferred_start"], 0)
                preferred_hours[item["preferred_start"]] += item["event_count"]
            routine.update({
                "routine_type": "flexible",
                "preferred_hours": sorted(preferred_hours),
                "typical_duration_hours": round(float(np.median([item["duration"] for item in learned])), 1),
                "weekly_runs": len(learned),
                "routine_tip": (
                    "Keep laundry to these usual days and run a full load where practical, rather than adding small extra cycles."
                    if appliance == "Washing machine"
                    else "Heat water only when needed; switch it off after use or use a timer instead of leaving it on."
                ),
            })
        behavior.append(routine)

    future_dates = [last + pd.Timedelta(days=offset) for offset in range(1, 8)]
    jobs = []
    for date in future_dates:
        for template in templates:
            if date.dayofweek == template["weekday"]:
                jobs.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "weekday": date.strftime("%A"),
                    "appliance": template["appliance"],
                    "start": f"{template['preferred_start']:02d}:00",
                    "end": f"{(template['preferred_start'] + template['duration']) % 24:02d}:00",
                    "duration_hours": template["duration"],
                    "typical_kwh": round(sum(template["profile"]), 2),
                })

    if not any(item["routine_type"] == "flexible" for item in behavior):
        raise ValueError("No repeatable routines were found in the available appliance history.")

    routines = {item["appliance"]: item for item in behavior}
    jobs_by_date = {}
    for job in jobs:
        jobs_by_date.setdefault(job["date"], []).append(job)
    weekly_plan = []
    for date in future_dates:
        date_key = date.strftime("%Y-%m-%d")
        day_jobs = jobs_by_date.get(date_key, [])
        use = []
        save = []
        ac_routine = routines.get("Air conditioner")
        if ac_routine:
            windows = ", ".join(ac_routine["preferred_windows"])
            use.append({
                "appliance": "Air conditioner",
                "time": windows,
                "advice": f"When cooling is needed and the room is occupied, these are the usual periods: {windows}.",
            })
            save.append({
                "appliance": "Air conditioner",
                "time": "When the room is empty",
                "advice": "Consider a suitable timer, close doors and windows, and clean filters. Keep comfort and health needs first.",
            })
        if "Refrigerator" in routines:
            use.append({
                "appliance": "Refrigerator",
                "time": "All day",
                "advice": "Keep it running; it is a continuous-use appliance, not one to switch off on a schedule.",
            })
            save.append({
                "appliance": "Refrigerator",
                "time": "Every day",
                "advice": "Open the door only as needed, check the seal, and leave space around the appliance for airflow.",
            })
        for appliance in ("Lights", "Fans", "Television"):
            routine = routines.get(appliance)
            if not routine:
                continue
            if date.strftime("%A") in routine["preferred_days"]:
                use.append({
                    "appliance": appliance,
                    "time": ", ".join(routine["preferred_windows"]),
                    "advice": f"Your readings most often show use around {', '.join(routine['preferred_windows'])}. Use only when needed.",
                })
            save.append({
                "appliance": appliance,
                "time": "When not needed",
                "advice": routine["routine_tip"],
            })
        for job in day_jobs:
            if job["appliance"] in ("Lights", "Fans", "Television"):
                continue
            use.append({
                "appliance": job["appliance"],
                "time": f"{job['start']}–{job['end']}",
                "advice": f"Usual run: about {job['typical_kwh']:.1f} kWh for {job['duration_hours']} hour(s).",
            })
        washing = routines.get("Washing machine")
        if washing and not any(job["appliance"] == "Washing machine" for job in day_jobs):
            days = ", ".join(washing["preferred_days"])
            save.append({
                "appliance": "Washing machine",
                "time": "Wait for a usual laundry day",
                "advice": f"Add to a full load on your usual {days} routine rather than running an extra small cycle.",
            })
        if "Water heater" in routines:
            save.append({
                "appliance": "Water heater",
                "time": "After use",
                "advice": "Switch it off when hot water is no longer needed; avoid heating water without a current need.",
            })
        weekly_plan.append({
            "date": date_key,
            "weekday": date.strftime("%A"),
            "use": use,
            "save": save,
        })

    ac_history = history[history.appliance == "Air conditioner"]
    ac_stable = stable[stable.appliance == "Air conditioner"]
    ac_recent_daily = ac_history[ac_history.date >= recent_start].groupby("date").kwh.sum()
    ac_stable_daily = ac_stable.groupby("date").kwh.sum()
    ac_recent_average = float(ac_recent_daily.mean()) if not ac_recent_daily.empty else 0
    ac_usual_average = float(ac_stable_daily.mean()) if not ac_stable_daily.empty else 0
    ac_change_pct = (ac_recent_average / ac_usual_average - 1) * 100 if ac_usual_average else 0
    return {
        "history_days": len(dates),
        "routine_history_days": len(stable_dates),
        "activity_readings": sum(item["active_readings"] for item in behavior),
        "data_source": "simulated" if (history.source == "simulated").all() else "mixed/sensor",
        "behavior": behavior,
        "jobs": jobs,
        "weekly_plan": weekly_plan,
        "alerts": [{
            "appliance": "Air conditioner",
            "recent_daily_kwh": round(ac_recent_average, 2),
            "usual_daily_kwh": round(ac_usual_average, 2),
            "change_pct": round(ac_change_pct, 1),
        }] if ac_change_pct >= 25 else [],
    }


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

    @app.get("/api/scheduler", dependencies=[Depends(require_resident)])
    def scheduler():
        try:
            return clean(_scheduler_plan(data()))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

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
