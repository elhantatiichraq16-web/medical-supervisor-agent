"""
Pattern SUPERVISOR avec LangGraph
Equivalent du workflow Langflow supervisor_khaoula.json

Flux complet :
  ChatInput
      |
  Supervisor Agent  ->  decide quels agents activer (JSON)
      |
  [Parallele] Symptoms | Risk | Medical History
      |
  Combine
      |
  Healthcare Response Agent  ->  rapport medical structure
      |
  *** HUMAN-IN-THE-LOOP  (interrupt_before) ***
  L'humain lit le rapport et approuve ou modifie
      |
  Audit Agent         ->  verifie coherence du niveau de risque
      |
  Risk Extractor      ->  extrait "Haut" ou "Bas"
      |
  SmartRouter (add_conditional_edges)
  |-- Haut  ->  High Risk Alert  : "URGENT : Le patient doit visiter le medecin."
  |-- Bas   ->  Low Risk Alert   : "PAS URGENT : Vous pouvez suivre la prospection."
      |
  END
"""

import json
import re
import os
import time
from datetime import datetime
from typing import TypedDict, Annotated

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

import monitoring

# Journal JSON global — rempli par chaque noeud pendant l'execution
_node_journal: list = []

def log_node(node_name: str, input_data: dict, output_data: dict):
    """Enregistre l'entree et la sortie d'un noeud dans le journal JSON."""
    _node_journal.append({
        "noeud":     node_name,
        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "entree":    input_data,
        "sortie":    output_data,
    })

def save_json_log(json_path: str, thread_id: str, user_message: str):
    """Sauvegarde le journal complet dans un fichier .json structure."""
    data = {
        "session":     datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "thread_id":   thread_id,
        "patient":     user_message,
        "nb_noeuds":   len(_node_journal),
        "noeuds":      _node_journal,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def reset_journal():
    """Vide le journal entre deux cas patients."""
    _node_journal.clear()

# ===========================================================
# 1. ETAT PARTAGE (SupervisorState)
# ===========================================================

def keep_last(a, b):
    return b

class SupervisorState(TypedDict):
    # monitoring — identifiant unique propage a tous les noeuds
    correlation_id: str

    # entree utilisateur
    user_input: str

    # decisions du supervisor
    activate_symptoms: bool
    activate_risk: bool
    activate_history: bool
    supervisor_reason: str

    # resultats des sous-agents (reducer pour la mise a jour parallele)
    symptoms_result: Annotated[str, keep_last]
    risk_result:     Annotated[str, keep_last]
    history_result:  Annotated[str, keep_last]

    # synthese
    combined_text:  str
    final_response: str

    # human-in-the-loop
    human_approved:  bool
    human_comment:   str   # commentaire optionnel de l'humain

    # pipeline post-approbation (supervisor_khaoula.json)
    audit_result: str
    risk_label:   str   # "Haut" ou "Bas"
    final_alert:  str   # message URGENT ou PAS URGENT


# ===========================================================
# 2. MODELE GROQ
# ===========================================================

GROQ_API_KEY = os.environ["GROQ_API_KEY"]

llm = ChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0.1,
    api_key=GROQ_API_KEY,
)


# ===========================================================
# 3. PROMPTS
# ===========================================================

SUPERVISOR_PROMPT = """You are a Supervisor Agent coordinating a medical multi-agent system.

Available agents:
- Symptoms_Agent      : analyzes symptoms
- Risk_Agent          : evaluates risk level
- Medical_History_Agent : reviews medical history

Decide which agents to activate based on the patient message.
Return ONLY valid JSON — no explanation, no markdown.

{
  "activate_symptom_agent": true,
  "activate_risk_agent": true,
  "activate_medical_history_agent": true,
  "reason": "short justification here"
}"""

SYMPTOMS_PROMPT = """You are a Symptoms Analysis Agent.
Analyze the patient description and extract key medical information.
Return ONLY valid JSON.

{
  "symptoms": ["symptom1", "symptom2"],
  "duration": "X days",
  "severity": "low|moderate|high",
  "observations": "any important notes"
}"""

