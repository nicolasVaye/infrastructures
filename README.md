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

### Mode minimal (développement) — 4 commandes

```bash
# 1. Prérequis : Docker + (optionnel) uv pour le dev sans Docker
cp .env.example .env

# 2. Mettez de VRAIS secrets dans .env (le backend refuse de démarrer sinon) :
#    JWT_SECRET (≥ 32 chars), STORAGE_SECRET, SEED_ADMIN_PASSWORD
nano .env        # ou vim

# 3. Build + démarrage (Postgres + backend + workers + frontend + scheduler)
make up          # = docker compose --profile keycloak up -d --build

# 4. Vérifier que tout est sain
make ps          # tous les services doivent passer "healthy"
curl localhost:8000/health    # {"status":"ok","database":"ok"}
```

- Frontend : http://localhost:8080 — **admin / <votre SEED_ADMIN_PASSWORD>**
  (changement de mot de passe forcé au 1er login)
- API : http://localhost:8000/docs (OpenAPI)
- Premier login Keycloak optionnel : profil déjà inclus dans `make up`.

**En cas de problème** : `make logs` (logs temps réel), `make restart`,
`make rebuild` (rebuild complet). La CI locale se lance avec `make test`
(voir « Tests » plus bas).

### Développement local sans Docker (uv)

```bash
uv sync                                # dans shared/, backend/, frontend/ (installe shared en éditable)
uv run uvicorn app.main:app --reload   # backend, http://localhost:8000
uv run python -m app.worker            # worker(s)
BACKEND_URL=http://localhost:8000 uv run python main.py   # frontend (depuis frontend/app)
```

Ou via le Makefile : `make dev-backend`, `make dev-worker`, `make dev-frontend`.

Sans Docker, le backend retombe sur SQLite (`DATABASE_URL` non définie) — pratique pour débugger.
Le backend refuse de démarrer avec un `JWT_SECRET` faible/par défaut : en local, exportez un
secret quelconque (≥ 32 caractères) ou `INSECURE_DEV=1` pour un bac à sable jetable.

### Déploiement scalé sur Docker Swarm (production)

L'architecture (stateless partout, DB unique) est conçue pour le scale-out. Le fichier
`docker-stack.yaml` décrit la stack production : **Traefik** (TLS auto + sticky sessions
pour les websockets NiceGUI) devant **2 frontends**, **3 backends**, **4 workers**,
**1 scheduler**, **1 Postgres** épinglé sur un nœud dédié.

```bash
# 0. Prérequis : un cluster Swarm (docker swarm init sur le manager — un seul
#    nœud suffit pour tester), un registre d'images accessible, un DNS pointé.

# 1. Secrets : .env avec JWT_SECRET, STORAGE_SECRET, SEED_ADMIN_PASSWORD,
#    DB_PASSWORD, DOMAIN, ACME_EMAIL (email Let's Encrypt).

# 2. Build & push des images (chaque nœud doit pouvoir les puller) :
docker buildx build --push -t $REG/infra-backend:TAG -f backend/Dockerfile .
docker buildx build --push -t $REG/infra-frontend:TAG -f frontend/Dockerfile .

# 3. Étiquetez le nœud qui portera la base :
docker node update --label-add db=true <nom-du-nœud>

# 4. Déploiement (rolling update start-first, rollback auto en cas d'échec) :
export REG=... TAG=... DOMAIN=...
make swarm-init        # une fois par cluster
make swarm-deploy      # = docker stack deploy -c docker-stack.yaml infrastructures

# 5. Vérification & scaling à chaud :
make swarm-ps                          # état des réplicas
make swarm-scale BACKEND=5 WORKER=8    # scale sans interruption
```

**À lire avant de scaler** :
- Le **frontend** exige des **sticky sessions** (déjà configurées dans le stack via
  Traefik `loadbalancer.sticky.cookie`) : un websocket NiceGUI doit retomber sur la
  même réplique. Pour partager les storages entre répliques, décommentez
  `NICEGUI_REDIS_URL` dans `.env` et ajoutez un service Redis.
