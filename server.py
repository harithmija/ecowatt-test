"""EcoWatt AI web server. Run: uvicorn server:app --reload"""
import logging, math, os, time
from datetime import datetime
import hmac
import re
import sqlite3
import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
import auth, core
import friendly_features
from config import GEMINI_API_KEY, GRID_KG_PER_KWH as EF

HERE = os.path.dirname(__file__)
app = FastAPI(title="EcoWatt AI")
cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5000,http://127.0.0.1:5000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
logger = logging.getLogger(__name__)
core.init_db()
auth.init_db()
_c = {"t": 0, "df": None}
SESSION_COOKIE = "ecowatt_session"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()


class Signup(BaseModel):
    name: str = Field(max_length=80)
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)


class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class GoogleCredential(BaseModel):
    credential: str = Field(min_length=1, max_length=10000)
    nonce: str = Field(min_length=1, max_length=200)


def require_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    user = auth.session_user(token) if token else None
    if user is None:
        raise HTTPException(401, "Please sign in to continue")
    return user


def require_role(role):
    def check_role(user=Depends(require_user)):
        if user["role"] != role:
            raise HTTPException(403, "This account does not have access to this page")
        return user
    return check_role


def set_session_cookie(response, user):
    token = auth.create_session(user["id"])
    response.set_cookie(
        SESSION_COOKIE, token, max_age=auth.SESSION_SECONDS, httponly=True,
        secure=COOKIE_SECURE, samesite="strict", path="/",
    )


@app.post("/api/auth/signup", status_code=201)
def signup(account: Signup, response: Response):
    name, email = account.name.strip(), account.email.strip().lower()
    if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Enter a name and a valid email")
    try:
        user = auth.create_account(email, name, "resident", account.password)
    except sqlite3.IntegrityError as exc:
        if "accounts.email" in str(exc):
            raise HTTPException(409, "An account with that email already exists") from exc
        raise
    set_session_cookie(response, user)
    return {"user": user}


@app.post("/api/auth/login")
def login(credentials: Login, response: Response):
    user = auth.authenticate(credentials.email.strip(), credentials.password)
    if user is None or user["role"] != "resident":
        raise HTTPException(401, "Email or password is incorrect")
    set_session_cookie(response, user)
    return {"user": user}


@app.get("/api/auth/config")
def auth_config():
    return {"google_client_id": GOOGLE_CLIENT_ID or None}


@app.post("/api/auth/google/nonce")
def google_login_nonce():
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Google sign-in is not configured")
    return {"nonce": auth.create_google_nonce()}


@app.post("/api/auth/google")
def google_login(credentials: GoogleCredential, response: Response):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Google sign-in is not configured")
    try:
        claims = id_token.verify_oauth2_token(
            credentials.credential, GoogleRequest(), GOOGLE_CLIENT_ID
        )
    except (ValueError, GoogleAuthError) as exc:
        raise HTTPException(401, "Google sign-in could not be verified") from exc
    token_nonce = claims.get("nonce", "")
    if not token_nonce or not hmac.compare_digest(token_nonce, credentials.nonce):
        raise HTTPException(401, "Google sign-in could not be verified")
    if not auth.consume_google_nonce(credentials.nonce):
        raise HTTPException(401, "Google sign-in expired or was already used; please try again")
    email = claims.get("email", "")
    subject = claims.get("sub", "")
    name = claims.get("name") or email.split("@", 1)[0]
    if claims.get("email_verified") is not True or not subject or not email:
        raise HTTPException(401, "Google must provide a verified email")
    try:
        user = auth.authenticate_google(subject, email.strip().lower(), name.strip())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "This Google account could not be linked") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    set_session_cookie(response, user)
    return {"user": user}


@app.get("/api/auth/me")
def who_am_i(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    user = auth.session_user(token) if token else None
    if user and user["role"] != "resident":
        auth.delete_session(token)
        user = None
    return {"user": user}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth.delete_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=COOKIE_SECURE, samesite="strict")
    return {"ok": True}


def data():
    if time.time() - _c["t"] > 30:
        _c["df"], _c["t"] = core.load_readings(), time.time()
    return _c["df"]


