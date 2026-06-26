from unittest.mock import MagicMock, patch

import monitoring


def test_new_correlation_id_is_unique():
    a = monitoring.new_correlation_id()
    b = monitoring.new_correlation_id()
    assert a != b


def test_run_lifecycle_tracks_events_and_status():
    correlation_id = monitoring.new_correlation_id()
    monitoring.start_run(correlation_id, "patient test")
    monitoring.log_event(correlation_id, "supervisor", "ok", 12.3)
    monitoring.log_event(correlation_id, "symptoms", "ok", 45.6)
    monitoring.end_run(correlation_id, "completed", {"risk_label": "Bas"})

    run = monitoring.get_run(correlation_id)
    assert run["status"] == "completed"
    assert len(run["events"]) == 2
    assert run["events"][0]["node"] == "supervisor"
    assert run["summary"]["risk_label"] == "Bas"


def test_get_run_returns_none_for_unknown_id():
    assert monitoring.get_run("does-not-exist") is None


def test_list_runs_includes_started_run():
    correlation_id = monitoring.new_correlation_id()
    monitoring.start_run(correlation_id, "patient test 2")
    ids = [r["correlation_id"] for r in monitoring.list_runs()]
    assert correlation_id in ids


def test_get_metrics_aggregates_tokens_and_latency_per_node():
    correlation_id = monitoring.new_correlation_id()
    monitoring.start_run(correlation_id, "patient test 3")
    monitoring.log_event(correlation_id, "metrics_test_node", "ok", 100.0,
                          tokens={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    monitoring.log_event(correlation_id, "metrics_test_node", "error", 50.0)
    monitoring.end_run(correlation_id, "completed", {})

    metrics = monitoring.get_metrics()
    node_stats = metrics["per_node"]["metrics_test_node"]
    assert node_stats["calls"] == 2
    assert node_stats["errors"] == 1
    assert node_stats["total_tokens"] == 15
    assert node_stats["duration_ms_avg"] == 75.0


def test_build_backend_falls_back_to_memory_when_no_mongodb_uri():
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("MONGODB_URI", None)
        backend = monitoring._build_backend()
    assert isinstance(backend, monitoring._MemoryBackend)


def test_build_backend_falls_back_to_memory_when_mongodb_unreachable():
    with patch.dict("os.environ", {"MONGODB_URI": "mongodb+srv://invalid:invalid@unreachable.example.net/test"}):
        backend = monitoring._build_backend()
    assert isinstance(backend, monitoring._MemoryBackend)


def test_memory_backend_lifecycle():
    backend = monitoring._MemoryBackend()
    backend.start_run("corr-mem-1", "patient")
    backend.log_event("corr-mem-1", {"node": "n1", "status": "ok"})
    backend.end_run("corr-mem-1", "completed", {"x": 1})

    run = backend.get_run("corr-mem-1")
    assert run["status"] == "completed"
    assert len(run["events"]) == 1
    assert any(r["correlation_id"] == "corr-mem-1" for r in backend.list_runs())


def test_mongo_backend_delegates_to_pymongo_collection():
    fake_collection = MagicMock()
    fake_client = MagicMock()
    fake_client.__getitem__.return_value.__getitem__.return_value = fake_collection

    with patch("pymongo.MongoClient", return_value=fake_client):
        backend = monitoring._MongoBackend("mongodb+srv://fake")

    backend.start_run("corr-mongo-1", "patient")
    fake_collection.insert_one.assert_called_once()

    backend.log_event("corr-mongo-1", {"node": "n1"})
    fake_collection.update_one.assert_any_call(
        {"correlation_id": "corr-mongo-1"}, {"$push": {"events": {"node": "n1"}}}
    )

    backend.end_run("corr-mongo-1", "completed", {"risk_label": "Bas"})
    assert fake_collection.update_one.call_count == 2
    end_call_args = fake_collection.update_one.call_args_list[1]
    assert end_call_args[0][0] == {"correlation_id": "corr-mongo-1"}
    assert end_call_args[0][1]["$set"]["status"] == "completed"
    assert end_call_args[0][1]["$set"]["summary"] == {"risk_label": "Bas"}

    fake_collection.find_one.return_value = {"correlation_id": "corr-mongo-1", "status": "completed"}
    result = backend.get_run("corr-mongo-1")
    assert result == {"correlation_id": "corr-mongo-1", "status": "completed"}

    fake_collection.find.return_value = [{"correlation_id": "corr-mongo-1"}]
    assert backend.list_runs() == [{"correlation_id": "corr-mongo-1"}]
