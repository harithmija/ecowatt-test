import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import core

st.set_page_config("EcoWatt AI", layout="wide")
GREEN, PAL = "#0B4F3C", ["#0B4F3C", "#3E9B73", "#9BD3B5", "#C9A227"]
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;600;700&display=swap');
html, body, [class*="css"] {font-family:'Instrument Sans',sans-serif;}
h1,h2,h3 {color:#0B4F3C; letter-spacing:-0.01em;}
[data-testid="stSidebar"] {background:#0B4F3C;} [data-testid="stSidebar"] * {color:#fff !important;}
[data-testid="stMetric"] {border:1px solid #D5E5DC; border-radius:8px; padding:12px 16px; background:#fff;}
.flag {border-left:4px solid; padding:8px 12px; margin:6px 0; background:#F5FAF7;}
</style>""", unsafe_allow_html=True)

core.init_db()
df = core.load_readings()
side = st.sidebar
side.title("EcoWatt AI")
side.caption("Smart energy management")
page = side.radio("Go to", ["Overview", "Monthly report", "Appliances", "AI advisor", "Savings simulator", "Sustainability"])
side.divider()
side.caption("Tariff (RM/kWh, illustrative: edit to match your bill)")
tariff = []
prev = 0
for cap, rate in core.DEFAULT_TARIFF:
    lbl = f"Above {prev} kWh" if cap == float("inf") else f"{prev}-{cap} kWh"
    tariff.append((cap, side.number_input(lbl, value=rate, step=0.01, format="%.3f")))
    prev = cap
api_key = side.text_input("Gemini API key", value=os.getenv("GEMINI_API_KEY", ""), type="password")
if (df.source == "simulated").all():
    side.info("All readings are simulated.")

last = df.date.max()
cur = df[df.date.dt.to_period("M") == last.to_period("M")]
stats = core.appliance_stats(df, tariff)
flagged = stats[stats.status.isin(["abnormal", "high"])]


def tidy(fig, h=360):
    fig.update_layout(height=h, margin=dict(l=0, r=0, t=30, b=0), plot_bgcolor="#fff", legend_title_text="")
    return fig


if page == "Overview":
    st.title("Overview")
    kwh = cur.kwh.sum()
    elapsed = last.day + 0.0
    days_in = last.days_in_month
    proj = kwh / elapsed * days_in
    c = st.columns(4)
    c[0].metric("Used this month", f"{kwh:.0f} kWh")
    c[1].metric("Estimated bill so far", f"RM {core.bill(kwh, tariff):.2f}")
    c[2].metric("Projected month-end", f"RM {core.bill(proj, tariff):.2f}", f"{proj:.0f} kWh")
    c[3].metric("Potential savings", f"RM {flagged.extra_month_rm.sum():.2f}/mo")
    a, b = st.columns([1, 1])
    by = cur.groupby("appliance").kwh.sum().reset_index()
    a.subheader("Where the energy goes")
    a.plotly_chart(tidy(px.pie(by, names="appliance", values="kwh", hole=.55, color_discrete_sequence=PAL)), use_container_width=True)
    t30 = df[df.date > last - pd.Timedelta(days=30)].groupby(["date", "appliance"]).kwh.sum().reset_index()
    b.subheader("Last 30 days")
    b.plotly_chart(tidy(px.area(t30, x="date", y="kwh", color="appliance", color_discrete_sequence=PAL)), use_container_width=True)
    st.subheader("Alerts and next steps")
    if flagged.empty:
        st.success("No unusual consumption detected.")
    for _, r in flagged.sort_values("extra_month_rm", ascending=False).iterrows():
        col = "#B3261E" if r.status == "abnormal" else "#C9A227"
        st.markdown(f"<div class='flag' style='border-color:{col}'><b>{r.appliance}: {r.status}</b><br>{r.why}<br>"
                    f"<b>Next:</b> {core.RECS[r.appliance]} Possible saving: RM {r.extra_month_rm:.2f}/month.</div>", unsafe_allow_html=True)

elif page == "Monthly report":
    st.title("Monthly electricity report")
    months = sorted(df.date.dt.to_period("M").unique(), reverse=True)
    m = st.selectbox("Month", months, format_func=lambda p: p.strftime("%B %Y"))
    d = df[df.date.dt.to_period("M") == m]
    daily = d.groupby(["date", "appliance"]).kwh.sum().reset_index()
    tot = d.kwh.sum()
    dd = d.groupby("date").kwh.sum()
    c = st.columns(5)
    c[0].metric("Total", f"{tot:.1f} kWh")
    c[1].metric("Estimated bill", f"RM {core.bill(tot, tariff):.2f}")
    c[2].metric("Daily average", f"{dd.mean():.1f} kWh")
    c[3].metric("Peak day", f"{dd.idxmax():%d %b}", f"{dd.max():.1f} kWh", delta_color="off")
    c[4].metric("Top appliance", d.groupby("appliance").kwh.sum().idxmax())
    if m == last.to_period("M"):
        st.caption(f"Month in progress: {last.day} of {last.days_in_month} days recorded. Projected {tot/last.day*last.days_in_month:.0f} kWh.")
    st.subheader("Daily consumption by appliance")
    st.plotly_chart(tidy(px.bar(daily, x="date", y="kwh", color="appliance", color_discrete_sequence=PAL)), use_container_width=True)
    a, b = st.columns(2)
    cum = dd.cumsum().reset_index()
    cum["rm"] = cum.kwh.apply(lambda k: core.bill(k, tariff))
    a.subheader("Cumulative bill (RM)")
    a.plotly_chart(tidy(px.line(cum, x="date", y="rm", color_discrete_sequence=[GREEN])), use_container_width=True)
    b.subheader("When power is used (kWh by day and hour)")
    hm = d.groupby(["date", "hour"]).kwh.sum().reset_index().pivot(index="hour", columns="date", values="kwh")
    b.plotly_chart(tidy(go.Figure(go.Heatmap(z=hm.values, x=hm.columns, y=hm.index, colorscale="Greens"))), use_container_width=True)
    st.subheader("Bill breakdown by tariff tier")
    st.dataframe(core.tier_rows(tot, tariff), hide_index=True, use_container_width=True)
    st.subheader("Daily table")
    tbl = daily.pivot(index="date", columns="appliance", values="kwh").round(2)
    tbl["Total kWh"] = tbl.sum(axis=1).round(2)
    tbl["Cumulative RM"] = cum.set_index("date").rm.round(2)
    st.dataframe(tbl, use_container_width=True)
    st.download_button("Download CSV", tbl.to_csv().encode(), f"ecowatt_{m}.csv", "text/csv")

elif page == "Appliances":
    st.title("Appliance monitoring")
    for i, (name, w, room) in core.APPLIANCES.items():
        r = stats[stats.appliance == name].iloc[0]
        a = df[df.appliance == name]
        with st.expander(f"{name} ({room}): {r.status}", expanded=r.status in ("abnormal", "high")):
            c = st.columns(4)
            c[0].metric("Latest power", f"{a.sort_values('ts').power_w.iloc[-1]:.0f} W")
            c[1].metric("This month", f"{a[a.date.dt.to_period('M') == last.to_period('M')].kwh.sum():.1f} kWh")
            c[2].metric("Baseline", f"{r.baseline:.2f} kWh/day")
            c[3].metric("Last 7 days", f"{r.recent:.2f} kWh/day", f"{r.pct:+.0%}", delta_color="inverse")
            dly = a.groupby("date").kwh.sum().reset_index()
            fig = px.bar(dly.tail(30), x="date", y="kwh", color_discrete_sequence=[GREEN])
            if pd.notna(r.baseline):
                fig.add_hline(y=r.baseline, line_dash="dash", annotation_text="baseline")
            st.plotly_chart(tidy(fig, 260), use_container_width=True)
            st.write(r.why)
            if r.status in ("abnormal", "high"):
                st.write(f"**Suggested checks:** {core.RECS[name]}  \n**Possible saving:** RM {r.extra_month_rm:.2f}/month")
            note = st.text_input("Record an action taken", key=f"n{i}", placeholder="e.g. Cleaned filter, raised setpoint to 25 C")
            if st.button("Save action", key=f"b{i}") and note:
                core.add_action(name, note)
                st.rerun()
    st.subheader("Action log and review")
    acts = core.load_actions()
    if acts.empty:
        st.caption("Actions you record appear here with a before/after comparison.")
    for _, x in acts.iterrows():
        bef, aft, n = core.review_action(df, x.appliance, x.ts)
        res = f"{bef:.2f} to {aft:.2f} kWh/day over {n} day(s)" if n else f"baseline {bef:.2f} kWh/day; no readings after the action yet"
        st.write(f"**{x.ts}** {x.appliance}: {x.note} ({res})")

elif page == "AI advisor":
    st.title("AI energy advisor")
    st.caption("Python calculates everything; the AI only explains the results." + ("" if api_key else " No Gemini key set, so answers use built-in rules."))
    ctx = core.build_context(df, tariff)
    hist = st.session_state.setdefault("chat", [])
    for role, txt in hist:
        st.chat_message(role).write(txt)
    q = st.chat_input("My electricity usage increased this month. Which appliance should I investigate first?")
    if q:
        hist.append(("user", q))
        try:
            ans = core.ask_gemini(q, ctx, api_key) if api_key else core.fallback_answer(df, tariff)
        except Exception as e:
            ans = core.fallback_answer(df, tariff) + f"\n\n(Gemini unavailable: {e})"
        hist.append(("assistant", ans))
        st.rerun()

elif page == "Savings simulator":
    st.title("Savings simulator")
    month_kwh = cur.kwh.sum() / last.day * last.days_in_month
    ac = df[df.appliance == "Air conditioner"].groupby("date").kwh.sum().iloc[-8:-1].mean()
    wh = df[df.appliance == "Water heater"].groupby("date").kwh.sum().iloc[-8:-1].mean()
    ac_hours = df[(df.appliance == "Air conditioner") & (df.kwh > 0.05)].groupby("date").size().iloc[-8:-1].mean()
    c = st.columns(3)
    h = c[0].slider("Cut AC running hours per day", 0.0, 4.0, 1.0, 0.5)
    t = c[1].slider("Raise AC setpoint (C)", 0, 4, 1)
    w = c[2].slider("Shorten water-heater use (%)", 0, 50, 20, 5)
    st.caption("Assumptions: each 1 C higher setpoint saves about 6% of AC energy; savings are applied to the last 7-day averages.")
    per_hr = ac / max(ac_hours, 1)
    s_ac_h, s_ac_t = h * per_hr * 30, max(0, ac - h * per_hr) * 0.06 * t * 30
    s_wh = wh * w / 100 * 30
    items = pd.DataFrame({"Action": ["Fewer AC hours", "Higher AC setpoint", "Shorter water heating"], "kWh/month": [s_ac_h, s_ac_t, s_wh]})
    total = items["kWh/month"].sum()
    items["RM/month"] = items["kWh/month"].apply(lambda k: core.saving_rm(month_kwh, k, tariff))
    st.metric("Estimated total saving", f"RM {core.saving_rm(month_kwh, total, tariff):.2f}/month", f"{total:.0f} kWh")
    a, b = st.columns(2)
    a.plotly_chart(tidy(px.bar(items.sort_values("RM/month"), x="RM/month", y="Action", orientation="h", color_discrete_sequence=[GREEN])), use_container_width=True)
    b.plotly_chart(tidy(go.Figure(go.Bar(x=["Current pace", "With changes"], y=[core.bill(month_kwh, tariff), core.bill(month_kwh - total, tariff)], marker_color=["#9BD3B5", GREEN])).update_layout(title="Projected monthly bill (RM)")), use_container_width=True)
    st.dataframe(items.sort_values("RM/month", ascending=False).round(2), hide_index=True, use_container_width=True)

else:
    st.title("Sustainability")
    f = st.number_input("Emission factor (kg CO2e per kWh)", value=core.GRID_KG_PER_KWH, step=0.01,
                        help="Placeholder. Replace with an official grid factor before reporting carbon figures.")
    c = st.columns(3)
    c[0].metric("Emissions this month", f"{cur.kwh.sum()*f:.0f} kg CO2e")
    c[1].metric("Avoidable if flagged issues fixed", f"{flagged.extra_month_kwh.sum()*f:.0f} kg/month")
    c[2].metric("Avoidable energy", f"{flagged.extra_month_kwh.sum():.0f} kWh/month")
    mon = df.groupby([df.date.dt.to_period("M").astype(str), "appliance"]).kwh.sum().reset_index()
    st.plotly_chart(tidy(px.bar(mon, x="date", y="kwh", color="appliance", color_discrete_sequence=PAL, labels={"date": "Month"})), use_container_width=True)
    st.caption("Estimates only; the first and latest months may be partial.")
