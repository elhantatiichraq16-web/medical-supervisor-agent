"""
Agent de monitoring — Correlation ID + journal structure par execution.

Chaque appel a `start_run()` cree un correlation_id unique (UUID4).
Tous les noeuds du graphe LangGraph appellent `log_event()` avec ce meme
correlation_id, ce qui permet de retracer une execution complete
(latence par noeud, erreurs, statut final) a partir d'un seul identifiant,
y compris a travers l'API (endpoint /runs/{id}, /metrics, /dashboard).

Stockage : MongoDB si la variable d'environnement MONGODB_URI est definie
(persistant, survit aux redemarrages/redeploiements) — sinon repli
automatique sur un cache en memoire (utilise par les tests et en
developpement local sans base de donnees).
"""

import os
import uuid
from datetime import datetime, timezone
from threading import Lock


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _MemoryBackend:
    """Stockage en memoire (non persistant) — repli quand MONGODB_URI est absent."""

    def __init__(self):
        self._lock = Lock()
        self._runs: dict = {}

    def start_run(self, correlation_id: str, user_input: str) -> None:
        with self._lock:
            self._runs[correlation_id] = {
                "correlation_id": correlation_id,
                "started_at": _now(),
                "user_input": user_input,
                "status": "running",
                "events": [],
            }

    def log_event(self, correlation_id: str, event: dict) -> None:
        with self._lock:
            if correlation_id in self._runs:
                self._runs[correlation_id]["events"].append(event)

    def end_run(self, correlation_id: str, status: str, summary: dict) -> None:
        with self._lock:
            if correlation_id in self._runs:
                self._runs[correlation_id]["status"] = status
                self._runs[correlation_id]["ended_at"] = _now()
                self._runs[correlation_id]["summary"] = summary

    def get_run(self, correlation_id: str) -> dict | None:
        with self._lock:
            return self._runs.get(correlation_id)

    def list_runs(self) -> list:
        with self._lock:
            return list(self._runs.values())


class _MongoBackend:
    """Stockage persistant dans MongoDB (collection 'runs' de la base configuree)."""

    def __init__(self, uri: str):
        from pymongo import MongoClient

        db_name = os.environ.get("MONGODB_DB", "medical_supervisor_agent")
        self._client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self._collection = self._client[db_name]["runs"]
        self._collection.create_index("correlation_id", unique=True)

    def start_run(self, correlation_id: str, user_input: str) -> None:
        self._collection.insert_one({
            "correlation_id": correlation_id,
            "started_at": _now(),
            "user_input": user_input,
            "status": "running",
            "events": [],
        })

    def log_event(self, correlation_id: str, event: dict) -> None:
        self._collection.update_one(
            {"correlation_id": correlation_id},
            {"$push": {"events": event}},
        )

    def end_run(self, correlation_id: str, status: str, summary: dict) -> None:
        self._collection.update_one(
            {"correlation_id": correlation_id},
            {"$set": {"status": status, "ended_at": _now(), "summary": summary}},
        )

    def get_run(self, correlation_id: str) -> dict | None:
        doc = self._collection.find_one({"correlation_id": correlation_id}, {"_id": 0})
        return doc

    def list_runs(self) -> list:
        return list(self._collection.find({}, {"_id": 0}))


def _build_backend():
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        return _MemoryBackend()
    try:
        backend = _MongoBackend(uri)
        backend._client.admin.command("ping")
        return backend
    except Exception:
        return _MemoryBackend()


_backend = _build_backend()


def start_run(correlation_id: str, user_input: str) -> None:
    _backend.start_run(correlation_id, user_input)


def log_event(correlation_id: str, node: str, status: str, duration_ms: float, detail: str = "",
              tokens: dict | None = None) -> None:
    event = {
        "correlation_id": correlation_id,
        "node": node,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "detail": detail[:300],
        "tokens": tokens or {},
        "timestamp": _now(),
    }
    _backend.log_event(correlation_id, event)


def end_run(correlation_id: str, status: str, summary: dict) -> None:
    _backend.end_run(correlation_id, status, summary)


def get_run(correlation_id: str) -> dict | None:
    return _backend.get_run(correlation_id)


def list_runs() -> list:
    runs = _backend.list_runs()
    return [
        {
            "correlation_id": r["correlation_id"],
            "status": r["status"],
            "started_at": r["started_at"],
            "nb_events": len(r["events"]),
        }
        for r in runs
    ]


def get_metrics() -> dict:
    """Agrege latence et tokens sur l'ensemble des runs connus, par noeud."""
    runs = _backend.list_runs()

    per_node: dict = {}
    total_tokens = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    status_counts = {"completed": 0, "rejected": 0, "running": 0}

    for run in runs:
        status_counts[run["status"]] = status_counts.get(run["status"], 0) + 1
        for event in run["events"]:
            node = event["node"]
            stats = per_node.setdefault(node, {
                "calls": 0, "errors": 0, "duration_ms_total": 0.0,
                "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            })
            stats["calls"] += 1
            if event["status"] == "error":
                stats["errors"] += 1
            stats["duration_ms_total"] += event["duration_ms"]
            tokens = event.get("tokens") or {}
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                stats[key] += tokens.get(key, 0)
                total_tokens[key] += tokens.get(key, 0)

    for node, stats in per_node.items():
        stats["duration_ms_avg"] = round(stats["duration_ms_total"] / stats["calls"], 2) if stats["calls"] else 0
        stats["duration_ms_total"] = round(stats["duration_ms_total"], 2)

    return {
        "nb_runs": len(runs),
        "status_counts": status_counts,
        "total_tokens": total_tokens,
        "per_node": per_node,
    }