RISK_PROMPT = """You are a Risk Assessment Agent.
Evaluate the patient's risk level based on described symptoms.
Return ONLY valid JSON.

{
  "risk_level": "low|medium|high",
  "reason": "brief justification"
}"""

HISTORY_PROMPT = """You are a Medical History Analysis Agent.
Identify chronic conditions, past illnesses, and risk factors.
Return ONLY valid JSON.

{
  "chronic_conditions": ["condition1"],
  "previous_conditions": ["illness1"],
  "risk_factors": ["factor1"]
}"""

RESPONSE_PROMPT = """You are a Healthcare Response Agent.

You receive the combined output of three medical analysis agents:
1. Symptoms analysis
2. Risk assessment
3. Medical history

Generate a clear, structured health summary for the patient.

Rules:
- Do NOT give a definitive diagnosis.
- Be professional and concise.
- Always recommend seeing a doctor when appropriate.

Format your response exactly like this:

Patient Summary:
[summary of symptoms]

Medical History:
[relevant history]

Risk Level:
[assessed risk with justification]

Recommendations:
[actionable next steps]"""

# Prompt PeQ6f — Audit Agent
AUDIT_PROMPT = """Role : Expert en audit de systemes IA sante.

Objectif : Evaluer si le niveau de risque dans le rapport ci-dessous est coherent avec les symptomes decrits. Identifier toute contradiction ou sous-estimation du risque.

Rapport a auditer :
{llm_response}

Instrustions :
- Analyser objectivement le rapport.
- Verifier la coherence entre symptomes et niveau de risque annonce.
- Conclure OBLIGATOIREMENT par l'une de ces deux phrases exactes :
  "Niveau de risque evalue : Haut"
  "Niveau de risque evalue : Bas"
"""

# Prompt glNjT — Risk Extractor
RISK_EXTRACTOR_PROMPT = """Role : Extracteur de niveau de risque.

Consigne STRICTE : Ta reponse doit contenir UNIQUEMENT un seul mot.
Soit : Haut
Soit : Bas

Aucune ponctuation, aucune explication, aucun autre mot.

Texte a analyser :
{reponse_llm}
"""

# Messages d'alerte (GroqModel-aRMzd et GroqModel-G6oOV)
HIGH_RISK_SYSTEM = "URGENT : Le patient doit visiter le medecin."
LOW_RISK_SYSTEM  = "PAS URGENT : Vous pouvez suivre la prospection."


# ===========================================================
# 4. HELPER
# ===========================================================

def extract_json(text: str) -> dict:
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except (json.JSONDecodeError, AttributeError):
        pass
    return {}

def banner(title: str, char: str = "=", width: int = 62):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")

def step(tag: str, msg: str):
    print(f"\n  [{tag}] {msg}")


def monitored(node_name: str):
    """Decorateur : mesure la duree d'un noeud et l'enregistre dans le
    monitoring (Correlation ID), en plus du journal JSON existant."""
    def decorator(fn):
        def wrapper(state: SupervisorState):
            correlation_id = state.get("correlation_id", "")
            t0 = time.perf_counter()
            try:
                result = fn(state)
                duration_ms = (time.perf_counter() - t0) * 1000
                monitoring.log_event(correlation_id, node_name, "ok", duration_ms)
                return result
            except Exception as exc:
                duration_ms = (time.perf_counter() - t0) * 1000
                monitoring.log_event(correlation_id, node_name, "error", duration_ms, detail=str(exc))
                raise
        return wrapper
    return decorator


# ===========================================================
# 5. NOEUDS DU GRAPHE
# ===========================================================

