"""
Agent de monitoring — Correlation ID + journal structure par execution.

Chaque appel a `start_run()` cree un correlation_id unique (UUID4).
Tous les noeuds du graphe LangGraph appellent `log_event()` avec ce meme
correlation_id, ce qui permet de retracer une execution complete
(latence par noeud, erreurs, statut final) a partir d'un seul identifiant,
y compris a travers l'API (header de reponse + endpoint /runs/{id}).
"""

import json
import os
import uuid
from datetime import datetime, timezone
from threading import Lock

MONITORING_DIR = os.path.join(os.path.dirname(__file__), "monitoring_logs")
os.makedirs(MONITORING_DIR, exist_ok=True)

_lock = Lock()
_runs: dict = {}  # correlation_id -> liste d'evenements (cache memoire pour l'API)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def start_run(correlation_id: str, user_input: str) -> None:
    with _lock:
        _runs[correlation_id] = {
            "correlation_id": correlation_id,
            "started_at": _now(),
            "user_input": user_input,
            "status": "running",
            "events": [],
        }
    _append_to_disk(correlation_id, {
        "type": "run_started",
        "correlation_id": correlation_id,
        "timestamp": _now(),
        "user_input": user_input,
    })


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
    with _lock:
        if correlation_id in _runs:
            _runs[correlation_id]["events"].append(event)
    _append_to_disk(correlation_id, event)


def end_run(correlation_id: str, status: str, summary: dict) -> None:
    with _lock:
        if correlation_id in _runs:
            _runs[correlation_id]["status"] = status
            _runs[correlation_id]["ended_at"] = _now()
            _runs[correlation_id]["summary"] = summary
    _append_to_disk(correlation_id, {
        "type": "run_ended",
        "correlation_id": correlation_id,
        "timestamp": _now(),
        "status": status,
        "summary": summary,
    })


def get_run(correlation_id: str) -> dict | None:
    with _lock:
        return _runs.get(correlation_id)


def list_runs() -> list:
    with _lock:
        return [
            {
                "correlation_id": r["correlation_id"],
                "status": r["status"],
                "started_at": r["started_at"],
                "nb_events": len(r["events"]),
            }
            for r in _runs.values()
        ]


def get_metrics() -> dict:
    """Agrege latence et tokens sur l'ensemble des runs connus, par noeud."""
    with _lock:
        runs = list(_runs.values())

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_to_disk(correlation_id: str, event: dict) -> None:
    path = os.path.join(MONITORING_DIR, f"{correlation_id}.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
