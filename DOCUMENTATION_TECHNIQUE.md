# Documentation Technique — Medical Supervisor Agent

**Mini-projet : Architecture multi-agents (pattern Supervisor) — Secteur Santé**

## Équipe

- Ichrak Elhantati
- Fatima Ezzahra Elmenoum
- Hassan Boulahfa

**Date :** Juin 2026
**Dépôt GitHub :** https://github.com/elhantatiichraq16-web/medical-supervisor-agent
**Déploiement en production :** https://med-agent.up.railway.app

---

## 1. Présentation du projet

Le **Medical Supervisor Agent** est un système multi-agent (pattern **Supervisor**) qui analyse la description d'un patient, active dynamiquement des sous-agents spécialisés, génère un rapport médical structuré, le soumet à une validation humaine obligatoire (human-in-the-loop), puis route une alerte finale selon le niveau de risque détecté.

Le projet répond aux critères de validation suivants :

| Critère | Mise en œuvre |
|---|---|
| Observabilité | Correlation ID propagé à tous les nœuds, latence et tokens tracés |
| Tests | Suite pytest (29 tests), LLM mocké |
| Gouvernance | Agent Card + Runbook à jour |
| Conteneurisation et déploiement | Docker + déploiement Railway, API accessible publiquement |
| Incident | Runbook avec kill-switch et procédure de rollback |
| Documentation technique + démo | Ce document + dashboard de monitoring |

---

## 2. Architecture

```
Patient soumet sa description
        |
Supervisor Agent (decide quels agents activer)
        |
  [Parallèle] Symptoms Agent | Risk Agent | Medical History Agent
        |
Combine (fusion des 3 analyses)
        |
Healthcare Response Agent (rapport structuré)
        |
*** HUMAN-IN-THE-LOOP (interrupt_before) ***
   L'humain approuve ou refuse le rapport
        |
Audit Agent (vérifie la cohérence du niveau de risque)
        |
Risk Extractor ("Haut" / "Bas")
        |
SmartRouter
 ├─ Haut → High Risk Alert : "URGENT : consulter un médecin"
 └─ Bas  → Low Risk Alert  : "PAS URGENT"
        |
       END
```