@monitored("supervisor")
def supervisor_node(state: SupervisorState) -> SupervisorState:
    """GroqModel-etZFh : Supervisor — decide quels agents activer."""
    step("SUPERVISOR", "Analyse de la demande patient...")

    response = llm.invoke([
        SystemMessage(content=SUPERVISOR_PROMPT),
        HumanMessage(content=state["user_input"]),
    ])
    data = extract_json(response.content)

    activate_symptoms = bool(data.get("activate_symptom_agent", True))
    activate_risk     = bool(data.get("activate_risk_agent", True))
    activate_history  = bool(data.get("activate_medical_history_agent", True))
    reason            = data.get("reason", "—")

    print(f"         Symptoms : {'ON' if activate_symptoms else 'OFF'}")
    print(f"         Risk     : {'ON' if activate_risk else 'OFF'}")
    print(f"         History  : {'ON' if activate_history else 'OFF'}")
    print(f"         Raison   : {reason}")

    log_node("supervisor", {"user_input": state["user_input"]}, {
        "activate_symptoms": activate_symptoms,
        "activate_risk":     activate_risk,
        "activate_history":  activate_history,
        "reason":            reason,
        "llm_raw":           response.content,
    })

    return {
        **state,
        "activate_symptoms": activate_symptoms,
        "activate_risk":     activate_risk,
        "activate_history":  activate_history,
        "supervisor_reason": reason,
    }


@monitored("symptoms")
def symptoms_node(state: SupervisorState) -> dict:
    """GroqModel-FYDy9 : Symptoms Agent."""
    if not state.get("activate_symptoms", True):
        step("SYMPTOMS", "Desactive par le supervisor.")
        log_node("symptoms", {"active": False}, {"symptoms_result": "{}"})
        return {"symptoms_result": "{}"}

    step("SYMPTOMS AGENT", "Analyse des symptomes en cours...")
    response = llm.invoke([
        SystemMessage(content=SYMPTOMS_PROMPT),
        HumanMessage(content=state["user_input"]),
    ])
    print(f"         Extrait : {response.content[:80]}...")
    log_node("symptoms", {"user_input": state["user_input"]}, {"symptoms_result": response.content})
    return {"symptoms_result": response.content}


@monitored("risk")
def risk_node(state: SupervisorState) -> dict:
    """GroqModel-ummXV : Risk Agent."""
    if not state.get("activate_risk", True):
        step("RISK", "Desactive par le supervisor.")
        log_node("risk", {"active": False}, {"risk_result": "{}"})
        return {"risk_result": "{}"}

    step("RISK AGENT", "Evaluation du niveau de risque...")
    response = llm.invoke([
        SystemMessage(content=RISK_PROMPT),
        HumanMessage(content=state["user_input"]),
    ])
    print(f"         Extrait : {response.content[:80]}...")
    log_node("risk", {"user_input": state["user_input"]}, {"risk_result": response.content})
    return {"risk_result": response.content}


@monitored("history")
def history_node(state: SupervisorState) -> dict:
    """GroqModel-xw3jS : Medical History Agent."""
    if not state.get("activate_history", True):
        step("HISTORY", "Desactive par le supervisor.")
        log_node("history", {"active": False}, {"history_result": "{}"})
        return {"history_result": "{}"}

    step("HISTORY AGENT", "Analyse de l'historique medical...")
    response = llm.invoke([
        SystemMessage(content=HISTORY_PROMPT),
        HumanMessage(content=state["user_input"]),
    ])
    print(f"         Extrait : {response.content[:80]}...")
    log_node("history", {"user_input": state["user_input"]}, {"history_result": response.content})
    return {"history_result": response.content}


@monitored("combine")
def combine_node(state: SupervisorState) -> SupervisorState:
    """DataOperations + ParserComponent : fusion des 3 resultats."""
    step("COMBINE", "Fusion des resultats des 3 agents...")

    combined = (
        "=== SYMPTOMS ANALYSIS ===\n"
        f"{state.get('symptoms_result', '{}')}\n\n"
        "=== RISK ASSESSMENT ===\n"
        f"{state.get('risk_result', '{}')}\n\n"
        "=== MEDICAL HISTORY ===\n"
        f"{state.get('history_result', '{}')}"
    )
    print("         Fusion terminee.")
    log_node("combine",
        {"symptoms": state.get("symptoms_result",""), "risk": state.get("risk_result",""), "history": state.get("history_result","")},
        {"combined_text": combined}
    )
    return {**state, "combined_text": combined}


