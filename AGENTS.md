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

## 3. 🐛 BUG SSE (CAUSE TROUVÉE, FIX APPLIQUÉ après v7.45)

**Symptôme (v7.44/v7.45)** : le flux SSE s'ouvre, la première trame (`retry: 5000\n: connected`) arrive, puis plus rien : aucun keepalive, aucun événement, le read-timeout httpx 45 s ne se déclenche jamais (une seule connexion, aucun retry), panneau figé sur "connected, last data received Xs ago (seq 0)".

**Cause racine (prouvée dans la source NiceGUI 3.18.0, `client.py` `handle_disconnect`)** :
`install_event_listener()` enregistrait `app.on_disconnect(lambda: task.cancel())`
— un hook **global**. NiceGUI exécute TOUS les `app._disconnect_handlers` à la
déconnexion de **n'importe quel** client (autre onglet, autre navigateur, autre
utilisateur, ou drop websocket transient qui se reconnecte quelques secondes plus
tard pendant le délai de grâce de 20 s). Chaque disconnect étranger annulait donc
la tâche SSE de cet onglet : `CancelledError` → la tâche meurt en silence → état
gelé `connected: True` (le watchdog et le read-timeout ne peuvent plus tirer : la
tâche n'attend plus rien), `connects` reste à 1, aucune reconnexion. Le backend
était sain tout du long (keepalives continués, cf. compteurs v7.45).

**Fix** (`frontend/app/services/events_client.py`, `install_event_listener`) :
- hooks **par client** (`context.client.on_disconnect/on_connect`) au lieu du hook global ;
- les handlers agissent sur la tâche COURANTE lue dans `app.storage.client['events_task']` (jamais une référence capturée) ;
- `_rearm_stream` en `client.on_connect` redémarre la tâche si elle est morte : un drop transient qui se reconnecte (grâce NiceGUI) ne laisse plus l'onglet sans events, car le page builder ne se rejoue pas à la reconnexion et le garde `events_installed` empêchait toute réinstallation ;
- log INFO `Event stream task cancelled (last_seq=N)` sur annulation pour rendre le phénomène visible dans les logs.

**Vérification post-fix (docker compose)** : les compteurs `keepalives` de
`GET /system/sse-stats` et `connects`/`last_chunk_ts` du panneau Realtime
Diagnostics doivent avancer ensemble ; ouvrir/fermer un second onglet ne doit
plus figer le flux du premier ; un événement (login OIDC) doit arriver en seq > 0.

**Note résiduelle (corrigée)** : l'entrée `ui.run` active de `frontend/app/main.py`
est désormais la **variante 2 prod `reload=False`** (la variante dev est en
commentaire) — le conteneur frontend ne tourne plus avec l'auto-reloader.
Pour le dev local, re-basculer sur la variante 1.

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
- **NiceGUI** : les tâches de fond n'ont pas de contexte page → ne jamais toucher `app.storage` depuis une tâche ; passer par une queue + `ui.timer` (pattern `_drain()`). **Hooks de cycle de vie : TOUJOURS `context.client.on_connect/on_disconnect` (par client), jamais `app.on_disconnect` (global : se déclenche pour N'IMPORTE QUEL client qui se déconnecte et tuait la tâche SSE de chaque onglet — cause du bug SSE v7.44/45)**. **Refresh de tables : refreshable PAR CELLULE + signature par cellule (pattern `_users_tab` / `sessions_content`) — un refresh par ligne suffit à faire clignoter l'avatar à chaque heartbeat (last_activity bouge toutes les 15 s)**. **Ordre de rendu STABLE : `GET /sessions` est trié par `last_activity DESC` (brouillé par chaque heartbeat) — trier par une clé stable (`created_at`) sinon la table se rebuild entièrement à chaque poll.**
- **Onglets /settings LAZY (v7.48)** : NiceGUI exécute TOUS les blocs `ui.tab_panel` au rendu de la page — construire les 6 onglets d'un coup faisait payer ~10 appels REST + une sparkline par session AVANT le premier affichage. Pattern : un slot `ui.column` par panel, corps construit à la PREMIÈRE activation (`on_value_change` sur `ui.tabs` ; l'évènement initial arrive AVANT la création des slots → ignorer un slot manquant ; `ui.tab_panel` accepte le NOM en chaîne, l'objet `Tab` n'a plus d'attribut `.name`). Le logger `pages` loggue « Page 'X' built in N ms » pour chaque page (WARNING > 1,5 s) — c'est le meilleur proxy du ressenti d'affichage.
- **Perf / ressenti (outillage v7.48)** : `backend/tests/test_perf_volume.py` = sentinelles de latence sur une base seedée (450 users, 600 sessions, 3000 audit, 2500 activity) — budgets généreux, détecte les N+1 et les regressions de forme de requête (a attrapé `activity.py` : un `session.get` par utilisateur/sesion, corrigé en un seul `IN`). `make perf` = `scripts/perf_probe.py` (temps d'accès par URL authentifié, p50/p95, seuil `PERF_SLOW_MS`, exit 2 si dépassé). `make perf-ui` = `scripts/perf_ui.py` (Playwright : temps d'affichage réel des pages + première activation des onglets, budget `PERF_UI_SLOW_MS` ; cliquer les onglets PAR INDEX — les labels sont localisés et « Roles » matche « Users & roles » en sous-chaîne).
- **Pagination tableaux admin (v7.48)** : `components/pager.py` (composant partagé « Showing X–Y of Z » + chevrons, i18n `common.pager.*`). **Users/Sessions = pagination CLIENT** : toutes les données restent fetchées (badges online, sparklines bougent en live) ; seul le SLICE RENDU est paginé (50/page) — le rebuild par signature compare la slice visible, la page est reset sur filtre et clampée quand le total rétrécit. **Audit = pagination SERVEUR** (`GET /audit?limit&offset` + `/audit/count` avec le MÊME filtre `actions`, sinon total ≠ lignes paginées). Le pager ne rend jamais de boutons morts : une seule page → juste le compteur. Le journal du Realtime Diagnostics reste plafonné à 50 incidents (scroll area) : borné par design, pas de pagination.
- **Changement d'identité en cours de page (v7.48, bug 403 storm)** : `app.storage.user` est par NAVIGATEUR — se connecter en utilisateur de moindre privilège depuis le même navigateur (callback OIDC, login dans un autre onglet) échange les tokens SANS reconstruire la page ouverte. Une page /settings construite en admin continuait d'appeler les endpoints admin avec un token non-admin → tempête de « API error 403: Admin role required » ressentie comme « le SSE ne marche plus ». Fixes : (1) **watcher de rôle** dans `settings_content` (timer 5 s, `not _is_admin()` → redirection) ; (2) `_fetch` de users/sessions : ApiError 401/403 → arrêt silencieux ; (3) `audit_table` : 403 → carte muette. **Tout fetch d'un onglet admin doit gérer 401/403 silencieusement** — la page sera fermée par le watcher.
- **Tests SSE de propagation (v7.48)** : `backend/tests/test_sse_propagation.py` épingle le contrat évènements (login → `sessions_changed`, avatar → `user_updated` avec `user_id`, logout → `session_revoked` + `sessions_changed`, + lignes d'audit) via un abonné `events._subscribers` — **httpx ASGITransport ne peut PAS streamer GET /events** (il attend la fin de l'app ASGI) ; le transport SSE lui-même est couvert par `test_sse_events.py`. `make test-sse-ui` (scripts/sse_check.py, Playwright) = les scénarios d'acceptation en navigateur réel : login/avatar/logout visibles live depuis une page /settings ouverte (crée un user jetable « sse-check », le supprime en finally), + fermeture de la page admin quand l'identité quitte le navigateur (logout depuis un 2e onglet).
- **Propagation d'identité entre onglets (v7.48)** : `with_base_layout` (main.py) enregistre par client une empreinte `identity_seen = (user_id, role)` au build de la page et un timer 2 s qui recharge la page dès que le storage ne correspond plus. Cas couverts : login/logout dans un AUTRE onglet du même navigateur écrase `storage.user` (partagé par cookie) — sans ça le header/nav de l'onglet 1 restait figés sur l'ancienne identité (nom du dropdown, lien App Settings selon rôle) jusqu'à un F5 manuel que rien ne justifie pour l'utilisateur. **Point clé : un 2e login n'est possible que si la page /login des DEUX onglets a été ouverte AVANT le 1er login** (la vue login rebondit les navigateurs déjà authentifiés) — c'est le protocole de `make test-identity-ui` (scripts/identity_check.py, Playwright). Fingerprint = (user_id, role) uniquement : les changements d'avatar/nom passent déjà par `profile_version` (timer du header), pas de reload superflu.
- **Diagnostic identité/onglets (v7.48)** : chaque build de page loggue « Page 'X' built in N ms (session=<id-8-chars> user=<name>) » — le mapping onglet ↔ fichier storage ↔ identité est directement observable (`docker compose logs frontend | grep "Page '"`). Deux onglets avec des session ids différents = deux cookies distincts (course des premiers chargements en parallèle, partition Firefox ou conteneurs) = sessions indépendantes, F5 ne peut rien fusionner et le watcher d'identité n'a rien à détecter. Même id = session partagée, swap au 2e login → rechargement par le watcher. **Rappel : `.nicegui/` vit dans le conteneur frontend SANS volume — chaque rebuild efface les storages et déconnecte tous les navigateurs ; le comportement « partagé vs séparé » d'un utilisateur peut changer d'un run à l'autre pour cette seule raison.**
- **Identités par onglet / cookies partitionnés (v7.48)** : `app.storage.user` est clavé par le COOKIE de session, pas par onglet. En Chrome les onglets partagent le cookie → UNE identité par navigateur (le watcher de rôle couvre le swap). En Firefox (dFPI/cookie partitioning), le flux OIDC (redirection croisée Keycloak) peut donner à l'onglet un cookie PARTITIONNÉ → deux onglets = deux sessions indépendantes (admin + nico coexistent, logout de l'un n'affecte pas l'autre) — comportement observé et BÉNIN, pas un bug. Les fichiers `.nicegui/storage-user-<uuid>.json` (un par cookie) permettent de trancher en diagnostique. **Ne jamais assumer storage.user partagé ou isolé : les deux cas existent selon le navigateur ; tout code sensible au rôle doit réagir au changement (watcher) et tolérer 401/403 silencieusement.**
- **Bruit de logs Drawer (v7.48)** : le widget Drawer de NiceGUI interroge son état par JS attendu (1 s) à chaque connect ; si la page meurt à ce moment (F5, navigation logout) → ERROR traceback « JavaScript did not respond within 1.0 s ». Filtré par `_DrawerTeardownFilter` (core/logging_config.py) : uniquement les records 'nicegui' dont la traceback passe par `elements/drawer.py` — les vraies erreurs JS passent toujours.
- **Service worker / cache** : si un fichier CSS est modifié, bumper la version cache dans `frontend/app/assets/pwa/sw.js` (actuel : `nicestack-v7.46.0`).
- **Activité** : `POST /activity` attribue chaque navigation à la session JWT (`sid`, colonne `activity_events.session_id`). `GET /activity/users` = cumul PAR UTILISATEUR (Chrome+Firefox fusionnés, onglet Users) ; `GET /activity/sessions` = par SESSION (onglet Sessions, un graphe par navigateur). Sparkline partagée : `views/_common.activity_sparkline()`.
- **Logo / icônes** : les PNG statiques de `assets/icons` sont SUPPRIMÉS. Le backend génère toutes les icônes (ICO + PNG 192/512/maskable/apple-touch via Pillow) au `PUT /app/logo` et les sert par `GET /app/logo/icons/{name}` ; le frontend les expose en `/icon-*.png`, `/apple-touch-icon.png` avec fallback `logo.svg`. Le proxy frontend (`core/backend_assets.py`) cache 60 s (tue le spam 404 « pas de logo ») et est invalidé par la page settings après upload. Les SVG uploadés ne sont pas rasterisés (fallback SVG). **Propagation temps réel : `PUT/DELETE /app/logo` émet `app_settings_changed` (setting=logo, version) ; le frontend bump `logo_version` (le timer du header re-rend le logo en ≤2 s) et réécrit les `<link rel=icon>` avec `?v=` (les navigateurs ne rechargent JAMAIS un favicon spontanément, même avec no-cache).**
- **Splitter sidebar** : la poignée est `position:fixed` synchronisée en JS (`left = drawer.width - 5`). Pendant l'animation du toggle, un follower rAF suit la largeur réelle du drawer frame par frame — **ne pas remettre de `transition` CSS sur `left` de `.sidebar-collapse-handle`** (lag → désolidarisation) et **ne jamais lire `getBoundingClientRect().width` comme largeur de départ d'un drag** (valeur transitoire en cours d'animation) : utiliser l'état `currentW` du script. **Le conteneur des pages (`.q-page-container`) porte un `padding-left` piloté par le MODÈLE Quasar : toute largeur de drawer appliquée en JS doit AUSSI mettre à jour ce padding, sinon le contenu des sub-pages ne suit pas** (le follower rAF s'en charge pendant l'animation, `apply()` pour le drag). **PAS de `!important` sur la transition `.q-drawer`** : le script la désactive inline (`transition: none`) pendant le drag — avec `!important` le drawer continuait d'easer vers le curseur pendant que la poignée le suivait exactement (décalage visible sur tout le drag).
- **Rafraîchissements SSE = signaux, pas des données** : un event SSE bump un compteur dans `app.storage.user` (`sessions_refresh_counter`, `users_refresh_counter`, `jobs_refresh_counter`…) ; un `ui.timer` de l'onglet voit le compteur bouger, REFETCH en REST et re-rend par diff de signatures. Un type de changement sans compteur écouté (ex: `user_updated` avant v7.46.3) n'est visible qu'au poll de 15 s — ajouter le compteur au handler ET l'écouter dans l'onglet.
- **Timeout d'inactivité du navigateur** : l'AuthMiddleware ne voit que les requêtes HTTP ; une SPA NiceGUI n'en émet plus après le chargement (tout passe par websocket). `last_activity` est donc rafraîchi par le **heartbeat** (`api_client.heartbeat`, timer 15 s en contexte page) — sans ça, 30 min d'usage SPA sans rechargement ⇒ le prochain F5 efface le storage et renvoie /login (symptôme vu « au hasard des navigateurs », pas lié au navigateur). Le backend, lui, considère une session connectée pendant 3 min après son dernier heartbeat (`heartbeat_ttl_seconds=180`). **Diagnostic « renvoyé sur /login »** : le middleware loggue chaque redirection (`Auth redirect: ... session_cookie=ABSENT/present`) — cookie ABSENT = politique/quirk du navigateur ; cookie present = le cookie a été REMPLACÉ par un id de session vide.
- **Rotation du cookie de session (bug Epiphany/WebKitGTK, v7.46.4)** : les sondes du navigateur (favicon, manifest, icônes, sw.js) partent SANS cookie dans WebKitGTK ; nos routes custom (`/logo`, `/favicon.ico`, `/manifest.json`, `/icon-*`, `/apple-touch-icon`, pas les statiques `/assets/`) mintent alors un id de session VIDE dont le Set-Cookie **écrase le vrai cookie** → le prochain F5 tombe sur /login bien que la session backend vive. Fix : `CookieRotationGuard` (frontend core/security.py), middleware OUTERMOST qui strip le Set-Cookie de ces routes — installé via `app.on_startup` avec le trick `app.middleware_stack = None` (Starlette refuse add_middleware après le premier lifespan). Ne pas ajouter de routes publiques custom sans les ajouter à `_COOKIE_SAFE_PATHS/PREFIXES`.
- **Sessions zombies** : un navigateur fermé sans logout laisse une session non révoquée jusqu'au job `maintenance.cleanup_sessions`. `GET /sessions?include_inactive=true` (admin) les retourne avec `active=false` ; l'onglet Sessions a un switch « sessions inactives » (rendu grisé + badge Offline) et une recherche par nom d'utilisateur (les chips par utilisateur ne s'affichent que si ≤ 8 utilisateurs — au-delà, seule la recherche est scalable).
- **Sécurité (v7.47)** : anti brute-force sur `POST /auth/login` (10 échecs/15 min par IP OU username, comptés dans l'audit `login_failed` → multi-répliques ; **le commit des `login_failed` AVANT le raise est vital** — la dépendance DbSession rollback sur HTTPException, sans commit explicite l'échec disparaissait de l'audit ET du compteur). Refresh tokens **tournants** : hash du dernier refresh stocké sur `sessions.refresh_token_hash` ; un rejeu révoque toute la session (audit `refresh_reused`). Mots de passe initiaux/reset **aléatoires par compte** (`generate_initial_password`, plus de constante partagée) : la réponse de `POST /users` et `/users/{id}/reset-password` porte le mot de passe à afficher une fois. **Toute écriture de mot de passe doit committer avant de retourner** (le teardown de la dépendance commit après l'envoi de la réponse : un client qui se logue immédiatement perd la course — bug réel observé). `validate_runtime_secrets()` (bootstrap) refuse les JWT_SECRET faibles (< 32, défauts connus) sauf `INSECURE_DEV=1` (fixtures de test). Port API publié sur `127.0.0.1` uniquement. CSP : pas de header (NiceGUI ne supporte pas les nonces — voir README §Sécurité) ; TLS inter-services à faire au scale-out. Scale frontend > 1 réplique : `NICEGUI_REDIS_URL` + sticky sessions obligatoires (storages NiceGUI = fichiers locaux par défaut).
- **Service worker** : le head appelle `reg.update()` à chaque chargement pour que le nouveau `CACHE` soit repris dès le premier reload (sinon les navigateurs ne re-valident sw.js que toutes les ~24 h et les users gardent l'ancien CSS/JS après un déploiement).

## 4bis. Consolidation v7.47 (fail-fast, Alembic, payloads, CI)

- **Fail-fast secrets** : `app.bootstrap.validate_runtime_secrets` refuse de démarrer avec `JWT_SECRET` par défaut/faible (<32) OU `SEED_ADMIN_PASSWORD` par défaut ('admin'). Opt-out dev : `INSECURE_DEV=1`.
- **Migrations Alembic** : le schéma est versionné dans `backend/migrations/` (baseline = 0001). Au boot, `ensure_schema()` lance `alembic upgrade head` (connection réutilisée, advisory lock). Toute évolution de schéma = nouvelle révision, jamais de DDL ad hoc.
- **Avatars** : `UserOut` ne transporte PLUS le base64 (`has_avatar: bool` + `avatar_version: int`). Image via `GET /users/{id}/avatar` (self ou admin). Frontend : routes proxy `/avatar` et `/users/{id}/avatar`. `GET /users` paginé (`limit` ≤ 500, `offset`) ; le frontend boucle par pages de 200.
- **SSE seq global** : sur Postgres, `notify_event` tire le seq de la séquence `infra_event_seq` DANS la transaction et l'embarque dans le payload (`_seq`) → ordre cohérent multi-réplicas. `_fanout` utilise le seq embarqué, fallback compteur local (SQLite/anciens réplicas).
- **/health** : vérifie la DB (503 `database: unreachable` si KO). Healthchecks compose backend + frontend.
- **X-Forwarded-For** : honoré UNIQUEMENT si le peer TCP est dans `TRUSTED_PROXIES` (CIDRs, défaut = ranges privés). Sinon IP peer directe — un XFF spoofé ne peut plus tourner la clé du rate-limiter.
- **CI** : `.github/workflows/ci.yml` (compileall + `scripts/check_i18n.py` + ruff + pytest à chaque push/PR).
- **Tests** (`backend/tests/`, SQLite in-process) : `test_secrets.py` (fail-fast), `test_auth_security.py` (rotation refresh + replay → révocation, rate-limit 429), `test_sse_events.py` (seq monotonic, ring, replay Last-Event-ID, _resync), `test_users_avatar_pagination.py` (pas de base64 dans UserOut, route avatar accès-contrôlée, pagination), `test_health.py` (200/503).

## 4ter. Makefile & déploiement (v7.47)

**Tests** (le gate CI, jouable en local) : `make test` (tout), `make test-backend` (pytest, SQLite in-process, `uv sync --extra dev` automatique), `make test-frontend` (compileall + check i18n), `make check` (gate CI exact).

**Dev sans Docker** : `make dev-backend` (uvicorn reload, `INSECURE_DEV=1`), `make dev-worker`, `make dev-frontend`.

**Swarm** : `make swarm-init` → `make swarm-deploy` (`docker-stack.yaml`) → `make swarm-scale BACKEND=5 WORKER=8` → `make swarm-ps` / `swarm-logs` / `swarm-remove`. La stack Swarm utilise des images d'un registre (`REG`/`TAG`), Traefik avec TLS ACME + sticky sessions cookie, Postgres épinglé `node.labels.db==true`, update `start-first` + rollback auto. Les images se build/push avec `docker buildx build --push -f backend/Dockerfile .`.

**README** : section « Démarrage » réécrite — mode minimal dev (4 commandes, secrets obligatoires dans `.env`) + mode Swarm scalé complet (prérequis, étapes, garde-fous sticky/Postgres/overlay). S'y référer plutôt que le dupliquer.

## 5. Déploiement & commandes utiles

```bash
docker compose --profile keycloak up -d --build   # déploiement complet
make rebuild                                      # rebuild complet (make up / make test / make help)
docker compose logs -f backend | grep -i sse      # observabilité SSE
curl -N -H "Authorization: Bearer <TOKEN>" http://localhost:8000/events   # test SSE brut
```

## 6. Règles de conduite pour l'agent

1. **Diagnostiquer avant de fixer** : exécuter le protocole §3 dans l'ordre et consigner les résultats avant toute modification.
2. **Changements ciblés** : edits chirurgicaux, pas de refactor opportuniste. Ce projet évolue par petites versions vérifiées.
3. **Toujours valider** : `compileall` + check i18n après chaque modification.
4. **Ne pas toucher** au mécanisme replay (`Last-Event-ID`, ring buffer, `_resync`) sans raison prouvée.
5. **Contexte utilisateur** : l'admin s'appelle Nicolas ; il teste en conditions réelles avec OIDC/Keycloak ; les symptômes qu'il rapporte sont observés en prod docker compose, pas en dev SQLite.
