# Infrastructures

Monorepo d'une plateforme de pilotage : un **frontend NiceGUI** (basé sur
[nicegui-component-based](https://github.com/frycodelab/nicegui-component-based/)), un **backend FastAPI** qui
exécute, planifie et ordonnance des actions asynchrones, et un **package partagé** qui élimine toute
duplication des modèles de sérialisation.

```
┌─────────────┐   REST + JWT    ┌──────────────┐   SQL    ┌──────────┐
│  Frontend    │ ──────────────► │  Backend API  │ ───────► │ Postgres │
│  NiceGUI     │ ◄────────────── │  (répliques)  │          │ cluster  │
└─────────────┘                 └──────┬───────┘          └──────────┘
       ▲                                │ jobs (SELECT … FOR UPDATE SKIP LOCKED)
       │                                ▼
       │                        ┌──────────────┐
       └── heartbeat / audit   │   Workers    │  ← scale horizontalement
                                │ (+ scheduler)│
                                └──────────────┘
```

## Structure

| Dossier | Rôle |
|---|---|
| `shared/` | **Source unique des modèles** : DTOs Pydantic v2 (sérialisation rapide, cœur en Rust), enums, client async (automatisations) et sync (frontend) |
| `backend/` | API REST FastAPI (ORJSON), users/rôles, JWT access+refresh, suivi des sessions (« qui est connecté »), audit trail, file de jobs en base, worker + ordonnanceur CRON |
| `frontend/` | NiceGUI (template frycodelab, quasiment intact) dont la couche services est réimplémentée **au-dessus de l'API REST** |

## Démarrage

```bash
cp .env.example .env          # changez les secrets
docker compose up --build
```

- Frontend : http://localhost:8080 — **admin / admin** (changement de mot de passe forcé au 1er login)
- API : http://localhost:8000/docs (OpenAPI)
- Scalabilité : `docker compose up --scale backend=3 --scale worker=4`

### Développement local (uv)

```bash
uv sync                                # dans shared/, backend/, frontend/ (installe shared en éditable)
uv run uvicorn app.main:app --reload   # backend, http://localhost:8000
uv run python -m app.worker            # worker(s)
BACKEND_URL=http://localhost:8000 uv run python main.py   # frontend (depuis frontend/app)
```

Sans Docker, le backend retombe sur SQLite (`DATABASE_URL` non définie) — pratique pour débugger.

## Authentification : une seule pour tous

Le backend est l'unique source de vérité (users, rôles admin/operator/user, mots de passe PBKDF2).

### Fournisseurs d'identité externes (OIDC / Keycloak)

Des sources d'authentification externes cohabitent avec les comptes locaux :

- **Page admin « Providers »** (sidebar) : créer/modifier/activer/désactiver/supprimer un
  fournisseur OIDC (issuer URL, client ID, secret — jamais renvoyé par l'API), rôle par défaut
  des utilisateurs auto-provisionnés, et bouton « verify » qui teste le document de découverte.
- **Login** : la page affiche un bouton « Sign in with … » par fournisseur activé. Le flux
  authorization-code (state signé anti-CSRF) se joue **entièrement côté backend** : échange du
  code, vérification de l'ID token via le JWKS, provisioning JIT optionnel, puis retour de la
  même paire JWT qu'un login local. Sessions, heartbeat, kick et audit restent identiques.
- Comptes fédérés : `users.auth_provider = 'oidc'`, sans mot de passe local — le login local
  les refuse (`401`) sans révéler leur existence.
- `docker compose --profile keycloak up` lance un Keycloak optionnel (port 8081) pour tester.
  À déclarer chez le client : redirect_uri `http://localhost:8080/auth/oidc/callback`
  (ajustable via `OIDC_REDIRECT_BASE_URL`).

### Jobs : soumission et suivi

- **Page « Submit job »** (`/jobs/new`) : type de job (ex. `demo.sleep`), paramètres JSON,
  priorité (0 = traité en premier) → `POST /jobs` (`202 Accepted`), exécution asynchrone par les workers.
- **Page « Jobs »** (`/jobs`) : liste rafraîchie toutes les 5 s, filtres par état
  (queued / running / succeeded / failed / cancelled) avec compteurs, annulation d'un job
  en file ou en cours, résultat/erreur affichés.

### Sessions connectées, par utilisateur

La page « Sessions » regroupe les sessions actives **par utilisateur** (compteur par user,
filtre par user au clic) : navigateurs web, clients OIDC et automatisations, avec IP, client,
dernier heartbeat et possibilité de révoquer (kick).

- **Le frontend s'authentifie comme n'importe quel client** : la page de login appelle `POST /auth/login`
  et stocke la paire JWT (access 30 min / refresh 12 h) dans `app.storage.user`.
- **Les automatisations externes** utilisent le même endpoint, via `shared.client.AsyncClient` :

```python
from shared.client import AsyncClient

async with AsyncClient("http://localhost:8000") as client:
    await client.login("robot", "secret")          # X-Client-Label: automation
    job = await client.submit_job("demo.sleep", {"seconds": 2})
    job = await client.wait_for_job(job.id)
```

- **Suivi des sessions** : chaque login crée une ligne `sessions` (IP, user-agent, client, heartbeat).
  Les clients web envoient un heartbeat toutes les 60 s ; la page *Sessions* (sidebar) liste qui est
  connecté et permet de révoquer une session (kick).

## Modèles partagés (zéro duplication)

`shared/src/shared/models` définit les DTOs une seule fois. Le backend les utilise comme
`response_model` (sérialisation ORJSON), le frontend les désérialise via les clients.
Modifier un champ = une seule modification, les deux projets voient le changement
(installation éditable en dev, bump de version en prod).

## Jobs / actions

- `POST /jobs` → 202 + job créé `queued` ; priorité, params JSON, `created_by`.
- Les **workers** (`python -m app.worker`) réclament les jobs avec `FOR UPDATE SKIP LOCKED`
  (n'importe combien de réplicas, un job exécuté une seule fois), exécution asynchrone via un registre
  de handlers (`app/worker/__init__.py`, voir `demo.sleep`), annulation coopérative.
- Le **scheduler** (une instance, `SCHEDULER=1`) enfile périodiquement les jobs issus de la table
  `schedules` (CRON).

## Ce qu'il reste à faire (volontairement hors squelette)

- migrations Alembic (le squelette fait `create_all` + seed) ;
- load-balancer / k8s (HPA), PgBouncer devant Postgres ;
- rate limiting des endpoints (néj adoption de slowapi/traefik), refresh token rotation persistée ;
- websocket/SSE pour le suivi de jobs temps réel (le client partagé fait du polling pour l'instant).

## Tests

```bash
cd backend && uv run pytest        # tests API (login, rôles, sessions, jobs) + worker
```

## Dépendances : versions maîtrisées et reproductibles

**Principe** : le code fixe les versions (`pyproject.toml`), le lock garantit la
reproductibilité totale (arbre de dépendances complet, versions transitives incluses).

- **Backend / workers / shared** : `uv`. Le `backend/uv.lock` est (à être) commité ;
  le `Dockerfile` le copie quand il est présent, et `uv sync` installe alors exactement
  le même arbre à chaque build. Sans lock, uv résout depuis `pyproject.toml` à chaque
  build (marche, mais non reproductible).
- **Frontend** : l'image de base `zauberzeug/nicegui:latest` flotte — la version de
  NiceGUI **réellement embarquée** est celle du `pip install` épinglé dans
  `frontend/Dockerfile` (`nicegui[highcharts]==3.18.0`). Bump à faire au même
  endroit que dans `frontend/pyproject.toml`.

### Commandes utiles (voir `Makefile`, `make help`)

```bash
make outdated   # upgrades disponibles pour les paquets installés (frontend + backend)
make versions   # versions réellement en place dans les conteneurs
make lock       # (re)génère backend/uv.lock depuis pyproject.toml → à commiter
make upgrade    # uv lock --upgrade : refresh du lock vers les dernières versions compatibles
```

Workflow de montée de version : `make upgrade` (ou bump du pin frontend) →
`docker compose --profile keycloak up -d --build` → tests → commit du lock.
Dependabot couvre le côté sécurité (alertes sur les ranges `pyproject`).