@monitored("final_response")
def response_node(state: SupervisorState) -> SupervisorState:
    """GroqModel-QQ1QZ : Healthcare Response Agent — rapport structure."""
    step("HEALTHCARE RESPONSE", "Generation du rapport medical...")

    response = llm.invoke([
        SystemMessage(content=RESPONSE_PROMPT),
        HumanMessage(content=state["combined_text"]),
    ])
    print("         Rapport genere.")
    log_node("healthcare_response",
        {"combined_text": state.get("combined_text", "")},
        {"final_response": response.content}
    )
    return {**state, "final_response": response.content}


@monitored("human_review")
def human_review_node(state: SupervisorState) -> SupervisorState:
    """
    HUMAN-IN-THE-LOOP
    LangGraph interrompt AVANT ce noeud (interrupt_before=["human_review"]).
    Ce noeud s'execute apres que l'humain a approuve via update_state().
    """
    comment = state.get("human_comment", "")
    step("HUMAN REVIEW", f"Approuve par l'humain. Commentaire : {comment or '(aucun)'}")
    log_node("human_review",
        {"final_response": state.get("final_response", "")},
        {"human_approved": True, "human_comment": comment}
    )
    return {**state, "human_approved": True}


@monitored("audit")
def audit_node(state: SupervisorState) -> SupervisorState:
    """Prompt-PeQ6f + GroqModel-gkoZc : Audit Agent — coherence du risque."""
    step("AUDIT AGENT", "Verification de la coherence du niveau de risque...")

    prompt = AUDIT_PROMPT.format(llm_response=state["final_response"])
    response = llm.invoke([HumanMessage(content=prompt)])
    print(f"         Audit : {response.content[:120]}...")
    log_node("audit",
        {"final_response": state.get("final_response", "")},
        {"audit_result": response.content}
    )
    return {**state, "audit_result": response.content}


@monitored("risk_extractor")
def risk_extractor_node(state: SupervisorState) -> SupervisorState:
    """Prompt-glNjT + GroqModel-pebJk : Risk Extractor — extrait Haut ou Bas."""
    step("RISK EXTRACTOR", "Extraction du label de risque (Haut / Bas)...")

    prompt = RISK_EXTRACTOR_PROMPT.format(reponse_llm=state["audit_result"])
    response = llm.invoke([HumanMessage(content=prompt)])
    raw = response.content.strip()

    if "haut" in raw.lower():
        label = "Haut"
    elif "bas" in raw.lower():
        label = "Bas"
    else:
        label = "Bas"

    print(f"         Label extrait : [{label}]")
    log_node("risk_extractor",
        {"audit_result": state.get("audit_result", "")},
        {"risk_label": label, "llm_raw": raw}
    )
    return {**state, "risk_label": label}


@monitored("high_risk_alert")
def high_risk_alert_node(state: SupervisorState) -> SupervisorState:
    """GroqModel-aRMzd : alerte URGENT."""
    banner("ALERTE RISQUE ELEVE", char="!")
    print(f"  >>> {HIGH_RISK_SYSTEM}")
    log_node("high_risk_alert",
        {"risk_label": "Haut"},
        {"final_alert": HIGH_RISK_SYSTEM}
    )
    return {**state, "final_alert": HIGH_RISK_SYSTEM}


@monitored("low_risk_alert")
def low_risk_alert_node(state: SupervisorState) -> SupervisorState:
    """GroqModel-G6oOV : alerte PAS URGENT."""
    banner("ALERTE RISQUE FAIBLE", char="-")
    print(f"  >>> {LOW_RISK_SYSTEM}")
    log_node("low_risk_alert",
        {"risk_label": "Bas"},
        {"final_alert": LOW_RISK_SYSTEM}
    )
    return {**state, "final_alert": LOW_RISK_SYSTEM}


