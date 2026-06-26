from unittest.mock import patch

from fastapi.testclient import TestClient

import api


client = TestClient(api.app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_diagnose_returns_report_awaiting_review():
    fake_result = {
        "thread_id": "thread-1",
        "correlation_id": "corr-1",
        "final_response": "Patient Summary: ...",
        "supervisor_reason": "Symptomes pertinents.",
        "status": "awaiting_human_review",
    }
    with patch.object(api, "start_diagnosis", return_value=fake_result):
        response = client.post("/diagnose", json={"user_message": "fievre", "thread_id": "thread-1"})

    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_human_review"


def test_diagnose_rejects_empty_message():
    response = client.post("/diagnose", json={"user_message": "   "})
    assert response.status_code == 400


def test_approve_completes_diagnosis():
    fake_result = {
        "thread_id": "thread-1",
        "correlation_id": "corr-1",
        "status": "completed",
        "risk_label": "Bas",
        "final_alert": "PAS URGENT",
    }
    with patch.object(api, "approve_diagnosis", return_value=fake_result):
        response = client.post("/diagnose/thread-1/approve", json={"approved": True})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_approve_unknown_thread_returns_404():
    with patch.object(api, "approve_diagnosis", side_effect=KeyError("thread-x")):
        response = client.post("/diagnose/thread-x/approve", json={"approved": True})
    assert response.status_code == 404


def test_runs_list_endpoint():
    response = client.get("/runs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_run_detail_404_for_unknown_correlation_id():
    response = client.get("/runs/unknown-id")
    assert response.status_code == 404


def test_metrics_endpoint_returns_aggregated_shape():
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "nb_runs" in body
    assert "total_tokens" in body
    assert "per_node" in body


def test_dashboard_endpoint_returns_html():
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Dashboard de monitoring" in response.text
