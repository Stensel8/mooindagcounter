"""
Datalaag: Bunny Database (libSQL) via Hrana-over-HTTP.

Dit bestand is het enige codeverschil tussen de twee varianten in deze repo:
web/app.py is identiek, alleen de datalaag (web/db.py) verschilt. Beide
varianten bieden dezelfde functies aan: startup/shutdown/ping en de
domeinfuncties voor het lezen en schrijven van counts.

Bunny Database spreekt het standaard libSQL/sqld "Hrana over HTTP" protocol:
statements gaan als JSON naar POST {LIBSQL_URL}/v2/pipeline met een Bearer
token — precies wat Bunny's eigen client-libraries ook doen. Er is geen
officiele Python SDK, maar het protocol is klein genoeg om hier direct met
httpx te spreken, zonder extra dependencies.
"""

import base64
import logging
import os

import httpx

logger = logging.getLogger("uvicorn.error")

# Schema wordt door de app zelf aangemaakt als het nog niet bestaat (SQLite-
# dialect). AUTOINCREMENT garandeert dat verwijderde ID's nooit hergebruikt
# worden, zodat de teller (hoogste ID) nooit terugloopt door een delete.
SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS counts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    client_ip TEXT NOT NULL
)"""

# Gedeelde HTTP-client met connection pooling; aangemaakt in startup().
_client: httpx.AsyncClient | None = None

# Of de counts-tabel bevestigd bestaat. Zolang dat niet zo is, wordt de
# CREATE TABLE bij elk request opnieuw geprobeerd: Bunny Database spint
# down bij inactiviteit, dus de database kan tijdens het opstarten van de
# app nog onbereikbaar zijn geweest.
_schema_ready = False


def _base_url() -> str:
    """
    Normaliseert de database-URL naar een http(s)-URL.
    Leest LIBSQL_URL, of BUNNY_DATABASE_URL — de naam die Bunny's
    "Add Secrets to Magic Container App" knop automatisch injecteert.
    Bunny geeft URL's in de vorm libsql://<id>.lite.bunnydb.net; dat is
    hetzelfde endpoint over HTTPS. Voor lokale ontwikkeling met sqld
    (docker compose) is het http://db:8080.
    """
    url = (
        os.getenv("LIBSQL_URL") 
        or os.getenv("BUNNY_DATABASE_URL") 
        or "http://localhost:8080"
    ).strip().rstrip("/")
    
    # Debug: log welke variabelen beschikbaar zijn
    logger.info("DB URL bron: LIBSQL_URL=%s, BUNNY_DATABASE_URL=%s, gekozen=%s", 
                bool(os.getenv("LIBSQL_URL")), 
                bool(os.getenv("BUNNY_DATABASE_URL")), 
                url)
    
    for old, new in (("libsql://", "https://"), ("wss://", "https://"), ("ws://", "http://")):
        if url.startswith(old):
            return new + url.removeprefix(old)
    return url


def _auth_headers() -> dict:
    """
    Bearer-token voor de database. Leest LIBSQL_AUTH_TOKEN, of
    BUNNY_DATABASE_AUTH_TOKEN (automatisch geinjecteerd door Bunny's
    "Add Secrets" knop; de app schrijft, dus niet het READ_ONLY-token).
    Leeg bij een lokale sqld zonder auth.
    """
    token = (
        os.getenv("LIBSQL_AUTH_TOKEN") 
        or os.getenv("BUNNY_DATABASE_AUTH_TOKEN") 
        or ""
    ).strip()
    
    # Debug: log of token aanwezig is
    logger.info("DB Auth: LIBSQL_AUTH_TOKEN=%s, BUNNY_DATABASE_AUTH_TOKEN=%s, has_token=%s", 
                bool(os.getenv("LIBSQL_AUTH_TOKEN")), 
                bool(os.getenv("BUNNY_DATABASE_AUTH_TOKEN")), 
                bool(token))
    
    return {"Authorization": f"Bearer {token}"} if token else {}


def _encode_arg(value) -> dict:
    """Zet een Python-waarde om naar een Hrana-waarde voor query-parameters."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode()}
    return {"type": "text", "value": str(value)}


def _decode_value(cell: dict):
    """Zet een Hrana-waarde uit een resultaat om naar een Python-waarde."""
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "blob":
        return base64.b64decode(cell["base64"])
    return cell.get("value")


