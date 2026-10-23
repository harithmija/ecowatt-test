"""EcoWatt AI core: SQLite storage, simulated readings, tariff, analytics, advisor."""
import json, os, re, sqlite3
from datetime import datetime, timedelta
import numpy as np
import tariff as T
from config import GRID_KG_PER_KWH
import pandas as pd

DB = os.getenv("ECOWATT_DB_PATH", os.path.join(os.path.dirname(__file__), "ecowatt.db"))

APPLIANCES = {  # id: (name, rated watts, room)
    1: ("Air conditioner", 1500, "Bedroom"),
    2: ("Refrigerator", 150, "Kitchen"),
    3: ("Water heater", 3000, "Bathroom"),
    4: ("Washing machine", 500, "Laundry"),
    5: ("Bedroom lights", 40, "Bedroom"),
    6: ("Bedroom fan", 60, "Bedroom"),
    7: ("Kitchen lights", 40, "Kitchen"),
    8: ("Living room lights", 60, "Living room"),
    9: ("Living room fan", 75, "Living room"),
    10: ("Television", 120, "Living room"),
    11: ("Bathroom lights", 20, "Bathroom"),
    12: ("Laundry lights", 20, "Laundry"),
}


def appliance_category(name):
    if name.lower().endswith(" lights"):
        return "Lights"
    if name.lower().endswith(" fan"):
        return "Fans"
    return name


DEFAULT_TARIFF = None  # tariff now lives in tariff.py

RECS = {
    "Air conditioner": "Check operating hours and thermostat setpoint, clean the filters, and look for open doors or windows.",
    "Refrigerator": "Check the door seal, avoid placing hot food inside, and leave space around the coils.",
    "Water heater": "Shorten heating periods, lower the thermostat and check for dripping hot taps.",
    "Washing machine": "Use full loads and cold-water cycles where possible.",
    "Bedroom lights": "Switch off bedroom lights when the room is empty and use daylight where practical.",
    "Bedroom fan": "Switch off the fan when the room is empty; use a comfortable speed.",
    "Kitchen lights": "Switch off kitchen lights when they are not needed.",
    "Living room lights": "Switch off lights when the living room is empty and use daylight where practical.",
    "Living room fan": "Switch off the fan when the room is empty; use a comfortable speed.",
    "Television": "Turn the television off when it is not being watched instead of leaving it on standby.",
    "Bathroom lights": "Switch off bathroom lights when they are not needed.",
    "Laundry lights": "Switch off laundry lights when the room is empty.",
}

ACTION_RECOMMENDATIONS = {
    "Air conditioner": [
        {"id": "reduce_runtime", "label": "Reduce AC runtime by 1 hour per day", "reduction": 0.08},
        {"id": "clean_filters", "label": "Clean the AC filters", "reduction": 0.03},
        {"id": "raise_setpoint", "label": "Raise the thermostat setpoint by 1°C", "reduction": 0.05},
    ],
    "Refrigerator": [
        {"id": "check_seal", "label": "Check and improve the refrigerator door seal", "reduction": 0.05},
        {"id": "cool_food", "label": "Let hot food cool before refrigerating it", "reduction": 0.03},
        {"id": "clear_coils", "label": "Leave space for airflow around the coils", "reduction": 0.03},
    ],
    "Water heater": [
        {"id": "shorten_heating", "label": "Shorten water-heater use by 20%", "reduction": 0.20},
        {"id": "lower_thermostat", "label": "Lower the water-heater thermostat setting", "reduction": 0.05},
        {"id": "fix_drips", "label": "Fix dripping hot-water taps", "reduction": 0.05},
    ],
    "Washing machine": [
        {"id": "full_loads", "label": "Run only full washing-machine loads", "reduction": 0.10},
        {"id": "cold_cycles", "label": "Use cold-water washing cycles", "reduction": 0.15},
    ],
}


