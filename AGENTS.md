# AGENTS.md — Guide de contexte pour agent IA (VS Code / API Mistral)

Projet : **infrastructures** — application de gestion d'infrastructures.
Ce fichier transfère le contexte accumulé sur des dizaines d'itérations. **Lisez-le en entier avant de modifier quoi que ce soit.**

---

## 1. Stack & structure

```
infrastructures/
├── backend/            # FastAPI (app/main.py, api/, core/, events.py)
├── frontend/           # NiceGUI (app/main.py, views/, components/, services/)
├── shared/             # Code partagé (src/, client async httpx partagé)
├── docker-compose.yaml # backend + frontend + postgres (+ keycloak via profile)
└── Makefile            # make rebuild = rebuild complet des conteneurs
```

- **Backend** : FastAPI + SQLAlchemy async (asyncpg). Entrée `backend/app/main.py`, montée via `uvicorn app.main:app`. Seul middleware : `CORSMiddleware`.
- **Frontend** : NiceGUI (Python, pas React). Le frontend consomme l'API backend via httpx (token Bearer dans `app.storage.user['access_token']`).
- **DB** : PostgreSQL en prod (docker compose), fallback SQLite en dev. Notifications temps réel via `pg_notify` / `LISTEN`.

## 2. Mécanisme temps réel (SSE) — cœur du sujet

Chaîne complète : mutation → `notify_event()` (pg_notify DANS la transaction) → backend LISTEN (`backend/app/events.py`, canal `infra_events`) → `_fanout()` (seq monotonic + ring buffer 200 events) → SSE subscribers (asyncio.Queue par connexion) → `GET /events` (StreamingResponse, keepalive `: keepalive\n\n` toutes les 15 s) → client httpx côté NiceGUI (`frontend/app/services/events_client.py`) → queue locale → `ui.timer(0.5)` `_drain()` → `handle_event()` (page context).

Points clés :
- **Replay** : le client renvoie `Last-Event-ID` (dernier `id:` reçu) ; le backend rejoue depuis le ring buffer. Si trou > fenêtre : trame `_resync` → le client bump tous les compteurs de refresh.
- **Watchdog client** : `WATCHDOG = 25.0` — chaque chunk est attendu via `asyncio.wait_for(aiter.__anext__(), 25)`. Silence > 25 s ⇒ break ⇒ reconnexion ⇒ replay.
- **Auth** : le SSE exige un Bearer token. Un agent qui teste avec curl doit d'abord obtenir un token (login ou admin bootstrap).
- **Observabilité v7.45** :
  - Backend logs INFO : `SSE subscriber #N connected/disconnected`, `SSE event seq=N fanned out to M subscriber(s)`, `SSE keepalive #N sent`.
  - `GET /system/sse-stats` (admin) : `{subscribers, seq, buffered, keepalives, fanouts}`.
  - `GET /system/events-log` : table `event_log` (incidents SSE/LISTEN, drops, replay gaps).
  - Panneau UI : **App Settings → onglet General → carte "Realtime Diagnostics"** (badge statut SSE, âge des données, seq, chips backend vs client, journal scrollable).
  - Client stocke son état dans `app.storage.user['sse_status']` : `{connected, last_error, last_seq, last_chunk_ts, events, connects}`.

## 3. 🐛 BUG EN COURS (priorité absolue)

