# Agent Card — Medical Multi-Agent Supervisor

## Identité
- **Nom :** Medical-Supervisor-Agent
- **Version :** 1.1.0
- **Type :** Système multi-agent (pattern Supervisor) avec orchestration LangGraph
- **Auteur :** Ichrak Elhantati, Fatima Ezzahra ELMENOUN, Hassan Boulahfa
- **Date de création :** 2026-06-24
- **Dernière mise à jour :** 2026-06-26 (ajout monitoring, API, CI/CD, déploiement)
- **Fichiers source :** `supervisor_langgraph.py` (graphe + logique métier), `api.py` (API FastAPI), `monitoring.py` (Correlation ID / observabilité)

## Description
Agent conversationnel médical qui reçoit la description d'un patient, décide dynamiquement quels sous-agents spécialisés activer (symptômes, risque, antécédents), combine leurs analyses en un rapport structuré, le soumet à validation humaine, puis route une alerte finale selon le niveau de risque détecté.

## Architecture
```
ChatInput
   │
Supervisor Agent (decide quels agents activer)
   │
[Parallèle] Symptoms_Agent | Risk_Agent | Medical_History_Agent
   │
Combine
   │
Healthcare Response Agent (rapport structuré)
   │
*** HUMAN-IN-THE-LOOP (interrupt_before) ***
   │
Audit Agent (cohérence du niveau de risque)
   │
Risk Extractor ("Haut" / "Bas")
   │
SmartRouter
 ├─ Haut → High Risk Alert : "URGENT : consulter un médecin"
 └─ Bas  → Low Risk Alert  : "PAS URGENT"
   │
END
```

## Capacités
- Analyse des symptômes décrits en langage naturel
- Évaluation du niveau de risque (low/medium/high)
- Revue des antécédents médicaux (conditions chroniques, facteurs de risque)
- Génération d'un rapport patient structuré et lisible
- Point d'arrêt humain obligatoire avant diffusion du rapport (`human_approved`, `human_comment`)
- Audit automatique de cohérence avant le routage final
- Journalisation complète de chaque nœud (entrée/sortie/timestamp) via `log_node()`
- **Observabilité / monitoring :** chaque exécution reçoit un `correlation_id` (UUID) unique, propagé à tous les nœuds du graphe (`monitoring.py`). Chaque nœud loggue son statut (`ok`/`error`), sa latence (`duration_ms`) et les tokens Groq consommés (`input_tokens`/`output_tokens`/`total_tokens`), consultable via l'API (`GET /runs/{correlation_id}`, `GET /metrics`, `GET /dashboard`) ou en JSONL (`monitoring_logs/`).
- **Exposition API :** l'agent est accessible via une API FastAPI (`api.py`) qui orchestre le flux human-in-the-loop en deux appels (`POST /diagnose` puis `POST /diagnose/{thread_id}/approve`).

## API
| Méthode | Route | Description |
|---|---|---|
| `GET` | `/ui` | Interface utilisateur (formulaire symptômes → rapport → approbation → alerte) — `ui.py` |
| `POST` | `/diagnose` | Lance le graphe (Supervisor + 3 sous-agents + rapport), s'arrête avant validation humaine |
| `POST` | `/diagnose/{thread_id}/approve` | Transmet la décision humaine (`approved`, `comment`) et termine l'exécution (audit, routage, alerte) |
| `GET` | `/health` | Sonde de disponibilité (utilisée par Railway) |
| `GET` | `/runs` | Liste des exécutions (monitoring) |
| `GET` | `/runs/{correlation_id}` | Détail d'une exécution : événements par nœud, statut, durée |
| `GET` | `/metrics` | Agrégation JSON : latence et tokens par nœud, compteurs de statuts |
| `GET` | `/dashboard` | Tableau de bord HTML (auto-refresh 15s) : latence, tokens, Correlation ID — `dashboard.py` |

## Tests & CI/CD
- Tests automatisés (`pytest`, dossier `tests/`) : nœuds du graphe, monitoring, et endpoints API — LLM Groq mocké pour ne pas dépendre du réseau/quota.
- Pipeline GitHub Actions (`.github/workflows/ci.yml`) : exécute la suite de tests puis construit l'image Docker à chaque push/PR.

## Conteneurisation & Déploiement
- `Dockerfile` : image basée sur `python:3.11-slim`, expose l'API via `uvicorn` (`api:app`), port piloté par la variable `PORT`.
- **Déployé en production sur [Railway](https://railway.com/)** à partir du repo GitHub (build automatique du `Dockerfile` à chaque push sur `master`).
  - **URL publique :** https://med-agent.up.railway.app
  - **Dashboard monitoring :** https://med-agent.up.railway.app/dashboard
  - **Documentation API (Swagger) :** https://med-agent.up.railway.app/docs
  - `GROQ_API_KEY` configurée comme variable d'environnement dans Railway (onglet Variables), jamais committée dans Git.
- `render.yaml` conservé dans le repo comme configuration alternative (Render exige une carte bancaire de vérification avant de créer un service, même gratuit — Railway a été retenu à la place pour ce déploiement).

## Limites / Garde-fous
- **Ne pose JAMAIS de diagnostic définitif** (contrainte explicite dans `RESPONSE_PROMPT`)
- Recommande systématiquement une consultation médicale si pertinent
- Ne doit pas être utilisé comme substitut à un avis médical professionnel
- Toute sortie doit passer par validation humaine avant action (`human_approved = false` bloque le pipeline)
- Hors scope : urgences vitales immédiates (orienter vers les services d'urgence réels, pas vers l'agent)

## Entrées / Sorties
- **Entrée :** `user_input` (texte libre décrivant l'état du patient)
- **Sortie :**
  - `final_response` : rapport médical structuré (résumé, antécédents, niveau de risque, recommandations)
  - `final_alert` : message "URGENT" ou "PAS URGENT"
  - Journal JSON complet de l'exécution (`save_json_log`)

## Dépendances
- **Modèle LLM :** Groq — `llama-3.1-8b-instant` (température 0.1)
- **Framework :** LangGraph (`StateGraph`, `MemorySaver` pour checkpointing)
- **Librairies :** `langchain_groq`, `langchain_core`, `pymongo`

## Stockage du monitoring (persistance)
- Le monitoring (`monitoring.py`) stocke chaque exécution dans **MongoDB** (collection `runs`) si la variable d'environnement `MONGODB_URI` est configurée — l'historique survit alors aux redémarrages/redéploiements du service.
- Si `MONGODB_URI` est absente, ou si la connexion échoue au démarrage, le module bascule automatiquement sur un **cache en mémoire** (non persistant) — utilisé par défaut en développement local et dans les tests automatisés, sans nécessiter de base de données.
- Index unique sur `correlation_id` créé automatiquement à la connexion (`_MongoBackend.__init__`).

## Configuration sensible
- La clé API Groq est lue depuis la variable d'environnement `GROQ_API_KEY` (jamais codée en dur, voir `.env.example`).
- La chaîne de connexion MongoDB (`MONGODB_URI`, format `mongodb+srv://...`) est lue depuis une variable d'environnement, jamais committée dans Git.
- En production (Railway), `GROQ_API_KEY` et `MONGODB_URI` sont déclarées comme variables d'environnement dans l'onglet Variables de Railway.

## Contact / Responsable
- **Mainteneur :** Ichrak Elhantati, Fatima Ezzahra ELMENOUN, Hassan Boulahfa
- **Contact :** elhantatiichraq16@gmail.com