def route_by_risk(state: SupervisorState) -> str:
    """SmartRouter : branchement conditionnel selon risk_label."""
    label = state.get("risk_label", "Bas")
    route = "high_risk_alert" if label == "Haut" else "low_risk_alert"
    step("SMARTROUTER", f"Risque = {label}  ->  {route}")
    return route


# ===========================================================
# 6. CONSTRUCTION DU GRAPHE
# ===========================================================

def build_graph():
    builder = StateGraph(SupervisorState)

    builder.add_node("supervisor",      supervisor_node)
    builder.add_node("symptoms",        symptoms_node)
    builder.add_node("risk",            risk_node)
    builder.add_node("history",         history_node)
    builder.add_node("combine",         combine_node)
    builder.add_node("final_response",  response_node)
    builder.add_node("human_review",    human_review_node)
    builder.add_node("audit",           audit_node)
    builder.add_node("risk_extractor",  risk_extractor_node)
    builder.add_node("high_risk_alert", high_risk_alert_node)
    builder.add_node("low_risk_alert",  low_risk_alert_node)

    # START -> supervisor
    builder.add_edge(START, "supervisor")

    # supervisor -> 3 agents en parallele
    builder.add_edge("supervisor", "symptoms")
    builder.add_edge("supervisor", "risk")
    builder.add_edge("supervisor", "history")

    # 3 agents -> combine
    builder.add_edge("symptoms", "combine")
    builder.add_edge("risk",     "combine")
    builder.add_edge("history",  "combine")

    # combine -> rapport -> [PAUSE] human_review -> audit -> risk_extractor
    builder.add_edge("combine",        "final_response")
    builder.add_edge("final_response", "human_review")
    builder.add_edge("human_review",   "audit")
    builder.add_edge("audit",          "risk_extractor")

    # SmartRouter conditionnel
    builder.add_conditional_edges(
        "risk_extractor",
        route_by_risk,
        {
            "high_risk_alert": "high_risk_alert",
            "low_risk_alert":  "low_risk_alert",
        }
    )

    # alertes -> END
    builder.add_edge("high_risk_alert", END)
    builder.add_edge("low_risk_alert",  END)

    memory = MemorySaver()
    return builder.compile(
        checkpointer=memory,
        interrupt_before=["human_review"],
    )


# ===========================================================
# 6bis. API HELPERS — utilises par api.py (FastAPI)
# ===========================================================
#
# Le graphe est compile UNE SEULE FOIS et partage entre les requetes HTTP,
# car le MemorySaver (checkpointer) doit conserver l'etat d'un thread_id
# entre l'appel POST /diagnose (qui s'arrete a interrupt_before=human_review)
# et l'appel POST /diagnose/{thread_id}/approve (qui reprend l'execution).

_api_graph = None

def get_api_graph():
    global _api_graph
    if _api_graph is None:
        _api_graph = build_graph()
    return _api_graph


def start_diagnosis(user_message: str, thread_id: str) -> dict:
    """Lance le graphe jusqu'au point d'arret human-in-the-loop.
    Retourne le rapport genere, en attente d'approbation."""
    correlation_id = monitoring.new_correlation_id()
    monitoring.start_run(correlation_id, user_message)
    reset_journal()

    graph = get_api_graph()
    config = {"configurable": {"thread_id": thread_id}}

    initial: SupervisorState = {
        "correlation_id":    correlation_id,
        "user_input":        user_message,
        "activate_symptoms": True,
        "activate_risk":     True,
        "activate_history":  True,
        "supervisor_reason": "",
        "symptoms_result":   "",
        "risk_result":       "",
        "history_result":    "",
        "combined_text":     "",
        "final_response":    "",
        "human_approved":    False,
        "human_comment":     "",
        "audit_result":      "",
        "risk_label":        "",
        "final_alert":       "",
    }

    for _ in graph.stream(initial, config, stream_mode="values"):
        pass

    snapshot = graph.get_state(config)
    return {
        "thread_id": thread_id,
        "correlation_id": correlation_id,
        "final_response": snapshot.values.get("final_response", ""),
        "supervisor_reason": snapshot.values.get("supervisor_reason", ""),
        "status": "awaiting_human_review",
    }