**Symptôme (observé en v7.44, à retester en v7.45)** : le flux SSE s'ouvre, la première trame (`retry: 5000\n: connected`) arrive, puis **plus rien** :
- aucun keepalive 15 s reçu côté client ;
- aucun événement (un login OIDC qui émet `sessions_changed` via pg_notify n'est jamais reçu, seq reste 0) ;
- le read-timeout httpx 45 s ne se déclenche **jamais** (une seule connexion, aucun retry) ;
- panneau : "connected, last data received 104s ago (seq 0)".

**Interprétation** : la connexion est un zombie — ouverte mais affamée. La cause exacte (backend fanout ? transport docker/proxy ? httpx ?) n'est PAS déterminée. La v7.45 a ajouté watchdog + observabilité pour la localiser.

**Protocole de diagnostic (dans l'ordre) — exécutez-le AVANT de proposer un fix :**

1. **Le backend produit-il ?** `docker compose logs -f backend` pendant 60 s : chercher `SSE keepalive #N sent` et, après un login, `SSE event seq=N fanned out`. Si oui → backend sain.
2. **Le flux sort-il du conteneur ?** `curl -N -H "Authorization: Bearer <TOKEN>" http://localhost:8000/events` : les keepalives doivent apparaître toutes les 15 s. Sinon → problème uvicorn/transport.
3. **Le frontend reçoit-il ?** Ouvrir l'app, regarder le panneau Realtime Diagnostics : chips "Keepalives envoyés" (backend) vs "Événements reçus (ce navigateur)" et l'âge des données. Si backend compte et client non → coupure entre backend et client httpx.
4. **Le watchdog se déclenche-t-il ?** Logs frontend (`docker compose logs -f frontend`) : `SSE watchdog fired (no chunk in 25s)`. Si oui mais que curl (étape 2) reçoit les keepalives → le problème est côté client httpx (buffering ? itération aiter_bytes ?) et non le transport.
5. Comparer `GET /system/sse-stats` (subscribers ≠ 0 ? keepalives qui montent ?) avec `sse_status` client.

**Pistes non encore explorées** : buffering de réponse dans un proxy/nginx éventuel devant le backend ; comportement d'`aiter_bytes` avec uvicorn ; MTU/docker network ; interaction avec le heartbeat/token refresh qui réécrit `app.storage.user`.

## 4. Conventions du projet

- **Langue de code** : commentaires et docstrings en **anglais** ; UI trilingue **en/de/fr** via `frontend/app/services/i18n.py`, dict `_TRANSLATIONS`. Toute nouvelle clé doit exister dans les 3 langues, sans doublon (566 clés en v7.45). Vérification AST possible.
- **Tests/validations avant toute livraison** :
  ```bash
  python3 -m compileall -q backend/app frontend/app shared/src
  ```
  + check i18n (clés en/de/fr complètes, zéro doublon, script AST sur `_TRANSLATIONS`).
- **Timeouts/constants SSE** : `RECONNECT_DELAY=2.0`, `WATCHDOG=25.0` (client) ; keepalive 15 s, ring 200, queue maxsize 256 (backend). Ne pas modifier sans comprendre le replay.
- **Timezone** : timestamps stockés UTC, rendus via `frontend/app/services/tz.py` (`format_local()`), réglage admin clé `app_timezone` (table `app_settings`).
- **Style UI** : classes CSS custom (`card`, `badge badge-success|warning|danger|info|default`, `button button-primary|secondary|ghost`, `field-label`, `text-muted`), inline styles pour les dimensions. Pas de Tailwind.
- **NiceGUI** : les tâches de fond n'ont pas de contexte page → ne jamais toucher `app.storage` depuis une tâche ; passer par une queue + `ui.timer` (pattern `_drain()`).
- **Service worker / cache** : si un fichier CSS est modifié, bumper la version cache dans `frontend/app/assets/pwa/sw.js` (actuel : `nicestack-v7.39.1`).

## 5. Déploiement & commandes utiles

```bash
docker compose --profile keycloak up -d --build   # déploiement complet
make rebuild                                      # rebuild sans keycloak
docker compose logs -f backend | grep -i sse      # observabilité SSE
curl -N -H "Authorization: Bearer <TOKEN>" http://localhost:8000/events   # test SSE brut
```

## 6. Règles de conduite pour l'agent

1. **Diagnostiquer avant de fixer** : exécuter le protocole §3 dans l'ordre et consigner les résultats avant toute modification.
2. **Changements ciblés** : edits chirurgicaux, pas de refactor opportuniste. Ce projet évolue par petites versions vérifiées.
3. **Toujours valider** : `compileall` + check i18n après chaque modification.
4. **Ne pas toucher** au mécanisme replay (`Last-Event-ID`, ring buffer, `_resync`) sans raison prouvée.
5. **Contexte utilisateur** : l'admin s'appelle Nicolas ; il teste en conditions réelles avec OIDC/Keycloak ; les symptômes qu'il rapporte sont observés en prod docker compose, pas en dev SQLite.