Le diagramme BPMN complet est disponible dans [medical_supervisor_agent.bpmn](medical_supervisor_agent.bpmn) (importable dans [bpmn.io](https://bpmn.io)).

### Stack technique

| Composant | Technologie |
|---|---|
| Orchestration multi-agents | LangGraph (`StateGraph`, `MemorySaver`) |
| Modèle LLM | Groq — `llama-3.1-8b-instant` |
| API | FastAPI (`api.py`) |
| Monitoring | Module interne (`monitoring.py`) — Correlation ID, latence, tokens |
| Tableau de bord | Page HTML autonome (`dashboard.py`) |
| Tests | pytest (`tests/`), LLM mocké |
| CI/CD | GitHub Actions (`.github/workflows/ci.yml`) |
| Conteneurisation | Docker (`Dockerfile`) |
| Déploiement | Railway (build automatique depuis GitHub) |

---

## 3. Observabilité — Correlation ID, latence, tokens

Chaque exécution reçoit un identifiant unique (`correlation_id`, UUID) propagé à tous les nœuds du graphe. Chaque nœud loggue :
- son statut (`ok` / `error`)
- sa latence (`duration_ms`)
- les tokens Groq consommés (`input_tokens`, `output_tokens`, `total_tokens`)

### Capture — Détail d'une exécution réelle (`GET /runs/{correlation_id}`)

```json
{
    "correlation_id": "b0c8abcd-ec81-44c1-ae02-48d179caa4a3",
    "started_at": "2026-06-26T10:37:19.487162+00:00",
    "user_input": "Fievre a 39 depuis 2 jours, toux seche, diabete de type 2.",
    "status": "completed",
    "events": [
        {"node": "supervisor", "status": "ok", "duration_ms": 263.69,
         "tokens": {"input_tokens": 166, "output_tokens": 74, "total_tokens": 240}},
        {"node": "history", "status": "ok", "duration_ms": 164.27,
         "tokens": {"input_tokens": 115, "output_tokens": 34, "total_tokens": 149}},
        {"node": "symptoms", "status": "ok", "duration_ms": 179.02,
         "tokens": {"input_tokens": 128, "output_tokens": 48, "total_tokens": 176}},
        {"node": "risk", "status": "ok", "duration_ms": 290.89,
         "tokens": {"input_tokens": 104, "output_tokens": 97, "total_tokens": 201}},
        {"node": "combine", "status": "ok", "duration_ms": 0.04, "tokens": {}},
        {"node": "final_response", "status": "ok", "duration_ms": 412.37,
         "tokens": {"input_tokens": 345, "output_tokens": 190, "total_tokens": 535}},
        {"node": "human_review", "status": "ok", "duration_ms": 0.04, "tokens": {}},
        {"node": "audit", "status": "ok", "duration_ms": 990.94,
         "tokens": {"input_tokens": 353, "output_tokens": 382, "total_tokens": 735}},
        {"node": "risk_extractor", "status": "ok", "duration_ms": 249.5,
         "tokens": {"input_tokens": 476, "output_tokens": 3, "total_tokens": 479}},
        {"node": "high_risk_alert", "status": "ok", "duration_ms": 0.02, "tokens": {}}
    ],
    "ended_at": "2026-06-26T10:37:32.369704+00:00",
    "summary": {
        "risk_label": "Haut",
        "final_alert": "URGENT : Le patient doit visiter le medecin."
    }
}
```

On observe la propagation du même `correlation_id` sur les 10 nœuds traversés (Supervisor → 3 agents parallèles → Combine → Response → Human Review → Audit → Risk Extractor → High Risk Alert), avec latence et consommation de tokens individuelles par nœud.

### Capture — Métriques agrégées (`GET /metrics`), 5 exécutions cumulées

```json
{
    "nb_runs": 5,
    "status_counts": {"completed": 3, "rejected": 0, "running": 2},
    "total_tokens": {"input_tokens": 5777, "output_tokens": 2778, "total_tokens": 8555},
    "per_node": {
        "supervisor":      {"calls": 5, "errors": 0, "duration_ms_avg": 239.55, "total_tokens": 1147},
        "history":         {"calls": 5, "errors": 0, "duration_ms_avg": 32.88,  "total_tokens": 149},
        "symptoms":        {"calls": 5, "errors": 0, "duration_ms_avg": 233.05, "total_tokens": 850},
        "risk":            {"calls": 5, "errors": 0, "duration_ms_avg": 259.03, "total_tokens": 849},
        "combine":         {"calls": 5, "errors": 0, "duration_ms_avg": 0.06,   "total_tokens": 0},
        "final_response":  {"calls": 5, "errors": 0, "duration_ms_avg": 438.01, "total_tokens": 2251},
        "human_review":    {"calls": 3, "errors": 0, "duration_ms_avg": 0.04,   "total_tokens": 0},
        "audit":           {"calls": 3, "errors": 0, "duration_ms_avg": 779.69, "total_tokens": 2013},
        "risk_extractor":  {"calls": 3, "errors": 0, "duration_ms_avg": 185.26, "total_tokens": 1296},
        "high_risk_alert": {"calls": 3, "errors": 0, "duration_ms_avg": 0.09,   "total_tokens": 0}
    }
}
```

### Capture — Tableau de bord visuel (`GET /dashboard`)

Accessible en direct sur **https://med-agent.up.railway.app/dashboard** — affiche les mêmes métriques sous forme de cartes de synthèse (exécutions totales, complétées, rejetées, en cours, tokens) et de tableaux (latence/tokens par nœud, liste des Correlation ID), avec rafraîchissement automatique toutes les 15 secondes.

```
EXECUTIONS TOTALES : 5     COMPLETEES : 3     REJETEES : 0     EN COURS : 2
TOKENS TOTAUX : 8555       TOKENS ENTREE/SORTIE : 5777 / 2778

Latence et tokens par noeud du graphe
NOEUD             APPELS  ERREURS  LATENCE MOY. (ms)  TOKENS (in/out/total)
supervisor          5        0          239.55          796 / 351 / 1147
history              5        0           32.88          115 / 34 / 149
symptoms              5        0          233.05          606 / 244 / 850
risk                    5        0          259.03          486 / 363 / 849
combine               5        0            0.06              0 / 0 / 0
final_response       5        0          438.01        1479 / 772 / 2251
human_review          3        0            0.04              0 / 0 / 0
audit                   3        0          779.69        1008 / 1005 / 2013
risk_extractor        3        0          185.26        1287 / 9 / 1296
high_risk_alert       3        0            0.09              0 / 0 / 0
```

---

## 4. Tests automatisés

Suite de tests pytest (`tests/`), avec le LLM Groq mocké pour ne pas dépendre du réseau ou du quota API pendant l'exécution des tests.

### Capture — Exécution de la suite complète (`pytest tests/ -v`)

```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
collecting ... collected 29 items

tests/test_api.py::test_health_endpoint PASSED                           [  3%]
tests/test_api.py::test_root_redirects_to_dashboard PASSED               [  6%]
tests/test_api.py::test_diagnose_returns_report_awaiting_review PASSED   [ 10%]
tests/test_api.py::test_diagnose_rejects_empty_message PASSED            [ 13%]
tests/test_api.py::test_approve_completes_diagnosis PASSED               [ 17%]
tests/test_api.py::test_approve_unknown_thread_returns_404 PASSED        [ 20%]
tests/test_api.py::test_runs_list_endpoint PASSED                        [ 24%]
tests/test_api.py::test_run_detail_404_for_unknown_correlation_id PASSED [ 27%]
tests/test_api.py::test_metrics_endpoint_returns_aggregated_shape PASSED [ 31%]
tests/test_api.py::test_dashboard_endpoint_returns_html PASSED           [ 34%]
tests/test_monitoring.py::test_new_correlation_id_is_unique PASSED       [ 37%]
tests/test_monitoring.py::test_run_lifecycle_tracks_events_and_status PASSED [ 41%]
tests/test_monitoring.py::test_get_run_returns_none_for_unknown_id PASSED [ 44%]
tests/test_monitoring.py::test_list_runs_includes_started_run PASSED     [ 48%]
tests/test_monitoring.py::test_get_metrics_aggregates_tokens_and_latency_per_node PASSED [ 51%]
tests/test_supervisor_nodes.py::test_supervisor_node_activates_agents_from_llm_json PASSED [ 55%]
tests/test_supervisor_nodes.py::test_symptoms_node_skipped_when_inactive PASSED [ 58%]
tests/test_supervisor_nodes.py::test_combine_node_merges_three_results PASSED [ 62%]
tests/test_supervisor_nodes.py::test_risk_extractor_node_extracts_haut PASSED [ 65%]
tests/test_supervisor_nodes.py::test_risk_extractor_node_extracts_bas PASSED [ 68%]
tests/test_supervisor_nodes.py::test_route_by_risk_routes_to_high_risk_alert PASSED [ 72%]
tests/test_supervisor_nodes.py::test_route_by_risk_routes_to_low_risk_alert PASSED [ 75%]
tests/test_supervisor_nodes.py::test_high_risk_alert_node_sets_urgent_message PASSED [ 79%]
tests/test_supervisor_nodes.py::test_low_risk_alert_node_sets_non_urgent_message PASSED [ 82%]
tests/test_supervisor_nodes.py::test_extract_json_parses_embedded_json PASSED [ 86%]
tests/test_supervisor_nodes.py::test_extract_json_returns_empty_dict_on_invalid_input PASSED [ 89%]
tests/test_supervisor_nodes.py::test_extract_tokens_reads_usage_metadata PASSED [ 93%]
tests/test_supervisor_nodes.py::test_extract_tokens_returns_empty_when_unavailable PASSED [ 96%]
tests/test_supervisor_nodes.py::test_monitored_decorator_extracts_and_strips_last_tokens PASSED [100%]

============================= 29 passed in 2.41s ==============================
```

**Couverture des tests :**
- `test_supervisor_nodes.py` : nœuds du graphe (Supervisor, Symptoms, Combine, Risk Extractor, alertes), extraction JSON, extraction de tokens
- `test_monitoring.py` : cycle de vie d'une exécution (Correlation ID), agrégation des métriques
- `test_api.py` : endpoints FastAPI (`/health`, `/diagnose`, `/approve`, `/runs`, `/metrics`, `/dashboard`)

### Pipeline CI/CD — GitHub Actions

Le pipeline (`.github/workflows/ci.yml`) s'exécute à chaque push/PR :
1. Installation des dépendances
2. Exécution de la suite pytest
3. Build de l'image Docker (vérifie que le `Dockerfile` reste valide)

Statut visible sur : https://github.com/elhantatiichraq16-web/medical-supervisor-agent/actions

---

## 5. Conteneurisation Docker

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}
```

### Capture — Build de l'image (`docker build -t medical-supervisor-agent:test .`)

```
#1 [internal] load build definition from Dockerfile
#1 DONE 0.1s

#6 [1/5] FROM docker.io/library/python:3.11-slim@sha256:cdbd05fb6f457ca275ff51ce00d93d865ca0b6a25f5ffb08262d94f6835771e5
#6 DONE 0.2s

#7 [2/5] WORKDIR /app
#7 CACHED

#8 [3/5] COPY requirements.txt .
#8 CACHED

#9 [4/5] RUN pip install --no-cache-dir -r requirements.txt
#9 CACHED

#10 [5/5] COPY . .
#10 DONE 0.3s

#11 exporting to image
#11 naming to docker.io/library/medical-supervisor-agent:test done
#11 DONE 0.7s
```

### Capture — Image construite (`docker images`)

```
REPOSITORY                 TAG       SIZE      CREATED AT
medical-supervisor-agent   test      323MB     2026-06-26 10:19:00 +0100
```

### Capture — Conteneur en cours d'exécution (`docker ps`)

```
NAMES                     IMAGE                           STATUS             PORTS
medical-supervisor-demo   medical-supervisor-agent:test   Up About an hour   0.0.0.0:8000->8000/tcp
```

Le conteneur expose l'API sur le port 8000, accessible localement via `http://localhost:8000` pendant les tests de développement, avant déploiement sur Railway.

---

## 6. Déploiement en production (Railway)

L'API est déployée sur **Railway**, à partir du `Dockerfile` du dépôt GitHub. Chaque push sur la branche `master` déclenche un nouveau build et déploiement automatique (CI/CD continu).

> **Note sur le choix de la plateforme :** Render (cité comme exemple dans l'énoncé) et Fly.io exigent tous deux l'enregistrement d'une carte bancaire avant de pouvoir créer le moindre service, même gratuit (vérification anti-abus). Railway a été retenu comme alternative équivalente (build Docker depuis GitHub, déploiement automatique, health check) sans cette contrainte.

**URL publique :** https://med-agent.up.railway.app
**Documentation interactive (Swagger) :** https://med-agent.up.railway.app/docs
**Tableau de bord :** https://med-agent.up.railway.app/dashboard

### Capture — Test du endpoint `/health` en production

```
GET https://med-agent.up.railway.app/health
→ HTTP 200
{"status": "ok"}
```

### Capture — Test complet `/diagnose` en production

```json
POST https://med-agent.up.railway.app/diagnose
Body: {"user_message": "Fievre a 39 depuis 2 jours, toux seche, diabete de type 2.", "thread_id": "doc-tech-demo"}

→ HTTP 200
{
    "thread_id": "doc-tech-demo",
    "correlation_id": "b0c8abcd-ec81-44c1-ae02-48d179caa4a3",
    "final_response": "Patient Summary:\nThe patient is experiencing moderate symptoms of fever and dry cough for 2 days. These symptoms may be indicative of a respiratory infection.\n\nMedical History:\nThe patient has a pre-existing condition of type 2 diabetes, which may increase their susceptibility to infections.\n\nRisk Level:\nMedium risk. The combination of fever, dry cough, and pre-existing diabetes may indicate a potential infection...\n\nRecommendations:\nWe strongly recommend that the patient consult a doctor as soon as possible...",
    "supervisor_reason": "Fievre et toux seche peuvent indiquer une infection, le diabete de type 2 est une condition de sante preexistante qui peut influencer le traitement",
    "status": "awaiting_human_review"
}
```

### Capture — Validation humaine et résultat final (`/approve`)

```json
POST https://med-agent.up.railway.app/diagnose/doc-tech-demo/approve
Body: {"approved": true, "comment": "Documentation technique - test demo"}

→ HTTP 200
{
    "thread_id": "doc-tech-demo",
    "correlation_id": "b0c8abcd-ec81-44c1-ae02-48d179caa4a3",
    "status": "completed",
    "risk_label": "Haut",
    "final_alert": "URGENT : Le patient doit visiter le medecin.",
    "final_response": "..."
}
```

Ce test illustre le flux complet : Supervisor → 3 agents en parallèle → rapport → validation humaine → audit → routage SmartRouter → alerte `URGENT` (cohérent avec la gravité des symptômes : fièvre élevée + diabète préexistant).

---

## 7. Gouvernance — Agent Card et Runbook

- **[AGENT_CARD.md](AGENT_CARD.md)** : identité de l'agent, architecture, capacités, API, dépendances, configuration sensible (clé API jamais committée).
- **[RUNBOOK.md](RUNBOOK.md)** : procédure de kill-switch (délai cible < 5 min), signaux de détection d'incident (y compris via le monitoring `GET /runs/{correlation_id}`), procédure de rollback (`git checkout <tag>`), plan d'escalade.

---

## 8. Comment reproduire les tests

```bash
# Cloner le depot
git clone https://github.com/elhantatiichraq16-web/medical-supervisor-agent.git
cd medical-supervisor-agent

# Tests automatises
pip install -r requirements-dev.txt
pytest tests/ -v

# Build et run Docker en local
docker build -t medical-supervisor-agent:test .
docker run -d --name medical-supervisor-demo \
  -e GROQ_API_KEY="votre_cle_groq" \
  -p 8000:8000 medical-supervisor-agent:test

# Test de l'API en local
curl http://localhost:8000/health
```

Pour tester l'instance déployée en production, voir la section "Comment tester" du [README.md](README.md).

---

## 9. Diagramme BPMN

Le flux métier complet (Patient → Supervisor → agents parallèles → validation humaine → audit → routage → alerte) est modélisé dans [medical_supervisor_agent.bpmn](medical_supervisor_agent.bpmn), importable directement dans [bpmn.io](https://bpmn.io) pour visualisation.
