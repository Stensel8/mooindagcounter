# Mooindagcounter - Web

Mooindag! Flask-gebaseerde teller-app met MariaDB als backend.

## Structuur

- `app.py`: Flask-app en databaselaag
- `requirements.txt`: Python-afhankelijkheden
- `Dockerfile`: Container definitie voor `mooindagcounter-web`
- `.env.example`: Voorbeeld omgevingsvariabelen
- `templates/`: HTML-templates (Jinja2)
- `static/`: CSS, afbeeldingen, manifest, robots.txt

## Lokaal draaien

```bash
# Vanuit de repo root:
cp src/web/.env.example .env
# Vul je waarden in (in elk geval DB_PASSWORD)
docker compose up --build
```

App draait op `http://localhost:8080`.

## Omgevingsvariabelen

```
DB_HOST=localhost          # MariaDB hostnaam
DB_PORT=3306               # MariaDB poort
DB_USER=mooindagcounter    # DB gebruiker
DB_PASSWORD=               # DB wachtwoord (verplicht)
DB_NAME=mooindagcounter    # Databasenaam
DISCORD_WEBHOOK_URL=       # Optioneel: Discord meldingen
GUNICORN_WORKERS=2         # Aantal app workers
```

## Database

De app verwacht een `counts` tabel met de volgende kolommen:
- `id` (INT, AUTO_INCREMENT, PRIMARY KEY)
- `message` (TEXT)
- `date` (TEXT)
- `time` (TEXT)
- `client_ip` (TEXT)

Dit wordt automatisch aangemaakt via `src/db/create_db.sql` bij de eerste opstart.

## Routes

### Web UI
- `GET /` - Teller pagina
- `POST /increment` - Nieuwe count toevoegen (formulier)
- `GET /overview` - Overzicht van alle counts
- `POST /remove/<id>` - Count verwijderen (formulier)

### API (JSON)
- `GET /healthz` - Statuscheck
- `GET /api/counts` - Alle counts ophalen
- `GET /api/counts/<id>` - Eén count ophalen
- `DELETE /api/counts/<id>` - Count verwijderen

## Deployment

Het Docker image (`mooindagcounter-web`) wordt gebouwd vanuit deze map en gepusht naar GHCR via GitHub Actions. Combineer met het `mooindagcounter-db` image voor de database.
