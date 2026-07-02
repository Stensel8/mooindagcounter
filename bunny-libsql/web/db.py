"""
Datalaag: Bunny Database (libSQL) via Hrana-over-HTTP.

Enige codeverschil met de microservices-variant (MariaDB via aiomysql);
web/app.py is identiek. Bunny Database spreekt het standaard libSQL/sqld
protocol — statements als JSON naar POST /v2/pipeline met een Bearer-token —
dus dit bestand praat daar rechtstreeks mee via httpx (geen SDK nodig).
"""

import logging
import os

import httpx

logger = logging.getLogger("uvicorn.error")

# AUTOINCREMENT: verwijderde ID's worden nooit hergebruikt, dus de teller
# (hoogste ID) loopt nooit terug door een delete.
SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS counts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    client_ip TEXT NOT NULL
)"""

_client: httpx.AsyncClient | None = None
_schema_ready = False

# Korte, mensvriendelijke omschrijving van de laatste fout; app.py toont
# dit op de foutpagina zodat bezoekers zien wát er misgaat.
last_error: str | None = None


def _base_url() -> str | None:
    """BUNNY_DATABASE_URL of LIBSQL_URL, genormaliseerd naar http(s) voor httpx."""
    url = (os.getenv("BUNNY_DATABASE_URL") or os.getenv("LIBSQL_URL") or "").strip().rstrip("/")
    if not url:
        return None
    for old, new in (("libsql://", "https://"), ("wss://", "https://"), ("ws://", "http://")):
        if url.startswith(old):
            return new + url.removeprefix(old)
    return url


def _auth_headers() -> dict:
    token = (
        os.getenv("BUNNY_DATABASE_AUTH_TOKEN") or os.getenv("LIBSQL_AUTH_TOKEN") or ""
    ).strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _encode_arg(value) -> dict:
    if value is None:
        return {"type": "null"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    return {"type": "text", "value": str(value)}


def _decode_value(cell: dict):
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    return cell.get("value")


async def _pipeline(sql: str, params: tuple = ()) -> dict | None:
    """Voert 1 statement uit; geeft het ruwe resultaat terug, of None bij een fout."""
    global last_error
    if _client is None:
        last_error = "er is nog geen database ingesteld (BUNNY_DATABASE_URL ontbreekt)"
        return None
    body = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": [_encode_arg(p) for p in params]}},
            {"type": "close"},
        ]
    }
    try:
        response = await _client.post("/v2/pipeline", json=body)
        response.raise_for_status()
        result = response.json()["results"][0]
    except Exception as e:
        logger.error("Database niet bereikbaar (%s): %s", type(e).__name__, e)
        last_error = "de database is even niet bereikbaar"
        return None
    if result.get("type") != "ok":
        message = result.get("error", {}).get("message", "onbekende fout")
        logger.error("Database weigerde de query: %s | sql: %s", message, sql.split()[0])
        last_error = f"de database weigerde de opdracht ({message})"
        return None
    last_error = None
    return result["response"]["result"]


async def _ensure_schema() -> None:
    """
    Maakt de counts-tabel aan zodra de database bereikbaar is. Wordt per
    request opnieuw geprobeerd tot het lukt: Bunny Database spint down bij
    inactiviteit en kan bij het opstarten van de app nog slapen.
    """
    global _schema_ready
    if not _schema_ready and await _pipeline(SCHEMA_SQL) is not None:
        _schema_ready = True


async def startup() -> None:
    global _client
    base = _base_url()
    if base is None:
        logger.error("Geen database-URL: zet BUNNY_DATABASE_URL of LIBSQL_URL")
        return
    _client = httpx.AsyncClient(
        base_url=base,
        headers=_auth_headers(),
        # Ruime read-timeout: Bunny Database moet soms wakker worden. Korte
        # connect-timeout: een onbereikbare database mag geen 30s kosten.
        timeout=httpx.Timeout(30.0, connect=10.0),
        transport=httpx.AsyncHTTPTransport(retries=2),
    )
    await _ensure_schema()


async def shutdown() -> None:
    if _client is not None:
        await _client.aclose()


async def _query(sql: str, params: tuple = ()) -> list | None:
    """SELECT; geeft rijen als lijst van dicts, of None bij een fout."""
    await _ensure_schema()
    result = await _pipeline(sql, params)
    if result is None:
        return None
    names = [col.get("name") for col in result.get("cols", [])]
    return [
        dict(zip(names, (_decode_value(cell) for cell in row)))
        for row in result.get("rows", [])
    ]


# --- Domeinfuncties (identieke interface in beide varianten) --- Mooindag!

async def save_counter(message: str, date, time, client_ip: str) -> int | None:
    """Bewaart een nieuwe count; geeft het toegewezen ID terug."""
    await _ensure_schema()
    result = await _pipeline(
        "INSERT INTO counts (message, date, time, client_ip) VALUES (?, ?, ?, ?)",
        (message, str(date), str(time), client_ip),
    )
    if result is None or result.get("last_insert_rowid") is None:
        return None
    return int(result["last_insert_rowid"])


async def get_counter(entry_id: int) -> dict | None:
    rows = await _query("SELECT * FROM counts WHERE id = ?", (entry_id,))
    return rows[0] if rows else None


async def get_all_counters() -> list | None:
    return await _query("SELECT id, message, date, time FROM counts ORDER BY id DESC")


async def get_latest_counter() -> int | None:
    """Tellerstand = hoogste ID; 0 bij lege tabel, None bij een fout."""
    rows = await _query("SELECT id FROM counts ORDER BY id DESC LIMIT 1")
    if rows is None:
        return None
    return rows[0]["id"] if rows else 0


async def message_exists(message: str) -> bool:
    rows = await _query("SELECT 1 FROM counts WHERE message = ? LIMIT 1", (message,))
    return bool(rows)


async def delete_counter(entry_id: int) -> bool:
    await _ensure_schema()
    return await _pipeline("DELETE FROM counts WHERE id = ?", (entry_id,)) is not None
