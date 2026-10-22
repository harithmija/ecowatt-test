"""Account and session storage for the EcoWatt web app."""
import hashlib
import hmac
import secrets
import sqlite3
import time

import core

PASSWORD_ITERATIONS = 600_000
SESSION_SECONDS = 7 * 24 * 60 * 60


def _connect():
    db = sqlite3.connect(core.DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    with _connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS accounts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role = 'resident'),
            password_hash TEXT NOT NULL,
            google_sub TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS web_sessions(
            token_hash TEXT PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            expires_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS google_login_nonces(
            nonce_hash TEXT PRIMARY KEY,
            expires_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_web_sessions_expiry ON web_sessions(expires_at);
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(accounts)")}
        if "google_sub" not in columns:
            db.execute("ALTER TABLE accounts ADD COLUMN google_sub TEXT")
            db.execute("CREATE UNIQUE INDEX ix_accounts_google_sub ON accounts(google_sub)")


def _password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password, encoded):
    try:
        algorithm, rounds, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _user(row):
    if row is None:
        return None
    return {"id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"]}


def create_account(email, name, role, password):
    with _connect() as db:
        cursor = db.execute(
            "INSERT INTO accounts(email, name, role, password_hash) VALUES(?,?,?,?)",
            (email, name, role, _password_hash(password)),
        )
        row = db.execute(
            "SELECT id, email, name, role FROM accounts WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return _user(row)


def authenticate(email, password):
    with _connect() as db:
        row = db.execute(
            "SELECT id, email, name, role, password_hash FROM accounts WHERE email = ? COLLATE NOCASE",
            (email,),
        ).fetchone()
    if row is None or not _verify_password(password, row["password_hash"]):
        return None
    return _user(row)


def authenticate_google(subject, email, name):
    with _connect() as db:
        row = db.execute(
            "SELECT id, email, name, role FROM accounts WHERE google_sub = ?",
            (subject,),
        ).fetchone()
        if row is not None:
            return _user(row)

        row = db.execute(
            "SELECT id, email, name, role, google_sub FROM accounts WHERE email = ? COLLATE NOCASE",
            (email,),
        ).fetchone()
        if row is not None:
            if row["google_sub"] is not None:
                raise ValueError("This email is already linked to another Google account")
            db.execute("UPDATE accounts SET google_sub = ? WHERE id = ?", (subject, row["id"]))
            return _user(row)

        cursor = db.execute(
            """INSERT INTO accounts(email, name, role, password_hash, google_sub)
               VALUES(?, ?, 'resident', ?, ?)""",
            (email, name, _password_hash(secrets.token_urlsafe(48)), subject),
        )
        row = db.execute(
            "SELECT id, email, name, role FROM accounts WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _user(row)


def create_session(account_id):
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    now = time.time()
    with _connect() as db:
        db.execute("DELETE FROM web_sessions WHERE expires_at <= ?", (now,))
        db.execute(
            "INSERT INTO web_sessions(token_hash, account_id, expires_at) VALUES(?,?,?)",
            (token_hash, account_id, now + SESSION_SECONDS),
        )
    return token


def session_user(token):
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    with _connect() as db:
        row = db.execute(
            """SELECT a.id, a.email, a.name, a.role
               FROM web_sessions s JOIN accounts a ON a.id = s.account_id
               WHERE s.token_hash = ? AND s.expires_at > ?""",
            (token_hash, time.time()),
        ).fetchone()
    return _user(row)


def delete_session(token):
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    with _connect() as db:
        db.execute("DELETE FROM web_sessions WHERE token_hash = ?", (token_hash,))


def create_google_nonce():
    nonce = secrets.token_urlsafe(32)
    nonce_hash = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    now = time.time()
    with _connect() as db:
        db.execute("DELETE FROM google_login_nonces WHERE expires_at <= ?", (now,))
        db.execute(
            "INSERT INTO google_login_nonces(nonce_hash, expires_at) VALUES(?, ?)",
            (nonce_hash, now + 5 * 60),
        )
    return nonce


def consume_google_nonce(nonce):
    nonce_hash = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    with _connect() as db:
        cursor = db.execute(
            "DELETE FROM google_login_nonces WHERE nonce_hash = ? AND expires_at > ?",
            (nonce_hash, time.time()),
        )
        return cursor.rowcount == 1