def invalidate_data():
    _c["t"] = 0
    _c["df"] = None


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
def overview(user=Depends(require_role("resident"))):
    df, last, cur, proj, st = ctx()
    fl = st[st.status.isin(["abnormal", "high"])].sort_values("extra_month_rm", ascending=False)
    t30 = df[df.date > last - pd.Timedelta(days=30)].groupby(["date", "appliance"]).kwh.sum().unstack().fillna(0)
    action_cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=7)
    action_impacts = []
    for action in core.load_actions().itertuples():
        action_ts = pd.Timestamp(action.ts)
        if action_ts < action_cutoff or not action.action_id:
            continue
        before, after, days_after = core.review_action(df, action.appliance, action.ts)
        before_dates = df.loc[
            (df.appliance == action.appliance)
            & (df.date < action_ts.normalize()),
            "date",
        ].drop_duplicates().sort_values().tail(7)
        before_readings = df[
            (df.appliance == action.appliance)
            & df.date.isin(before_dates)
        ]
        after_readings = df[
            (df.appliance == action.appliance)
            & (df.date > action_ts.normalize())
        ]
        action_impacts.append(dict(
            ts=action.ts,
            appliance=action.appliance,
            note=action.note,
            days_after=days_after,
            before_kwh=before,
            after_kwh=after,
            reduction_kwh=before - after if days_after and pd.notna(before) and pd.notna(after) else None,
            reduction_pct=(before - after) / before * 100
            if days_after and pd.notna(before) and before > 0 and pd.notna(after) else None,
            simulated=bool(
                not before_readings.empty
                and not after_readings.empty
                and (before_readings.source == "simulated").all()
                and (after_readings.source == "simulated").all()
            ),
        ))
    return clean(dict(
        month=last.strftime("%B %Y"), day=last.day, days=last.days_in_month,
        kwh=cur.kwh.sum(), bill=core.bill(cur.kwh.sum()), proj_kwh=proj, proj_bill=core.bill(proj),
        savings=fl.extra_month_rm.sum(), simulated=bool((df.source == "simulated").all()),
        by_appliance=cur.groupby("appliance").kwh.sum().to_dict(),
        trend=dict(dates=list(t30.index), series={c: list(t30[c]) for c in t30}),
        action_impacts=action_impacts,
        alerts=[dict(appliance=r.appliance, status=r.status, why=r.why, rec=core.RECS[r.appliance], rm=r.extra_month_rm) for r in fl.itertuples()]))


@app.get("/api/months")
def months(user=Depends(require_role("resident"))):
    return sorted(df_m for df_m in data().date.dt.strftime("%Y-%m").unique())[::-1]


@app.get("/api/monthly")
def monthly(month: str, user=Depends(require_role("resident"))):
    df, last, *_ = ctx()
    d = df[df.date.dt.strftime("%Y-%m") == month]
    if d.empty:
        raise HTTPException(404, "No data for that month")
    report = d.assign(category=d.appliance.map(
        lambda name: "Lights" if name.lower().endswith("lights")
        else "Fans" if name.lower().endswith("fan")
        else name
    ))
    daily = report.groupby(["date", "category"]).kwh.sum().unstack().fillna(0)
    dd = daily.sum(axis=1)
    hm = d.groupby(["hour", "date"]).kwh.sum().unstack().fillna(0)
    tot = d.kwh.sum()
    return clean(dict(
        total=tot, bill=core.bill(tot), avg=dd.mean(), peak_day=dd.idxmax(), peak_kwh=dd.max(),
        top=report.groupby("category").kwh.sum().idxmax(), partial=month == last.strftime("%Y-%m"), days_recorded=len(dd),
        simulated=bool((d.source == "simulated").all()),
        dates=list(daily.index), series={c: list(daily[c]) for c in daily}, cum_rm=[core.bill(k) for k in dd.cumsum()],
        heat=dict(x=list(hm.columns), y=list(hm.index), z=hm.values.tolist()),
        breakdown=core.tier_rows(tot).to_dict("records"),
        table=[dict(date=i, **{c: round(r[c], 2) for c in daily.columns}, total=round(r.sum(), 2)) for i, r in daily.iterrows()]))


