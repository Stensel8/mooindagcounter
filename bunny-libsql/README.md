# Bunny Database-variant (libSQL)

FastAPI-teller met [Bunny Database](https://bunny.net/database/) als managed
datalaag. Eén stateless container — geen database-container, geen volumes,
geen InnoDB, niets om te beheren. Bunny repliceert de data automatisch naar
de regio's waar je app draait, dus reads komen altijd uit de buurt.

## Hoe het werkt

Bunny Database is gebouwd op libSQL (een SQLite-fork) en spreekt het standaard
*Hrana over HTTP* protocol: statements gaan als JSON naar
`POST {LIBSQL_URL}/v2/pipeline` met een Bearer-token — precies wat Bunny's
eigen client-libraries ook doen. Er is geen officiële Python SDK, dus
`web/app.py` spreekt dat protocol direct via `httpx` (~80 regels, geen extra
dependencies).

## Deployment op Bunny.net

1. **Maak een database aan** in het [Bunny dashboard](https://dash.bunny.net)
   (Database → Add Database). Kies als primaire regio waar je meeste bezoekers
   zitten (bijv. Amsterdam) en voeg replica-regio's toe waar je app draait.
2. Kopieer de **URL** (`libsql://<id>.lite.bunnydb.net`) en maak een
   **access token** aan (Database → Connect).
3. Pas je Magic Containers app aan: **alleen** het `mooindagcounter-libsql`
   image (verwijder de db-container en het volume) met deze env-variabelen:
   - `LIBSQL_URL=libsql://<id>.lite.bunnydb.net`
   - `LIBSQL_AUTH_TOKEN=<token>`
4. Zet multi-region en autoscaling zo ruim als je wilt — de app is volledig
   stateless, dus elke pod in elke regio ziet dezelfde teller.

De app maakt de `counts`-tabel zelf aan bij de eerste start.

## Data migreren vanuit MariaDB

`migrate.py` kopieert alle rijen inclusief hun oorspronkelijke ID (de
tellerstand blijft dus exact gelijk) en is veilig om opnieuw te draaien:

```bash
pip install pymysql httpx

DB_HOST=<mariadb-host> DB_USER=mooindagcounter DB_PASSWORD=... \
LIBSQL_URL=libsql://<id>.lite.bunnydb.net LIBSQL_AUTH_TOKEN=<token> \
python3 migrate.py
```

## Lokaal draaien

In productie is er geen database-container, maar lokaal wil je niet tegen de
echte Bunny Database ontwikkelen. De docker-compose start daarom
[sqld](https://github.com/tursodatabase/libsql) — de open-source libSQL-server
waar Bunny Database op gebaseerd is — als drop-in vervanger:

```bash
docker compose up --build
```

App draait op `http://localhost:8080`.

## Omgevingsvariabelen

| Variabele | Standaard | Omschrijving |
|---|---|---|
| `LIBSQL_URL` | `http://localhost:8080` | Database-URL (`libsql://…` van Bunny of `http://…` lokaal) |
| `LIBSQL_AUTH_TOKEN` | _(leeg)_ | Access token uit het Bunny dashboard; leeg bij lokale sqld |
| `DISCORD_WEBHOOK_URL` | _(leeg)_ | Optioneel: Discord meldingen |
| `GUNICORN_WORKERS` | `2` | Aantal Gunicorn+Uvicorn workers |

## Database

Tabel `counts` (SQLite-dialect). `AUTOINCREMENT` garandeert dat verwijderde
ID's nooit hergebruikt worden, zodat de teller nooit terugloopt.

| Kolom | Type |
|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT |
| `message` | TEXT NOT NULL |
| `date` | TEXT NOT NULL |
| `time` | TEXT NOT NULL |
| `client_ip` | TEXT NOT NULL |

## Kosten & kanttekeningen

- $0.30 per **miljard** gelezen rijen, $0.30 per miljoen geschreven rijen,
  $0.10/GB opslag per actieve regio; de database spint down bij inactiviteit.
  Voor dit project: afgerond **$0/maand**. Tijdens de public preview is de
  dienst helemaal gratis.
- Bunny Database is **public preview**: geen SLA en de dienst kan nog
  veranderen. Een periodieke export (bijv. `curl /api/counts > backup.json`)
  is een prima vangnet voor dit project.
- Writes gaan naar de primaire regio; reads komen uit de dichtstbijzijnde
  replica. Voor een teller is die (milliseconden-)vertraging irrelevant.