- Le **backend** se scale librement (stateless, JWT + sessions en base, séquence
  d'événements SSE globale via Postgres). Le **scheduler** reste à 1 réplicas.
- **Postgres** n'est pas un service scalable : 1 instance épinglée + sauvegardes,
  ou une instance managée (`DATABASE_URL` pointe dessus).
- TLS est terminé par Traefik (ACME). Le trafic inter-services reste HTTP sur le
  réseau overlay — chiffrez l'overlay (`docker network create -d overlay --opt encrypted`)
  ou posez du mTLS pour un déploiement multi-tenant sensible.

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

## Sécurité

Ce que la plateforme implémente aujourd'hui :

- **Mots de passe** : PBKDF2-HMAC-SHA256 (260 000 itérations, sel aléatoire) ; les mots de passe
  initiaux et de reset sont **aléatoires et uniques par compte** (affichés une seule fois à l'admin,
  changement forcé à la première connexion) — plus aucun mot de passe partagé par défaut.
- **Anti brute-force backend** : `POST /auth/login` refuse (429) après 10 échecs en 15 min,
  comptés par IP **ou** par nom d'utilisateur. Le compteur est adossé à la table d'audit
  (`login_failed`) : partagé entre toutes les répliques du backend et persistant aux redémarrages.
  Le port API n'est publié que sur `127.0.0.1` — le navigateur ne doit jamais joindre le backend
  en direct, le frontend proxifie tout.
- **JWT** : access 30 min / refresh 12 h. **Rotation des refresh tokens** avec détection de
  réutilisation : chaque refresh n'invalide plus seulement l'ancien token — un rejein d'un token
  déjà consommé révoque immédiatement toute la session (audit `refresh_reused`, kick SSE).
- **Secrets** : refus de démarrer avec un `JWT_SECRET` faible/par défaut (< 32 caractères ou
  valeur connue). Opt-out local uniquement via `INSECURE_DEV=1`.
- **Session navigateur** : cookie signé httpOnly SameSite=Lax ; le timeout d'inactivité (30 min)
  est alimenté par le heartbeat (une SPA n'émet pas de requêtes HTTP) ; cap absolu 12 h.
- **Sessions backend** : heartbeat toutes les 15 s, « connecté » = heartbeat < 3 min ; les
  sessions zombies (navigateur fermé sans logout) sont visibles et filtrables dans l'onglet
  Sessions jusqu'au job de maintenance nocturne.
- **Audit trail** : logins, échecs de login, refresh rejeu, resets, CRUD — consultable côté admin.

Reste volontairement non couvert (voir plus bas « ce qu'il reste à faire ») :

- **CSP (Content-Security-Policy)** : un en-tête CSP strict casserait l'UI NiceGUI/Quasar telle
  qu'elle est générée aujourd'hui. NiceGUI n'expose pas de hook pour injecter des *nonces* dans
  le HTML qu'il produit (scripts inline partout, `eval` côté client, websocket, polices), donc
  une policy utilisable serait de la forme
  `default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'`
  — mieux que rien (elle bloque les sources externes) mais sans la garantie anti-XSS d'une CSP
  par nonces. Recommandation : la poser sur le reverse-proxy de production une fois qu'il
  existe, et la durcir à mesure que NiceGUI (issue ouverte côté framework) permettra les nonces.
- **TLS inter-services** : aujourd'hui tout est HTTP à l'intérieur du réseau Docker (frontend →
  backend → Postgres). Sur un hôte unique, le trafic ne quitte pas le kernel ; en scale-out
  multi-hôtes, chiffrez le réseau overlay (Swarm/K8s) ou mettez du mTLS entre services —
  sinon les JWT transitent en clair entre machines. Devant le frontend, un HTTPS terminating
  (nginx/Caddy/Traefik) est indispensable dès que l'application quitte localhost.

## Ce qu'il reste à faire (volontairement hors squelette)

- isolation multi-clients (tenant/organisation) — prochaine étape planifiée ;
- load-balancer / k8s (HPA), PgBouncer devant Postgres ;
- CSP sur le reverse-proxy de production (voir ci-dessus) ;
- réseau inter-services chiffré pour le scale-out multi-hôtes (voir ci-dessus).

## Ce qui est désormais couvert

- temps réel SSE (LISTEN/NOTIFY → fanout → `/events`, replay `Last-Event-ID`,
  watchdog client, **séquence d'événements globale multi-réplicas via Postgres**) ;
- rate limiting du login backend (audit-backed, multi-répliques) ;
- rotation des refresh tokens avec détection de rejeu ;
- mots de passe initiaux/reset aléatoires et uniques ;
- refus de boot avec secrets faibles (JWT **et** mot de passe admin seedé) ;
- **migrations Alembic versionnées** (baseline 0001, appliquées au boot sous
  advisory lock — plus de DDL ad hoc) ;
- **avatars hors payloads** (UserOut = flag + version, route dédiée
  `GET /users/{id}/avatar` accès-contrôlée) + **pagination de `/users`** ;
- **/health qui vérifie la base** (503 si KO) + healthchecks compose backend/frontend ;
- **X-Forwarded-For honoré uniquement derrière un proxy de confiance**
  (`TRUSTED_PROXIES`, défaut : ranges privés) ;
- **CI GitHub Actions** (compileall + i18n + ruff + pytest à chaque push/PR).

### Montée en charge du frontend

Au-delà d'une réplique frontend, les storages NiceGUI (sessions navigateur) doivent être
**partagés** — par défaut ils vivent dans des fichiers locaux par process :

```yaml
# docker-compose.yaml, service frontend
environment:
  NICEGUI_REDIS_URL: redis://redis:6379    # storages partagés via Redis
```

Et gardez des **sticky sessions** au load-balancer : un client websocket NiceGUI doit retomber
sur la même réplique. (Le backend, lui, est stateless : JWT + sessions en base + notifications
`pg_notify`, il se scale librement.)

## Tests

Le même gate que la CI (GitHub Actions, `.github/workflows/ci.yml`), jouable en local :

```bash
make test           # tout : backend (pytest) + frontend (compile + i18n)
make test-backend   # backend seulement (SQLite in-process, pas de Docker requis)
make test-frontend  # compileall + check i18n (en/de/fr complets, zéro doublon)
make check          # le gate CI exact (compileall + i18n + pytest)
```

Couverture des tests backend (`backend/tests/`) : flux login/jobs/sessions, IdP OIDC,
worker, **fail-fast secrets**, **rotation refresh + détection de rejeu**, **rate-limit
login (429)**, **SSE (seq, ring buffer, replay Last-Event-ID, _resync)**, **avatars
hors payloads + pagination /users**, **/health avec vérification DB**.

Les tests tournent sur SQLite in-process (`INSECURE_DEV=1`) : rapides, sans service
externe. Les chemins spécifiques Postgres (LISTEN/NOTIFY, séquence globale) se valident
en conditions réelles : `make up` puis `docker compose logs backend | grep seq=`.

## Dépendances : versions maîtrisées et reproductibles

**Principe** : le code fixe les versions (`pyproject.toml`), le lock garantit la
reproductibilité totale (arbre de dépendances complet, versions transitives incluses).

- **Backend / workers / shared** : `uv`. Le `backend/uv.lock` est (à être) commité ;
  le `Dockerfile` le copie quand il est présent, et `uv sync` installe alors exactement
  le même arbre à chaque build. Sans lock, uv résout depuis `pyproject.toml` à chaque
  build (marche, mais non reproductible).
- **Frontend** : même layout que le backend — image `python:3.12-slim` + `uv` ; toutes
  les dépendances (NiceGUI inclus, épinglé `==3.18.0`) viennent de
  `frontend/pyproject.toml` + `frontend/uv.lock` (à commiter). Bump de NiceGUI :
  uniquement dans `frontend/pyproject.toml` (pas d'autre endroit).

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