@app.get("/api/appliances")
def appliances(user=Depends(require_role("resident"))):
    df, last, cur, proj, st = ctx()
    out = []
    for name, w, room in core.APPLIANCES.values():
        a, r = df[df.appliance == name], st[st.appliance == name].iloc[0]
        d = a.groupby("date").kwh.sum().tail(30)
        projected_appliance_kwh = cur[cur.appliance == name].kwh.sum() / last.day * last.days_in_month
        out.append(dict(name=name, room=room, rated_w=w, power_w=a.sort_values("ts").power_w.iloc[-1],
                        month_kwh=cur[cur.appliance == name].kwh.sum(), status=r.status, baseline=r.baseline, recent=r.recent,
                        pct=r.pct, why=r.why, rec=core.RECS[name], extra_rm=r.extra_month_rm, dates=list(d.index), kwh=list(d.values),
                        actions=core.action_estimates(name, projected_appliance_kwh, proj)))
    return clean(out)


class Act(BaseModel):
    appliance: str = Field(min_length=1, max_length=100)
    action_id: str | None = None
    note: str | None = Field(default=None, max_length=200)


@app.post("/api/actions")
def add_action(a: Act, user=Depends(require_role("resident"))):
    if a.appliance not in [v[0] for v in core.APPLIANCES.values()]:
        raise HTTPException(400, "Invalid action")
    if a.action_id:
        df, last, cur, proj, _ = ctx()
        appliance_kwh = cur[cur.appliance == a.appliance].kwh.sum() / last.day * last.days_in_month
        estimate = next(
            (item for item in core.action_estimates(a.appliance, appliance_kwh, proj)
             if item["id"] == a.action_id),
            None,
        )
        if estimate is None:
            raise HTTPException(400, "Choose a recommended action for this appliance")
        core.add_action(
            a.appliance,
            estimate["label"],
            action_id=estimate["id"],
            estimated_kwh=estimate["estimated_kwh"],
            estimated_rm=estimate["estimated_rm"],
        )
        invalidate_data()
        return {"ok": True, "estimate": estimate}
    if not a.note or not a.note.strip():
        raise HTTPException(400, "Choose a recommended action or enter an action note")
    core.add_action(a.appliance, a.note.strip()[:200])
    invalidate_data()
    return {"ok": True}


@app.get("/api/actions")
def actions(user=Depends(require_role("resident"))):
    df, acts, out = data(), core.load_actions(), []
    for x in acts.itertuples():
        b, a, n = core.review_action(df, x.appliance, x.ts)
        out.append(dict(
            ts=x.ts,
            appliance=x.appliance,
            note=x.note,
            action_id=x.action_id,
            before=b,
            after=a,
            days_after=n,
            estimated_kwh=x.estimated_kwh,
            estimated_rm=x.estimated_rm,
        ))
    return clean(out)


class Q(BaseModel):
    question: str


@app.post("/api/chat")
def chat(q: Q, user=Depends(require_role("resident"))):
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
def simulate(hours: float = 1, setpoint: int = 1, heater: int = 20, user=Depends(require_role("resident"))):
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
def sustainability(user=Depends(require_role("resident"))):
    df, last, cur, proj, st = ctx()
    prev = df[df.date.dt.to_period("M") == last.to_period("M") - 1].kwh.sum() * EF
    kg = proj * EF
    fl = st[st.status.isin(["abnormal", "high"])].sort_values("extra_month_kwh", ascending=False)
    mon = df.groupby(df.date.dt.strftime("%Y-%m")).kwh.sum() * EF
    return clean(dict(kg=kg, prev=prev, change=(kg / prev - 1) if prev else None, km=kg / 0.17, trees=kg / 21, ef=EF,
                      wins=[dict(appliance=r.appliance, rec=core.RECS[r.appliance], rm=r.extra_month_rm, kg=r.extra_month_kwh * EF) for r in fl.itertuples()],
                      months=list(mon.index), month_kg=list(mon.values)))


friendly_features.register(app, data, ctx, clean, invalidate_data, require_role("resident"))


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))
