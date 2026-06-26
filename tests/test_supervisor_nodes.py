"""
Tests unitaires des noeuds du graphe Supervisor.
Le LLM Groq est mocke pour ne pas dependre du reseau/quota pendant la CI.
"""

import json
from contextlib import contextmanager

import supervisor_langgraph as sup


class FakeLLMResponse:
    def __init__(self, content: str):
        self.content = content


def fake_invoke_factory(content: str):
    def fake_invoke(messages):
        return FakeLLMResponse(content)
    return fake_invoke


@contextmanager
def mocked_llm(content: str):
    """sup.llm est un objet pydantic 'frozen' : patch.object echoue car il
    essaie de delattr l'attribut a la sortie. On sauvegarde/restaure
    l'attribut manuellement via __dict__ pour contourner ce comportement."""
    original = sup.llm.invoke
    sup.llm.__dict__["invoke"] = fake_invoke_factory(content)
    try:
        yield
    finally:
        sup.llm.__dict__["invoke"] = original


def base_state(**overrides) -> dict:
    state = {
        "correlation_id": "test-correlation-id",
        "user_input": "J'ai de la fievre et une toux seche.",
        "activate_symptoms": True,
        "activate_risk": True,
        "activate_history": True,
        "supervisor_reason": "",
        "symptoms_result": "",
        "risk_result": "",
        "history_result": "",
        "combined_text": "",
        "final_response": "",
        "human_approved": False,
        "human_comment": "",
        "audit_result": "",
        "risk_label": "",
        "final_alert": "",
    }
    state.update(overrides)
    return state


def test_supervisor_node_activates_agents_from_llm_json():
    content = json.dumps({
        "activate_symptom_agent": True,
        "activate_risk_agent": False,
        "activate_medical_history_agent": True,
        "reason": "Symptomes et antecedents pertinents.",
    })
    with mocked_llm(content):
        result = sup.supervisor_node(base_state())

    assert result["activate_symptoms"] is True
    assert result["activate_risk"] is False
    assert result["activate_history"] is True
    assert "antecedents" in result["supervisor_reason"]


def test_symptoms_node_skipped_when_inactive():
    state = base_state(activate_symptoms=False)
    result = sup.symptoms_node(state)
    assert result["symptoms_result"] == "{}"


def test_combine_node_merges_three_results():
    state = base_state(
        symptoms_result='{"symptoms": ["fievre"]}',
        risk_result='{"risk_level": "medium"}',
        history_result='{"chronic_conditions": []}',
    )
    result = sup.combine_node(state)
    assert "SYMPTOMS ANALYSIS" in result["combined_text"]
    assert "RISK ASSESSMENT" in result["combined_text"]
    assert "MEDICAL HISTORY" in result["combined_text"]


def test_risk_extractor_node_extracts_haut():
    state = base_state(audit_result="Niveau de risque evalue : Haut")
    with mocked_llm("Haut"):
        result = sup.risk_extractor_node(state)
    assert result["risk_label"] == "Haut"


def test_risk_extractor_node_extracts_bas():
    state = base_state(audit_result="Niveau de risque evalue : Bas")
    with mocked_llm("Bas"):
        result = sup.risk_extractor_node(state)
    assert result["risk_label"] == "Bas"


def test_route_by_risk_routes_to_high_risk_alert():
    state = base_state(risk_label="Haut")
    assert sup.route_by_risk(state) == "high_risk_alert"


def test_route_by_risk_routes_to_low_risk_alert():
    state = base_state(risk_label="Bas")
    assert sup.route_by_risk(state) == "low_risk_alert"


def test_high_risk_alert_node_sets_urgent_message():
    result = sup.high_risk_alert_node(base_state(risk_label="Haut"))
    assert result["final_alert"] == sup.HIGH_RISK_SYSTEM


def test_low_risk_alert_node_sets_non_urgent_message():
    result = sup.low_risk_alert_node(base_state(risk_label="Bas"))
    assert result["final_alert"] == sup.LOW_RISK_SYSTEM


def test_extract_json_parses_embedded_json():
    text = 'Voici la reponse : {"a": 1, "b": "ok"} merci.'
    data = sup.extract_json(text)
    assert data == {"a": 1, "b": "ok"}


def test_extract_json_returns_empty_dict_on_invalid_input():
    assert sup.extract_json("pas de json ici") == {}


def test_extract_tokens_reads_usage_metadata():
    class FakeResponse:
        usage_metadata = {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19}
        response_metadata = {}

    tokens = sup.extract_tokens(FakeResponse())
    assert tokens == {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19}


def test_extract_tokens_returns_empty_when_unavailable():
    class FakeResponse:
        usage_metadata = None
        response_metadata = {}

    assert sup.extract_tokens(FakeResponse()) == {}


def test_monitored_decorator_extracts_and_strips_last_tokens(monkeypatch):
    """Le wrapper @monitored doit extraire _last_tokens du dict retourne par
    le noeud (pour le monitoring) et NE PAS le laisser dans le state final."""
    captured = {}

    def fake_log_event(correlation_id, node, status, duration_ms, detail="", tokens=None):
        captured["tokens"] = tokens

    monkeypatch.setattr(sup.monitoring, "log_event", fake_log_event)

    @sup.monitored("fake_node")
    def fake_node(state):
        return {"some_field": "value", "_last_tokens": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}}

    result = fake_node(base_state())

    assert "_last_tokens" not in result
    assert captured["tokens"] == {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}
