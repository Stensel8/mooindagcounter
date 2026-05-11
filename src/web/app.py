from flask import Flask, render_template, request, redirect, url_for, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import threading
import requests
from dotenv import load_dotenv
import pymysql
from pymysql.cursors import DictCursor
from dbutils.pooled_db import PooledDB
from werkzeug.exceptions import HTTPException

app = Flask(__name__, static_folder="static")
load_dotenv("./.env")

AMS = ZoneInfo(os.getenv("TZ", "Europe/Amsterdam"))
MAX_MESSAGE_LENGTH = 300


# --- Verbindingspool ---

_pool: PooledDB | None = None
_pool_lock = threading.Lock()


def get_pool() -> PooledDB:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:  # dubbele check zodat de pool maar één keer aangemaakt wordt
                _pool = PooledDB(
                    creator=pymysql,
                    maxconnections=10,
                    mincached=2,
                    host=os.getenv("DB_HOST", "localhost"),
                    port=int(os.getenv("DB_PORT", "3306")),
                    user=os.getenv("DB_USER", "root"),
                    password=os.getenv("DB_PASSWORD", ""),
                    database=os.getenv("DB_NAME", "mooindagcounter"),
                    cursorclass=DictCursor,
                    autocommit=True,
                )
    return _pool


def get_connection():
    return get_pool().connection()


# Mooindag... Pool alvast aanmaken zodat een verkeerde config gelijk opvalt.
with app.app_context():
    try:
        get_pool()
    except Exception as e:
        app.logger.warning("Could not initialise DB pool at startup: %s", e)


# --- Database hulpfuncties --- Mooindag!

def db_query(sql: str, params: tuple = ()) -> list | None:
    """SELECT uitvoeren en alle rijen teruggeven. None bij een DB-fout."""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as e:
        app.logger.error("DB query error: %s", e)
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def db_execute(sql: str, params: tuple = ()) -> bool:
    """Niet-SELECT statement uitvoeren. True als het lukt, False bij fout."""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, params)
        return True
    except Exception as e:
        app.logger.error("DB execute error: %s", e)
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def db_insert(sql: str, params: tuple = ()) -> int | None:
    """INSERT uitvoeren en het nieuwe rij-ID teruggeven. None bij fout."""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.lastrowid
    except Exception as e:
        app.logger.error("DB insert error: %s", e)
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# --- Foutafhandeling --- Mooindag...

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(e):
    app.logger.error("Unhandled 500: %s", e)
    return render_template("db_offline.html"), 500


@app.errorhandler(503)
def service_unavailable(e):
    return render_template("db_offline.html"), 503


@app.errorhandler(Exception)
def unhandled_exception(e):
    # HTTP-fouten hebben hun eigen handler hierboven.
    if isinstance(e, HTTPException):
        return e
    app.logger.exception("Unhandled exception: %s", e)
    return render_template("db_offline.html"), 500


# --- Applicatielogica --- Mooindag!

def push_to_discord(counter: int, message: str, timestamp: datetime) -> None:
    # Achtergrondthread zodat de response niet wacht op Discord.
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        return

    def _send() -> None:
        try:
            requests.post(
                url,
                json={
                    "content": (
                        f"Counter: {counter}\n"
                        f"Datum: {timestamp.strftime('%d-%m-%Y')}\n"
                        f"Tijd: {timestamp.strftime('%H:%M')}\n"
                        f"{message.capitalize()}"
                    )
                },
                timeout=5,
            )
        except requests.RequestException as e:
            app.logger.warning("Discord webhook failed: %s", e)

    threading.Thread(target=_send, daemon=True).start()


def get_client_ip() -> str:
    # X-Forwarded-For kan een keten van IPs bevatten; de eerste is de echte afzender.
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "unknown"


def save_counter(message: str, date, time, client_ip: str) -> int | None:
    """Nieuwe count opslaan en het automatisch toegewezen ID teruggeven. None bij fout."""
    return db_insert(
        "INSERT INTO counts (message, date, time, client_ip) VALUES (%s, %s, %s, %s)",
        (message, str(date), str(time), client_ip),
    )


def get_counter(entry_id: int) -> dict | None:
    rows = db_query("SELECT * FROM counts WHERE id = %s", (entry_id,))
    return rows[0] if rows else None


def get_all_counters() -> list | None:
    return db_query("SELECT id, message, date, time FROM counts ORDER BY id DESC")


def get_latest_counter() -> int | None:
    """Huidige tellerstand teruggeven (hoogste ID). None als de DB niet bereikbaar is."""
    rows = db_query("SELECT id FROM counts ORDER BY id DESC LIMIT 1")
    if rows is None:
        return None
    return rows[0]["id"] if rows else 0


def message_exists(message: str) -> bool:
    rows = db_query("SELECT 1 FROM counts WHERE message = %s LIMIT 1", (message,))
    return bool(rows)


# --- Routes --- Mooindag...

@app.route("/overview")
def overview():
    data = get_all_counters()
    if data is None:
        return render_template("db_offline.html"), 503
    return render_template("overview.html", data=data)


@app.route("/increment", methods=["POST"])
def increment():
    timestamp = datetime.now(tz=AMS)
    counter = get_latest_counter()
    if counter is None:
        return render_template("db_offline.html"), 503

    message = request.form.get("message", "").strip().lower()

    if not message:
        return render_template("index.html", counter=counter, error_message="empty")

    if len(message) > MAX_MESSAGE_LENGTH:
        return render_template("index.html", counter=counter, error_message="too_long")

    if message_exists(message):
        return render_template("index.html", counter=counter, error_message="duplicate")

    new_id = save_counter(
        message,
        timestamp.date(),
        timestamp.time().replace(microsecond=0),
        get_client_ip(),
    )
    if new_id is None:
        return render_template("db_offline.html"), 503

    push_to_discord(new_id, message, timestamp)
    return redirect(url_for("index"))


@app.route("/remove/<int:id>", methods=["POST"])
def remove_item(id: int):
    db_execute("DELETE FROM counts WHERE id = %s", (id,))
    return redirect(url_for("overview"))


@app.route("/robots.txt")
def robots_txt():
    from flask import send_from_directory
    return send_from_directory("static", "robots.txt", mimetype="text/plain")


@app.route("/")
def index():
    counter = get_latest_counter()
    if counter is None:
        return render_template("db_offline.html"), 503
    return render_template("index.html", counter=counter)


@app.route("/index")
def index_redirect():
    return redirect(url_for("index"))


@app.route("/healthz")
def healthz():
    rows = db_query("SELECT 1")
    if rows is not None:
        return jsonify({"status": "ok"}), 200
    return jsonify({"status": "db_unavailable"}), 503


@app.route("/api/counts", methods=["GET"])
def api_counts():
    counters = get_all_counters()
    if counters is None:
        return jsonify({"error": "Database unavailable"}), 503
    return jsonify(
        [{"count": c["id"], "message": c["message"], "date": c["date"]} for c in counters]
    )


@app.route("/api/counts/<int:id>", methods=["GET", "DELETE"])
def api_count(id: int):
    if request.method == "GET":
        entry = get_counter(id)
        return jsonify(entry) if entry else (jsonify({"error": "Not found"}), 404)

    ok = db_execute("DELETE FROM counts WHERE id = %s", (id,))
    if not ok:
        return jsonify({"error": "Database unavailable"}), 503
    return jsonify({"message": f"Record {id} deleted"}), 200


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8080)