async def _pipeline(sql: str, params: tuple = ()) -> dict | None:
    """
    Voert een statement uit via Hrana-over-HTTP en geeft het ruwe resultaat
    terug (cols/rows/affected_row_count/last_insert_rowid), of None bij een
    fout of onbereikbare database.
    """
    if _client is None:
        return None
    body = {
        "requests": [
            {
                "type": "execute",
                "stmt": {"sql": sql, "args": [_encode_arg(p) for p in params]},
            },
            {"type": "close"},
        ]
    }
    try:
        response = await _client.post("/v2/pipeline", json=body)
        response.raise_for_status()
        result = response.json()["results"][0]
        if result.get("type") != "ok":
            logger.error("libSQL fout: %s", result.get("error", {}).get("message"))
            return None
        return result["response"]["result"]
    except Exception as e:
        logger.error("libSQL request mislukt: %s", e)
        return None


async def _ensure_schema() -> None:
    """Maakt de counts-tabel aan als die nog niet bestaat (eenmalig bij succes)."""
    global _schema_ready
    if _schema_ready:
        return
    if await _pipeline(SCHEMA_SQL) is not None:
        _schema_ready = True
    else:
        logger.warning("Schema-controle mislukt; database mogelijk (nog) niet bereikbaar")


async def startup() -> None:
    """Opent de gedeelde HTTP-client en maakt het schema aan als dat nog niet bestaat."""
    global _client
    base = _base_url()
    headers = _auth_headers()
    
    logger.info("DB startup: base_url=%s, headers=%s", base, {k: v[:10] + "..." if v else "" for k, v in headers.items()})
    
    _client = httpx.AsyncClient(
        base_url=base,
        headers=headers,
        timeout=httpx.Timeout(30.0),
        # Retry op verbindingsfouten: een remote database over internet heeft
        # af en toe een haperende verbinding; dit vangt dat stilletjes op.
        transport=httpx.AsyncHTTPTransport(retries=2),
    )
    await _ensure_schema()


async def shutdown() -> None:
    """Sluit de HTTP-client netjes af bij het stoppen van de applicatie."""
    if _client is not None:
        await _client.aclose()


async def _query(sql: str, params: tuple = ()) -> list | None:
    """
    Voert een SELECT-query uit en geeft alle rijen terug als lijst van dicts.
    Geeft None terug bij een DB-fout of onbereikbare DB.
    """
    await _ensure_schema()
    result = await _pipeline(sql, params)
    if result is None:
        return None
    names = [col.get("name") for col in result.get("cols", [])]
    return [
        dict(zip(names, (_decode_value(cell) for cell in row)))
        for row in result.get("rows", [])
    ]


async def _execute(sql: str, params: tuple = ()) -> bool:
    """Voert een niet-SELECT statement uit. Geeft True terug bij succes."""
    await _ensure_schema()
    return await _pipeline(sql, params) is not None


async def _insert(sql: str, params: tuple = ()) -> int | None:
    """Voert een INSERT uit en geeft het nieuwe rij-ID terug."""
    await _ensure_schema()
    result = await _pipeline(sql, params)
    if result is None or result.get("last_insert_rowid") is None:
        return None
    return int(result["last_insert_rowid"])


# --- Domeinfuncties (identieke interface in beide varianten) --- Mooindag!

async def ping() -> bool:
    """Controleert of de database bereikbaar is (voor /healthz)."""
    return await _query("SELECT 1") is not None


async def save_counter(message: str, date, time, client_ip: str) -> int | None:
    """Sla een nieuwe count op en geef het automatisch toegewezen ID terug."""
    return await _insert(
        "INSERT INTO counts (message, date, time, client_ip) VALUES (?, ?, ?, ?)",
        (message, str(date), str(time), client_ip),
    )


async def get_counter(entry_id: int) -> dict | None:
    """Haal een specifieke count op via ID, of None als die niet bestaat."""
    rows = await _query("SELECT * FROM counts WHERE id = ?", (entry_id,))
    return rows[0] if rows else None


async def get_all_counters() -> list | None:
    """Haal alle counts op, gesorteerd van nieuwste naar oudste."""
    return await _query("SELECT id, message, date, time FROM counts ORDER BY id DESC")


async def get_latest_counter() -> int | None:
    """
    Geeft de huidige tellerstand terug: het hoogste ID in de tabel.
    Geeft 0 terug als de tabel leeg is, None als de DB niet bereikbaar is.
    """
    rows = await _query("SELECT id FROM counts ORDER BY id DESC LIMIT 1")
    if rows is None:
        return None
    return rows[0]["id"] if rows else 0


async def message_exists(message: str) -> bool:
    """Controleert of een bericht al eerder is ingevoerd (duplicaatbeveiliging)."""
    rows = await _query("SELECT 1 FROM counts WHERE message = ? LIMIT 1", (message,))
    return bool(rows)


async def delete_counter(entry_id: int) -> bool:
    """Verwijdert een count. Geeft True terug bij succes."""
    return await _execute("DELETE FROM counts WHERE id = ?", (entry_id,))
