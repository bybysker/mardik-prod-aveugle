# Notes formateur — Mardik Support Agent (prod-aveugle)

Branche locale `instructor` — **ne pas pousser sur le remote**. Elle contient la
liste des trous seedés sur `main`, le dossier `solutions/` avec les fichiers
corrigés, et les correctifs en place dans `src/`.

Posture : **imiter** (remédiation). L'application *tourne presque* : les imports
résolvent, le câblage est en place, mais l'observabilité est aveugle et deux
incidents récurrents passent sous les radars. 12 trous répartis sur les
compétences de la phase.

État attendu :
- sur `main` : `uv run pytest` → **9 échecs / 1 succès** (le succès est un test
  trop laxiste, voir trou n°7), messages d'erreur lisibles, aucune erreur de
  collection.
- sur `instructor` : `uv run pytest` → **10 succès**.

Récapitulatif des familles : observabilité (n°1-5), tests d'intégration
(n°6-8), incidents (n°9-10), intégration continue (n°11-12).

## Trous

### Trou n°1 — Observabilité non câblée dans l'application
- **Compétence ciblée**: C20 — surveiller l'application / C11 — monitorer
- **Difficulté**: moyen
- **Localisation**: `src/mardik/app.py` (`build_agent`)
- **Symptôme**: `tests/unit/test_wiring.py` — l'agent assemblé porte une `NoOpTelemetry`, donc aucune trace ni métrique en production.
- **Cause racine**: `build_agent` ne construit jamais de télémétrie et laisse l'agent retomber sur le no-op.
- **Correctif**: construire `build_default_telemetry(...)` et la passer à `Agent(...)`.

### Trou n°2 — Span manquant sur les appels d'outils
- **Compétence ciblée**: C20 / C17
- **Difficulté**: moyen
- **Localisation**: `src/mardik/agent.py` (`_dispatch_tool`)
- **Symptôme**: `test_agent_observability.py::test_tool_call_is_traced` — aucun span `tool.call` exporté, la cause d'un échec d'outil est invisible.
- **Cause racine**: l'exécution de l'outil n'est pas encadrée par un span.
- **Correctif**: envelopper le dispatch dans `start_as_current_span("tool.call", attributes={"tool.name": ...})`.

### Trou n°3 — Métrique `latency_ms` non émise
- **Compétence ciblée**: C11 — monitorer (métriques)
- **Difficulté**: moyen
- **Localisation**: `src/mardik/agent.py` (`run_turn`)
- **Symptôme**: `test_latency_metric_emitted` — aucun point de mesure `latency_ms`.
- **Cause racine**: la latence est calculée mais jamais enregistrée.
- **Correctif**: appeler `self.telemetry.record_latency(elapsed_ms, session_id=...)`.

### Trou n°4 — Logs non structurés (`print`)
- **Compétence ciblée**: C20 — journalisation
- **Difficulté**: facile
- **Localisation**: `src/mardik/agent.py` (`run_turn`, fin de tour)
- **Symptôme**: `test_turn_completion_is_logged_structured` — aucun événement `turn.completed` capturé par structlog.
- **Cause racine**: le tour est journalisé via `print(...)` au lieu du logger structuré.
- **Correctif**: `self.telemetry.logger.info("turn.completed", session_id=..., latency_ms=...)`.

### Trou n°5 — Contexte de trace perdu entre threads
- **Compétence ciblée**: C17 — composants techniques
- **Difficulté**: difficile
- **Localisation**: `src/mardik/agent.py` (`_invoke_llm`)
- **Symptôme**: `test_trace_context_propagated_across_threads` — le span `llm.invoke` a un `trace_id` différent de `agent.turn`.
- **Cause racine**: l'appel LLM est déporté sur un `threading.Thread` sans propager le contexte OpenTelemetry (les `contextvars` ne sont pas copiés vers le thread).
- **Correctif**: capturer `otel_context.get_current()` avant le thread, `attach`/`detach` dans le worker.

### Trou n°6 — Le runner ne rejoue pas le contexte
- **Compétence ciblée**: C12 — tests automatisés (scénarios multi-sessions)
- **Difficulté**: moyen
- **Localisation**: `src/mardik/runner.py` (`replay`)
- **Symptôme**: `test_replay_preserves_session_context` — la réponse finale ne contient pas le statut attendu (`expédiée`) car le numéro de commande, donné dans un tour précédent, est perdu.
- **Cause racine**: `replay` n'envoie que le dernier message et ignore l'historique.
- **Correctif**: réinjecter `messages[:-1]` dans le store avant le tour final.

