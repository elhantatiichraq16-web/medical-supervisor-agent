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