def conn():
    return sqlite3.connect(DB)


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS appliances(id INTEGER PRIMARY KEY, name TEXT, rated_w REAL, room TEXT);
        CREATE TABLE IF NOT EXISTS readings(appliance_id INTEGER, ts TEXT, kwh REAL, power_w REAL, source TEXT);
        CREATE INDEX IF NOT EXISTS ix_r ON readings(appliance_id, ts);
        CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT, appliance TEXT, ts TEXT, note TEXT);
        """)
        action_columns = {row[1] for row in c.execute("PRAGMA table_info(actions)")}
        for column, sql_type in (
            ("action_id", "TEXT"),
            ("estimated_kwh", "REAL"),
            ("estimated_rm", "REAL"),
        ):
            if column not in action_columns:
                c.execute(f"ALTER TABLE actions ADD COLUMN {column} {sql_type}")
        for i, (n, w, r) in APPLIANCES.items():
            c.execute("INSERT OR IGNORE INTO appliances VALUES(?,?,?,?)", (i, n, w, r))
        c.execute("DELETE FROM readings WHERE source = 'simulated'")
        simulate(c)


def simulate(c, days=75, seed=None):
    """Generate fresh hourly demo readings while preserving rows from real sensors."""
    rng = np.random.default_rng(seed)
    end = datetime.now().replace(minute=0, second=0, microsecond=0)
    drift = end - timedelta(days=7)
    rows = []
    for ts in pd.date_range(end - timedelta(days=days), end, freq="h"):
        h, wd = ts.hour, ts.weekday()
        ac = rng.uniform(0.55, 0.85) if (h >= 21 or h < 7) else (rng.uniform(0.4, 0.7) if wd >= 5 and 13 <= h < 17 else 0)
        if ts >= drift:
            ac = ac * 1.15 + (rng.uniform(0.5, 0.9) if 12 <= h < 18 else 0)
        fr = max(0, rng.normal(0.055, 0.006))
        wh = rng.uniform(0.5, 1.1) if h in (6, 7, 19, 20) else 0
        wm = rng.uniform(0.35, 0.7) if (wd in (1, 3, 5) and h in (19, 20)) else 0
        bedroom_lights = rng.uniform(0.025, 0.04) if h in (6, 7) or 18 <= h < 23 else 0
        bedroom_fan = rng.uniform(0.035, 0.06) if h >= 21 or h < 7 or (wd >= 5 and 12 <= h < 16) else 0
        kitchen_lights = rng.uniform(0.025, 0.04) if h in (6, 7, 18, 19, 20) else 0
        living_lights = rng.uniform(0.04, 0.06) if h in (6, 7) or 17 <= h < 23 else 0
        living_fan = rng.uniform(0.045, 0.075) if 12 <= h < 17 or 19 <= h < 23 else 0
        tv = rng.uniform(0.07, 0.12) if 19 <= h < 23 or (wd >= 5 and 13 <= h < 17) else 0
        bathroom_lights = rng.uniform(0.012, 0.02) if h in (6, 7, 20, 21) else 0
        laundry_lights = rng.uniform(0.012, 0.02) if h in (18, 19, 20) else 0
        usage = (
            ac, fr, wh, wm, bedroom_lights, bedroom_fan, kitchen_lights,
            living_lights, living_fan, tv, bathroom_lights, laundry_lights,
        )
        for i, v in zip(APPLIANCES, usage):
            rows.append((i, ts.isoformat(), round(v, 4), round(v * 1000, 1), "simulated"))
    c.executemany("INSERT INTO readings VALUES(?,?,?,?,?)", rows)


def load_readings():
    with conn() as c:
        df = pd.read_sql("SELECT r.ts, r.kwh, r.power_w, r.source, a.name appliance FROM readings r "
                         "JOIN appliances a ON a.id=r.appliance_id", c, parse_dates=["ts"])
        actions = c.execute(
            "SELECT appliance, ts, action_id FROM actions WHERE action_id IS NOT NULL ORDER BY ts"
        ).fetchall()
    effects = {}
    for appliance, ts, action_id in actions:
        reduction = next(
            (
                action["reduction"]
                for action in ACTION_RECOMMENDATIONS.get(appliance, [])
                if action["id"] == action_id
            ),
            None,
        )
        if reduction is not None:
            effects.setdefault((appliance, action_id), (pd.Timestamp(ts).floor("h"), reduction))

    if effects:
        simulated = df.source == "simulated"
        for (appliance, _), (effective_at, reduction) in sorted(
            effects.items(), key=lambda item: item[1][0]
        ):
            affected = (
                simulated
                & (df.appliance == appliance)
                & (df.ts >= effective_at)
            )
            df.loc[affected, ["kwh", "power_w"]] *= 1 - reduction
    df["date"] = df.ts.dt.normalize()
    df["hour"] = df.ts.dt.hour
    return df


def breakdown(kwh):
    """Estimated TNB bill components (RM). Estimate only: excludes any energy-efficiency incentive."""
    kwh = max(kwh, 0.0)
    gen = min(kwh, 1500) * T.GENERATION[0][1] + max(kwh - 1500, 0) * T.GENERATION[1][1]
    energy = gen + kwh * (T.CAPACITY + T.NETWORK)
    prot = kwh <= T.PROTECTED_KWH
    afa = 0 if prot else kwh * T.afa_rate()
    retail = 0 if prot else T.RETAIL
    kwtbb = 0 if kwh <= T.KWTBB_EXEMPT_KWH else T.KWTBB_RATE * (energy + afa)
    sst = 0 if prot else T.SST_RATE * (energy + afa) * (kwh - T.PROTECTED_KWH) / kwh
    return [("Electricity (generation, capacity, network)", energy), ("Fuel adjustment (AFA)", afa),
            ("Retail charge", retail), ("Renewable energy fund (1.6%)", kwtbb), ("Service tax (8%)", sst)]


def bill(kwh, tariff=None):
    return sum(v for _, v in breakdown(kwh))


def tier_rows(kwh, tariff=None):
    rows = [{"Charge": k, "Amount (RM)": round(v, 2)} for k, v in breakdown(kwh)]
    rows.append({"Charge": "Total", "Amount (RM)": round(bill(kwh), 2)})
    return pd.DataFrame(rows)


def saving_rm(month_kwh, saved_kwh, tariff=DEFAULT_TARIFF):
    return bill(month_kwh, tariff) - bill(max(0, month_kwh - saved_kwh), tariff)


def action_estimates(appliance, appliance_month_kwh, household_month_kwh):
    appliance_month_kwh = max(float(appliance_month_kwh), 0.0)
    household_month_kwh = max(float(household_month_kwh), 0.0)
    estimates = []
    for action in ACTION_RECOMMENDATIONS.get(appliance, []):
        saved_kwh = appliance_month_kwh * action["reduction"]
        estimates.append({
            "id": action["id"],
            "label": action["label"],
            "assumed_reduction_pct": action["reduction"] * 100,
            "estimated_kwh": round(saved_kwh, 2),
            "estimated_rm": round(saving_rm(household_month_kwh, saved_kwh), 2),
        })
    return estimates


def appliance_stats(df, tariff=DEFAULT_TARIFF):
    """Compare the last 7 full days with the earlier baseline.
    high = recent average >15% above baseline; abnormal = >25% above AND at least 3 days beyond baseline+2sd."""
    daily = df.groupby(["appliance", "date"]).kwh.sum().reset_index()
    last = daily.date.max()
    month_kwh = df[df.date.dt.to_period("M") == last.to_period("M")].kwh.sum()
    out = []
    for name, g in daily.groupby("appliance"):
        g = g[g.date < last].sort_values("date")
        recent, base = g.tail(7), g.iloc[:-7]
        if len(base) < 14:
            out.append(dict(appliance=name, status="insufficient data", baseline=np.nan, recent=recent.kwh.mean(),
                            pct=np.nan, days_over=0, extra_month_kwh=0, extra_month_rm=0,
                            why="Fewer than 14 baseline days, so no conclusion can be drawn."))
            continue
        bm, sd = base.kwh.mean(), max(base.kwh.std(), 1e-6)
        rm = recent.kwh.mean()
        pct = rm / bm - 1
        over = int((recent.kwh > bm + 2 * sd).sum())
        status = "abnormal" if (pct > .25 and over >= 3) else "high" if pct > .15 else "normal"
        extra = max(0, rm - bm) * 30
        why = (f"Last 7 days average {rm:.2f} kWh/day against a baseline of {bm:.2f} kWh/day ({pct:+.0%}). "
               f"{over} of 7 days exceeded baseline + 2 standard deviations ({bm + 2*sd:.2f} kWh). ")
        why += {"abnormal": "The rise is sustained, so it is flagged as abnormal. This does not prove a fault; check usage conditions first.",
                "high": "Usage is elevated but not consistently outside normal variation, so it is flagged as high only.",
                "normal": "Within normal variation."}[status]
        out.append(dict(appliance=name, status=status, baseline=bm, recent=rm, pct=pct, days_over=over,
                        extra_month_kwh=extra, extra_month_rm=saving_rm(month_kwh + extra, extra, tariff) if extra else 0, why=why))
    return pd.DataFrame(out)


def add_action(appliance, note, action_id=None, estimated_kwh=None, estimated_rm=None):
    with conn() as c:
        c.execute(
            """INSERT INTO actions(appliance, ts, note, action_id, estimated_kwh, estimated_rm)
               VALUES(?,?,?,?,?,?)""",
            (
                appliance,
                datetime.now().isoformat(timespec="minutes"),
                note,
                action_id,
                estimated_kwh,
                estimated_rm,
            ),
        )


def load_actions():
    with conn() as c:
        return pd.read_sql("SELECT * FROM actions ORDER BY ts DESC", c)


def review_action(df, appliance, ts):
    """Average daily kWh for 7 days before vs. days since the action."""
    t = pd.Timestamp(ts).normalize()
    d = df[df.appliance == appliance].groupby("date").kwh.sum()
    before, after = d[(d.index < t)].tail(7), d[d.index > t]
    return (before.mean() if len(before) else np.nan), (after.mean() if len(after) else np.nan), len(after)


def ev_scenarios(df, tariff=None, kwh_per_km=0.16, efficiency=0.90):
    """What-if: extra monthly kWh and RM from home EV charging (assumptions, not car-specific)."""
    last = df.date.max()
    cur = df[df.date.dt.to_period("M") == last.to_period("M")]
    month_kwh = cur.kwh.sum() / last.day * last.days_in_month
    rows = []
    for km in (20, 40, 60, 80):
        k = km * 30 * kwh_per_km / efficiency
        rows.append({"km_per_day": km, "extra_kwh_month": round(k), "extra_bill_rm_month": round(bill(month_kwh + k) - bill(month_kwh), 2)})
    return {"assumptions": f"{kwh_per_km} kWh/km, {efficiency:.0%} charging efficiency, charged at home daily, standard tariff",
            "current_projected_month_kwh": round(month_kwh), "scenarios": rows}


def is_ev_question(q):
    return bool(re.search(r"\b(ev|tesla|electric (car|vehicle)|charger)\b", q.lower()))


# ---------------- AI advisor ----------------
SYSTEM = ("You are EcoWatt AI, a home energy advisor. Python already did every calculation: use only numbers in the JSON data "
          "and never invent household readings. For what-if questions (e.g. an EV charger) use the supplied what_if scenarios, "
          "state their assumptions, pick the closest row and ask for daily driving distance if unknown. "
          "Never diagnose a hardware fault; a high reading is not proof of malfunction. Say that data is simulated and costs are "
          "estimates. For non-energy questions, politely say you only help with household energy and electricity costs.")


def build_context(df, tariff=DEFAULT_TARIFF):
    st = appliance_stats(df, tariff)
    last = df.date.max()
    m = df[df.date.dt.to_period("M") == last.to_period("M")]
    prev = df[df.date.dt.to_period("M") == (last.to_period("M") - 1)]
    return json.dumps({
        "data_source": "simulated" if (df.source == "simulated").all() else "mixed/sensor",
        "month_to_date_kwh": round(m.kwh.sum(), 1), "month_to_date_bill_rm": round(bill(m.kwh.sum(), tariff), 2),
        "previous_month_kwh": round(prev.kwh.sum(), 1),
        "by_appliance_kwh": m.groupby("appliance").kwh.sum().round(1).to_dict(),
        "anomaly_analysis": st.round(2).fillna("n/a").to_dict("records"),
        "recommendation_library": RECS, "what_if_ev_charger": ev_scenarios(df)}, default=str)


def ask_gemini(question, context, api_key):
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=60000),
    )
    r = client.interactions.create(
        model="gemini-3.8-flash",
        input=f"{SYSTEM}\n\nDATA:\n{context}\n\nRESIDENT QUESTION: {question}",
        generation_config={"thinking_level": "low"},
    )
    if not r.output_text:
        raise RuntimeError("Gemini returned no text response.")
    return r.output_text


def fallback_answer(df, tariff=None, question=""):
    """Rule-based explanation used when no Gemini key is set."""
    if is_ev_question(question):
        s = ev_scenarios(df)
        lines = "\n".join(f"- {r['km_per_day']} km/day: +{r['extra_kwh_month']} kWh, about +RM {r['extra_bill_rm_month']}/month" for r in s["scenarios"])
        return (f"Estimated extra cost of charging an EV at home:\n{lines}\n\nAssumptions: {s['assumptions']}. "
                "Check TNB for EV or time-of-use tariffs, and have an electrician confirm your wiring can support a wall charger.")
    st = appliance_stats(df, tariff).sort_values("extra_month_rm", ascending=False)
    t = st.iloc[0]
    if t.status in ("normal", "insufficient data"):
        return "No appliance shows a notable change versus its baseline. (Simulated data; rule-based advice.)"
    return (f"Investigate the **{t.appliance}** first. {t.why}\n\nIf this continues it could add about "
            f"{t.extra_month_kwh:.0f} kWh (RM {t.extra_month_rm:.2f}) per month. Suggested checks: {RECS[t.appliance]}\n\n"
            "_Simulated data; rule-based advice._")