### Trou n°7 — Assertions d'intégration trop laxistes
- **Compétence ciblée**: C12 — tests automatisés
- **Difficulté**: moyen
- **Localisation**: `tests/integration/test_replay.py` (`test_replay_smoke`)
- **Symptôme**: le test passe sur `main` (`assert result.reply is not None`) alors que la régression du trou n°6 devrait être détectée — c'est le seul test vert sur `main`.
- **Cause racine**: l'assertion ne vérifie pas le contenu de la réponse.
- **Correctif**: durcir l'assertion (présence de `Commande #1042`, absence de `introuvable`).

### Trou n°8 — Fixture de session manquante (incident #2)
- **Compétence ciblée**: C12 / CT4
- **Difficulté**: facile
- **Localisation**: `sessions/incident_timeout.json` (absent sur `main`)
- **Symptôme**: `test_replay_timeout_incident` — `FileNotFoundError` au chargement de la session.
- **Cause racine**: la session rejouant l'incident de timeout n'a jamais été enregistrée.
- **Correctif**: ajouter `sessions/incident_timeout.json`.

### Trou n°9 — Course critique sur l'état partagé (incident #1)
- **Compétence ciblée**: C21 — résoudre les incidents / C17
- **Difficulté**: difficile
- **Localisation**: `src/mardik/session.py` (`record_turn` + accès historique)
- **Symptôme**: `test_record_turn_counts_every_concurrent_turn` — le compteur de tours perd des incréments sous concurrence (lecture-modification-écriture non atomique).
- **Cause racine**: le store partagé n'a aucune synchronisation.
- **Correctif**: protéger les accès par un `threading.Lock`.

### Trou n°10 — Timeout silencieux renvoyant `None` (incident #2)
- **Compétence ciblée**: C21 / C17
- **Difficulté**: moyen
- **Localisation**: `src/mardik/agent.py` (`_invoke_llm_sync`)
- **Symptôme**: `test_agent_errors.py::test_llm_timeout_surfaces_as_domain_error` — au lieu d'une erreur explicite, le timeout est avalé et `None` se propage (puis `AttributeError` en aval).
- **Cause racine**: le `except TimeoutError` retourne `None` au lieu de lever.
- **Correctif**: lever `LLMTimeoutError` (et incrémenter le compteur d'erreurs).

### Trou n°11 — La CI ne lance pas les tests d'intégration
- **Compétence ciblée**: C18 — automatiser les tests en intégration continue
- **Difficulté**: facile
- **Localisation**: `.github/workflows/ci.yml`
- **Symptôme**: le workflow ne lance que `pytest tests/unit` : les tests de rejeu (et donc les incidents) ne sont jamais vérifiés en CI.
- **Cause racine**: cible de test restreinte aux tests unitaires.
- **Correctif**: lancer la suite complète.

### Trou n°12 — Pas de seuil de couverture bloquant
- **Compétence ciblée**: C18
- **Difficulté**: facile
- **Localisation**: `.github/workflows/ci.yml`
- **Symptôme**: aucune garde sur la couverture ; une régression non testée passe la CI.
- **Cause racine**: absence de `--cov-fail-under`.
- **Correctif**: `pytest --cov=mardik --cov-fail-under=80` (n°11 et n°12 se corrigent ensemble).

## Implémentation de référence

Voir `solutions/` (miroir des fichiers corrigés) et les correctifs en place dans
`src/` sur cette branche. `git diff main instructor -- src tests sessions .github`
montre l'ensemble des correctifs.

## Critères de performance (rappel)

- Les tests d'intégration rejouent des sessions réelles et détectent les incidents.
- Les traces permettent de remonter à la cause d'une panne.
- Au moins deux incidents récurrents (n°9 course critique, n°10 timeout silencieux) sont corrigés.

## Compétences ciblées

C11 (n2), C12 (n2), C17 (n2-3), C18 (n1-2), C20 (n1-2), C21 (n3), CT3 (n3), CT4 (n3).
