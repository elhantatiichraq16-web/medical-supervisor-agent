"""
API FastAPI exposant le Medical-Supervisor-Agent.

Flux :
  POST /diagnose                    -> lance le graphe, s'arrete avant validation humaine
  POST /diagnose/{thread_id}/approve -> transmet la decision humaine, termine l'execution
  GET  /health                      -> sonde de disponibilite (utilisee par Render)
  GET  /runs/{correlation_id}       -> details de monitoring d'une execution
  GET  /runs                        -> liste des executions recentes
  GET  /metrics                     -> agregation latence/tokens/statuts (JSON)
  GET  /dashboard                   -> tableau de bord HTML (latence, tokens, Correlation ID)
"""

import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

import monitoring
from dashboard import render_dashboard
from supervisor_langgraph import start_diagnosis, approve_diagnosis

app = FastAPI(
    title="Medical Supervisor Agent API",
    version="1.0.0",
    description="Architecture multi-agents (pattern Supervisor) pour le secteur sante.",
)


class DiagnoseRequest(BaseModel):
    user_message: str
    thread_id: str | None = None


class ApproveRequest(BaseModel):
    approved: bool
    comment: str = ""


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/diagnose")
def diagnose(payload: DiagnoseRequest):
    thread_id = payload.thread_id or str(uuid.uuid4())
    if not payload.user_message.strip():
        raise HTTPException(status_code=400, detail="user_message est requis.")
    result = start_diagnosis(payload.user_message, thread_id)
    return result


@app.post("/diagnose/{thread_id}/approve")
def approve(thread_id: str, payload: ApproveRequest):
    try:
        result = approve_diagnosis(thread_id, payload.approved, payload.comment)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"thread_id inconnu ou expire : {exc}")
    return result


@app.get("/runs")
def runs():
    return monitoring.list_runs()


@app.get("/runs/{correlation_id}")
def run_detail(correlation_id: str):
    run = monitoring.get_run(correlation_id)
    if run is None:
        raise HTTPException(status_code=404, detail="correlation_id inconnu.")
    return run


@app.get("/metrics")
def metrics():
    return monitoring.get_metrics()


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return render_dashboard(monitoring.get_metrics(), monitoring.list_runs())
