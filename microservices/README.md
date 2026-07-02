# Microservices-variant (web + MariaDB)

FastAPI-teller met een zelf gehoste MariaDB. Twee containers, klassieke
microservices-architectuur: een stateless web-laag die vrij mag schalen en
**precies één** database-instantie met een volume.

## Lokaal draaien

Kopieer het env-bestand en vul je waarden in:

```bash
cp web/.env.example .env
```

Start de app vanuit deze map:

```bash
docker compose up --build
```

App draait op `http://localhost:8080`.

## Omgevingsvariabelen

| Variabele | Standaard | Omschrijving |
|---|---|---|
| `DB_HOST` | `localhost` | MariaDB hostnaam |
| `DB_PORT` | `3306` | MariaDB poort |
| `DB_USER` | `mooindagcounter` | DB gebruiker |
| `DB_PASSWORD` | _(verplicht)_ | DB wachtwoord |
| `DB_NAME` | `mooindagcounter` | Databasenaam |
| `DB_SSL` | `false` | TLS naar de database; zet aan zodra de DB niet op localhost draait |
| `DB_SSL_VERIFY` | `true` | Certificaatcontrole; `false` bij self-signed certificaten |
| `DB_SSL_CA` | _(leeg)_ | Pad naar CA-bundel (vereist door sommige managed diensten) |
| `DB_CONNECT_TIMEOUT` | `10` | Verbindingstimeout in seconden |
| `DB_POOL_RECYCLE` | `280` | Vernieuw idle poolverbindingen na dit aantal seconden |
| `DISCORD_WEBHOOK_URL` | _(leeg)_ | Optioneel: Discord meldingen |
| `GUNICORN_WORKERS` | `2` | Aantal Gunicorn+Uvicorn workers |

## Database

Tabel `counts`. De web-app maakt de tabel zelf aan als die nog niet bestaat
(`CREATE TABLE IF NOT EXISTS` bij het opzetten van de verbindingspool), zodat
elke lege MySQL/MariaDB-database werkt. Het `mooindag-db` image bevat
daarnaast `db/create_db.sql` als init-script.

| Kolom | Type |
|---|---|
| `id` | INT AUTO_INCREMENT PRIMARY KEY |
| `message` | TEXT NOT NULL |
| `date` | TEXT NOT NULL |
| `time` | TEXT NOT NULL |
| `client_ip` | TEXT NOT NULL |

## Deployment op Bunny.net (twee Magic Container apps)

Draai web en database **nooit samen in één multi-region app** (zie de
[hoofd-README](../README.md) voor waarom). Splits in twee apps:

1. Maak een **nieuwe Magic Containers app** (bijv. `mooindag-db`) met
   alleen het `mooindag-db` image, het `db_data` volume op
   `/var/lib/mysql`, **1 regio, autoscaling uit (vast 1 pod)** en een
   endpoint dat poort 3306 exposet.
2. Verwijder in de web-app de db-container én het volume, en wijs de
   web-container naar de nieuwe database: `DB_HOST=<endpoint-van-de-db-app>`,
   `DB_SSL=true`, `DB_SSL_VERIFY=false` (MariaDB genereert standaard een
   self-signed certificaat; het verkeer is dan versleuteld). Kies een **sterk**
   `DB_PASSWORD` — de databasepoort is publiek bereikbaar.
3. De web-app mag nu vrij schalen over alle regio's: elke pod praat met
   dezelfde database, dus iedereen ziet dezelfde teller.

*Let op:* schrijfacties vanuit verre regio's krijgen wat extra latency
(Tokyo → Amsterdam is ~250 ms) en Bunny-volumes hebben geen automatische
backups — draai af en toe een `mariadb-dump`, of overweeg de
[`bunny-libsql`](../bunny-libsql/) variant.

## Kubernetes

In `k8s/` staan manifests die dezelfde architectuur afdwingen op elk
Kubernetes-cluster (k3s, minikube, managed):

- **`web-deployment.yaml`** — stateless [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/),
  3 replicas, readiness-probe op `/healthz`, read-only rootfs;
- **`db-statefulset.yaml`** — [StatefulSet](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
  met exact 1 replica en een PersistentVolumeClaim;
- **`db-service.yaml` / `web-service.yaml` / `web-ingress.yaml`** — interne
  DNS (`DB_HOST=db`), loadbalancing en externe toegang.

```bash
# 1. Secret met wachtwoorden aanmaken (eenmalig, zie k8s/secret.example.yaml)
kubectl create namespace mooindagcounter
kubectl -n mooindagcounter create secret generic mooindag-db \
  --from-literal=MARIADB_ROOT_PASSWORD='...' \
  --from-literal=DB_PASSWORD='...'

# 2. Alles uitrollen (vanuit de root van de repo)
kubectl apply -k microservices/k8s/

# 3. Web-laag schalen (de database schaalt bewust niet mee)
kubectl -n mooindagcounter scale deployment/web --replicas=5
```