def approve_diagnosis(thread_id: str, approved: bool, comment: str = "") -> dict:
    """Reprend l'execution apres la decision humaine (human-in-the-loop)."""
    graph = get_api_graph()
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    correlation_id = snapshot.values.get("correlation_id", "")

    graph.update_state(config, {
        "human_approved": approved,
        "human_comment":  comment,
    })

    if not approved:
        monitoring.end_run(correlation_id, "rejected", {"thread_id": thread_id})
        return {
            "thread_id": thread_id,
            "correlation_id": correlation_id,
            "status": "rejected",
        }

    for _ in graph.stream(None, config, stream_mode="values"):
        pass

    final = graph.get_state(config).values
    monitoring.end_run(correlation_id, "completed", {
        "risk_label": final.get("risk_label", ""),
        "final_alert": final.get("final_alert", ""),
    })

    return {
        "thread_id": thread_id,
        "correlation_id": correlation_id,
        "status": "completed",
        "risk_label": final.get("risk_label", ""),
        "final_alert": final.get("final_alert", ""),
        "final_response": final.get("final_response", ""),
    }


# ===========================================================
# 7. LOGGING
# ===========================================================

LOG_DIR  = r"C:\Users\LENOVO\Desktop\exer\logs"
JSON_DIR = r"C:\Users\LENOVO\Desktop\exer\logs\json"

def init_log(ts: str) -> tuple:
    """Cree les dossiers et retourne (log_path, json_dir)."""
    os.makedirs(LOG_DIR,  exist_ok=True)
    os.makedirs(JSON_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"session_{ts}.log")
    json_dir = os.path.join(JSON_DIR, ts)
    os.makedirs(json_dir, exist_ok=True)
    return log_path, json_dir

def write_log(path: str, text: str):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")


# ===========================================================
# 8. EXECUTION D'UN CAS PATIENT
# ===========================================================

