---
title: Medical Supervisor Agent
emoji: 🩺
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8000
pinned: false
---

# Medical Supervisor Agent

Architecture multi-agents (pattern Supervisor) pour le secteur santé — LangGraph, FastAPI, monitoring (Correlation ID, latence, tokens), CI/CD, conteneurisation Docker.

Voir [AGENT_CARD.md](AGENT_CARD.md) et [RUNBOOK.md](RUNBOOK.md) pour la documentation complète.

## Endpoints

- `POST /diagnose` — lance le diagnostic, s'arrête avant validation humaine
- `POST /diagnose/{thread_id}/approve` — valide et termine l'exécution
- `GET /health` — sonde de disponibilité
- `GET /dashboard` — tableau de bord (latence, tokens, Correlation ID)
- `GET /metrics` — métriques agrégées (JSON)

## Variable d'environnement requise

- `GROQ_API_KEY` — à configurer dans les "Secrets" du Space (Settings → Variables and secrets).
