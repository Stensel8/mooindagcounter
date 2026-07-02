"""
Eenmalige migratie van de MariaDB-database (microservices-variant) naar
Bunny Database (libSQL).

Kopieert alle rijen inclusief hun oorspronkelijke ID, zodat de tellerstand
(hoogste ID) exact gelijk blijft. Bestaande ID's in de doeldatabase worden
overgeslagen, dus het script is veilig om opnieuw te draaien.

Gebruik:
    pip install pymysql httpx

    DB_HOST=... DB_PORT=3306 DB_USER=mooindagcounter DB_PASSWORD=... \
    DB_NAME=mooindagcounter \
    LIBSQL_URL=libsql://<database-id>.lite.bunnydb.net \
    LIBSQL_AUTH_TOKEN=<token> \
    python3 migrate.py
"""

import os
import sys

import httpx
import pymysql

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS counts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    client_ip TEXT NOT NULL
)"""


def libsql_base_url() -> str:
    """Normaliseert LIBSQL_URL naar een http(s)-URL (zie ook web/app.py)."""
    url = os.environ["LIBSQL_URL"].strip().rstrip("/")
    for old, new in (("libsql://", "https://"), ("wss://", "https://"), ("ws://", "http://")):
        if url.startswith(old):
            return new + url.removeprefix(old)
    return url


def execute_pipeline(client: httpx.Client, statements: list[dict]) -> None:
    """Stuurt statements in 1 batch naar libSQL en stopt bij de eerste fout."""
    body = {"requests": [*statements, {"type": "close"}]}
    response = client.post("/v2/pipeline", json=body)
    response.raise_for_status()
    for result in response.json()["results"]:
        if result.get("type") != "ok":
            sys.exit(f"libSQL fout: {result.get('error', {}).get('message')}")


def text(value) -> dict:
    return {"type": "text", "value": str(value)}


def main() -> None:
    connection = pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.getenv("DB_NAME", "mooindagcounter"),
        cursorclass=pymysql.cursors.DictCursor,
    )
    with connection, connection.cursor() as cursor:
        cursor.execute("SELECT id, message, date, time, client_ip FROM counts ORDER BY id")
        rows = cursor.fetchall()
    print(f"{len(rows)} rijen gelezen uit MariaDB")

    token = os.getenv("LIBSQL_AUTH_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(base_url=libsql_base_url(), headers=headers, timeout=30) as client:
        statements = [{"type": "execute", "stmt": {"sql": SCHEMA_SQL, "args": []}}]
        for row in rows:
            statements.append({
                "type": "execute",
                "stmt": {
                    # OR IGNORE: rijen die al bestaan (zelfde ID) worden overgeslagen.
                    "sql": (
                        "INSERT OR IGNORE INTO counts "
                        "(id, message, date, time, client_ip) VALUES (?, ?, ?, ?, ?)"
                    ),
                    "args": [
                        {"type": "integer", "value": str(row["id"])},
                        text(row["message"]),
                        text(row["date"]),
                        text(row["time"]),
                        text(row["client_ip"]),
                    ],
                },
            })
        execute_pipeline(client, statements)
    print(f"Klaar: {len(rows)} rijen gemigreerd naar libSQL (bestaande ID's overgeslagen)")


if __name__ == "__main__":
    main()