def run(user_message: str, thread_id: str, log_path: str, json_dir: str, mode: str = "auto",
        correlation_id: str = ""):
    """
    mode='auto'   : validation humaine simulee automatiquement
    mode='manual' : l'utilisateur saisit sa reponse au clavier

    Produit :
      - entrees dans log_path (.log)
      - un fichier JSON par noeud dans json_dir/
      - un journal de monitoring par correlation_id (monitoring_logs/)
    """
    reset_journal()
    correlation_id = correlation_id or monitoring.new_correlation_id()
    monitoring.start_run(correlation_id, user_message)
    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    t0 = datetime.now()

    # --- En-tete ---
    banner(f"PATIENT : {user_message[:55]}")
    write_log(log_path, f"\n{'='*62}")
    write_log(log_path, f"[{t0.strftime('%H:%M:%S')}] CAS — thread: {thread_id}")
    write_log(log_path, f"PATIENT : {user_message}")
    write_log(log_path, f"{'='*62}")

    initial: SupervisorState = {
        "correlation_id":    correlation_id,
        "user_input":        user_message,
        "activate_symptoms": True,
        "activate_risk":     True,
        "activate_history":  True,
        "supervisor_reason": "",
        "symptoms_result":   "",
        "risk_result":       "",
        "history_result":    "",
        "combined_text":     "",
        "final_response":    "",
        "human_approved":    False,
        "human_comment":     "",
        "audit_result":      "",
        "risk_label":        "",
        "final_alert":       "",
    }

    # --- Phase 1 : jusqu'a l'interruption ---
    banner("PHASE 1 — Agents + Rapport", char="-")
    for _ in graph.stream(initial, config, stream_mode="values"):
        pass

    snapshot = graph.get_state(config)
    rapport  = snapshot.values.get("final_response", "")

    # Afficher le rapport genere
    banner("RAPPORT HEALTHCARE (en attente de validation)")
    print(rapport)
    write_log(log_path, "\n--- RAPPORT HEALTHCARE ---")
    write_log(log_path, rapport)

    # --- Phase 2 : Human-in-the-Loop ---
    banner("HUMAN-IN-THE-LOOP", char="*")
    print(f"  Prochain noeud : {snapshot.next}")

    if mode == "manual":
        print("\n  Lisez le rapport ci-dessus.")
        approbation = input("  Approuvez-vous ce rapport ? (o/n) : ").strip().lower()
        comment     = input("  Commentaire (optionnel, Entree pour passer) : ").strip()
        approved    = approbation in ("o", "oui", "y", "yes", "")
    else:
        approved = True
        comment  = "Validation automatique (mode demo)"
        print(f"\n  [AUTO] {comment}")

    decision = "APPROUVE" if approved else "REFUSE"
    print(f"  Decision : {decision}")
    write_log(log_path, f"\n--- HUMAN REVIEW ---")
    write_log(log_path, f"Decision : {decision} | Commentaire : {comment or '(aucun)'}")

    graph.update_state(config, {
        "human_approved": approved,
        "human_comment":  comment,
    })

    if not approved:
        print("\n  Rapport refuse par l'humain — execution arretee.")
        write_log(log_path, "Execution interrompue : rapport refuse.")
        # Sauvegarder le journal JSON meme en cas de refus
        json_path = os.path.join(json_dir, f"{thread_id}_REFUSE.json")
        save_json_log(json_path, thread_id, user_message)
        print(f"  [JSON] Log noeuds : {json_path}")
        monitoring.end_run(correlation_id, "rejected", {"thread_id": thread_id})
        return None

    # --- Phase 3 : Audit + Risk Extractor + SmartRouter + Alerte ---
    banner("PHASE 2 — Audit + Routage + Alerte", char="-")
    for _ in graph.stream(None, config, stream_mode="values"):
        pass

    # --- Resultats finaux ---
    final = graph.get_state(config).values
    t1    = datetime.now()
    duree = round((t1 - t0).total_seconds(), 1)

    banner("RESULTAT FINAL")
    print(f"  Niveau de risque : {final.get('risk_label', 'N/A')}")
    print(f"  Alerte           : {final.get('final_alert', 'N/A')}")
    print(f"  Duree totale     : {duree}s")

    write_log(log_path, "\n--- RESULTATS ---")
    write_log(log_path, f"Agents actives    : Symptoms={final.get('activate_symptoms')} | Risk={final.get('activate_risk')} | History={final.get('activate_history')}")
    write_log(log_path, f"Raison supervisor : {final.get('supervisor_reason')}")
    write_log(log_path, f"Audit (extrait)   : {final.get('audit_result', '')[:250]}")
    write_log(log_path, f"Niveau de risque  : {final.get('risk_label', '')}")
    write_log(log_path, f"Alerte finale     : {final.get('final_alert', '')}")
    write_log(log_path, f"Duree             : {duree}s | Fin : {t1.strftime('%H:%M:%S')}")

    # --- Sauvegarder le journal JSON par noeud ---
    json_path = os.path.join(json_dir, f"{thread_id}.json")
    save_json_log(json_path, thread_id, user_message)
    write_log(log_path, f"JSON noeuds       : {json_path}")
    print(f"\n  [JSON] Log noeuds sauvegarde : {json_path}")

    monitoring.end_run(correlation_id, "completed", {
        "risk_label": final.get("risk_label", ""),
        "final_alert": final.get("final_alert", ""),
        "duree_s": duree,
    })
    final["correlation_id"] = correlation_id
    return final


# ===========================================================
# 9. COMPARATIF LOW-CODE vs FRAMEWORK
# ===========================================================

