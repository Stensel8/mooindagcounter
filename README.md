# Mooindagcounter

Mooindag! FastAPI-teller, draait op Bunny.net Magic Containers.

## Twee varianten

Twee complete deployment-varianten van dezelfde app. `web/app.py`, de
templates en static zijn **byte-voor-byte identiek** (CI dwingt dit af);
het enige codeverschil is de datalaag `web/db.py`.

| | [`microservices/`](microservices/) | [`bunny-libsql/`](bunny-libsql/) |
|---|---|---|
| Database | MariaDB (zelf gehost) | [Bunny Database](https://bunny.net/database/) (managed, libSQL) |
| Containers | web + db | alleen web |
| Draait op | docker compose, Kubernetes, Bunny (2 apps) | Bunny Magic Containers |
| Kosten database | ~$4/maand | ~$0 (usage-based) |

**Keuzehulp:** zelf een database willen beheren of op Kubernetes draaien
(leerzaam!) → `microservices/`. Nul beheer en wereldwijd snelle reads →
`bunny-libsql/`.

**Waarom deze opzet:** een database-sidecar per pod betekent op Bunny één
database per regio met elk een eigen volume — dus een andere teller per
refresh, een lege teller na opschalen en InnoDB-crashes bij afschalen.
De regel is simpel: **web-laag stateless en vrij schaalbaar, de database op
precies 1 plek (of managed)**. Zie de README per variant voor het stappenplan.

Elke response bevat een `X-Served-By` header (regio + pod-ID) zodat je kunt
zien welke pod je bediende — handig om te checken dat alle regio's dezelfde
database zien.

## Routes

Identiek voor beide varianten. HTML gaat uit met `Cache-Control: no-store`
zodat CDN's en browsers nooit een oude tellerstand tonen.

| Route | Wat |
|---|---|
| `GET /` | Tellerstand + invoerformulier |
| `POST /increment` | Nieuw bericht (max 300 tekens, uniek); redirect naar `/` |
| `GET /overview` | Tabel met alle counts, met verwijderknop |
| `GET /api/counts` | Alle counts als JSON, nieuwste eerst |
| `GET /api/counts/{id}` | Eén count als JSON |
| `DELETE /api/counts/{id}` | Verwijdert een count (wachtwoord vereist, zie hieronder) |
| `GET /robots.txt` | Robots-regels |

## Verwijderen (wachtwoord)

Verwijderen vereist een wachtwoord dat **alleen via een secret** wordt
ingesteld: `DELETE_PASSWORD`. Zonder die variabele staat verwijderen uit.

De verwijderknop op `/overview` opent een wachtwoord-modal; de API verwacht
het wachtwoord in de `X-Delete-Password` header. Na één juist wachtwoord is
de browser **10 minuten vertrouwd** via een HMAC-getekende, HttpOnly cookie
— daarna vraagt de modal opnieuw. Het wachtwoord zelf wordt nergens
opgeslagen of gelogd.

```bash
curl -X DELETE https://mooindagcounter.nl/api/counts/15 \
  -H "X-Delete-Password: $DELETE_PASSWORD"
```

## Deployment

GitHub Actions pusht drie images naar GHCR onder de namespace van de
**repo-eigenaar** (`ghcr.io/<owner>/…`) — forks publiceren dus automatisch
naar hun eigen namespace:

| Image | Bron |
|---|---|
| `mooindag-web` | `microservices/web` |
| `mooindag-db` | `microservices/db` |
| `mooindag-libsql` | `bunny-libsql/web` |

- Push naar `main` → `latest` + `sha-…`; via *Actions → Build & Push → Run
  workflow* bouw je vanaf een branch (alleen `sha-…`).
- **Nieuwe GHCR-packages staan standaard op private**; zet ze op public
  (GitHub → Packages → Package settings) anders kan Bunny's "GitHub Public"
  registry ze niet pullen.
- Ander namespace op Kubernetes? Gebruik de `images:`-override in
  `microservices/k8s/kustomization.yaml`.