COMPARATIF = """
+------------------+----------------------------+------------------------+
|  COMPARATIF PATTERN SUPERVISOR : Langflow vs LangGraph                |
+------------------+----------------------------+------------------------+
| Critere          | Langflow (Low-Code)         | LangGraph (Framework)  |
+------------------+----------------------------+------------------------+
| Parallelisme     | Noeuds relies visuellement  | add_edge() x3 natif    |
| Supervisor JSON  | GroqModel + manuel          | extract_json() Python  |
| Combine data     | DataOperations + Parser     | f-string Python pur    |
| Human-in-Loop    | Absent (low-code)           | interrupt_before natif |
| Controle agents  | Tous toujours actifs        | if/else selon decision |
| Audit Agent      | Prompt Template + Groq      | audit_node() Python    |
| Risk Extractor   | Prompt Template + Groq      | risk_extractor_node()  |
| SmartRouter      | Noeud conditionnel visuel   | add_conditional_edges  |
| Alertes risque   | 2 GroqModels separes        | 2 noeuds Python        |
| Persistence etat | Non native                  | MemorySaver checkpoints|
| Debug            | Logs visuels par noeud      | fichier .log horodate  |
| Flexibilite      | Limitee                     | Totale (code Python)   |
+------------------+----------------------------+------------------------+

FLUX SUPERVISOR_KHAOULA.JSON  (implementé dans ce fichier) :

  ChatInput
    |-> Supervisor  (JSON : ON/OFF par agent)
    |-> [Symptoms Agent | Risk Agent | History Agent]  <parallele>
    |-> Combine
    |-> Healthcare Response Agent  ->  rapport medical
    |
    |*** HUMAN-IN-THE-LOOP (interrupt_before) ***
    |   L'humain lit le rapport, approuve ou refuse
    |
    |-> Audit Agent         (coherence risque vs symptomes)
    |-> Risk Extractor      ("Haut" ou "Bas")
    |-> SmartRouter
         |-- Haut  ->  URGENT : Le patient doit visiter le medecin.
         |-- Bas   ->  PAS URGENT : Vous pouvez suivre la prospection.
    |-> END
"""


# ===========================================================
# 10. POINT D'ENTREE
# ===========================================================

if __name__ == "__main__":
    print(COMPARATIF)

    # Choisir le mode d'execution
    print("Mode d'execution :")
    print("  [1] Automatique (validation simulee — demo)")
    print("  [2] Manuel (vous tapez la validation au clavier)")
    choix = input("Votre choix (1/2, defaut=1) : ").strip()
    mode = "manual" if choix == "2" else "auto"

    # Creer les dossiers log et json
    ts               = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path, json_dir = init_log(ts)

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"SUPERVISOR LANGGRAPH — supervisor_khaoula.json\n")
        f.write(f"Session : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
        f.write(f"Mode    : {mode}\n")
        f.write(COMPARATIF)

    print(f"\n[LOG]  Fichier log  : {log_path}")
    print(f"[JSON] Dossier JSON : {json_dir}\n")

    # ── CAS 1 : fievre + diabete ──────────────────────────────
    run(
        user_message="J'ai de la fievre a 39, une toux seche et des douleurs musculaires depuis 2 jours. J'ai aussi du diabete de type 2.",
        thread_id="cas-1",
        log_path=log_path,
        json_dir=json_dir,
        mode=mode,
    )

    print("\n" + "=" * 62 + "\n")

    # ── CAS 2 : douleur cardiaque ─────────────────────────────
    run(
        user_message="Je ressens une douleur dans la poitrine et un essoufflement depuis ce matin. J'ai des antecedents familiaux de maladies cardiaques.",
        thread_id="cas-2",
        log_path=log_path,
        json_dir=json_dir,
        mode=mode,
    )

    write_log(log_path, f"\n{'='*62}\nFIN DE SESSION\n{'='*62}\n")
    print(f"\n[LOG]  Session sauvegardee : {log_path}")
    print(f"[JSON] Fichiers JSON       : {json_dir}/")
