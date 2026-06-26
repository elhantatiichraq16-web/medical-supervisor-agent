"""
Interface utilisateur simple (formulaire symptomes -> reponse).

Page autonome (CSS + JS inline) qui appelle les endpoints /diagnose et
/diagnose/{thread_id}/approve deja exposes par l'API, pour permettre une
demonstration du flux complet (y compris le point d'arret human-in-the-loop)
sans devoir utiliser curl ou /docs.
"""


def render_ui() -> str:
    return """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Medical Supervisor Agent — Diagnostic</title>
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; max-width: 760px; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .subtitle { color: #94a3b8; margin-bottom: 24px; font-size: 13px; }
  textarea { width: 100%; min-height: 100px; background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 8px; padding: 12px; font-size: 14px; font-family: inherit; resize: vertical; box-sizing: border-box; }
  button { background: #2563eb; color: white; border: none; border-radius: 8px; padding: 10px 20px; font-size: 14px; font-weight: 600; cursor: pointer; margin-top: 12px; }
  button:hover { background: #1d4ed8; }
  button:disabled { background: #334155; cursor: not-allowed; }
  button.reject { background: #b91c1c; margin-left: 8px; }
  button.reject:hover { background: #991b1b; }
  .card { background: #1e293b; border-radius: 10px; padding: 20px; border: 1px solid #334155; margin-top: 20px; display: none; }
  .card.visible { display: block; }
  .card h2 { font-size: 15px; margin: 0 0 12px; color: #cbd5e1; }
  .card pre { white-space: pre-wrap; font-family: inherit; font-size: 13px; line-height: 1.5; margin: 0; }
  .badge { display: inline-block; padding: 4px 12px; border-radius: 6px; font-size: 13px; font-weight: 700; margin-top: 8px; }
  .badge.haut { background: #450a0a; color: #f87171; }
  .badge.bas { background: #14532d; color: #4ade80; }
  .corr { font-family: monospace; font-size: 11px; color: #64748b; margin-top: 12px; }
  .status { font-size: 13px; color: #94a3b8; margin-top: 8px; }
  .links { margin-top: 24px; font-size: 13px; }
  .links a { color: #60a5fa; text-decoration: none; margin-right: 16px; }
</style>
</head>
<body>
  <h1>Medical Supervisor Agent — Diagnostic</h1>
  <div class="subtitle">Decrivez les symptomes du patient. Le rapport sera genere par les agents, puis attendra votre validation (human-in-the-loop) avant l'alerte finale.</div>

  <textarea id="symptoms" placeholder="Ex: Fievre a 39, toux seche et douleurs musculaires depuis 2 jours. Antecedent de diabete de type 2."></textarea>
  <div>
    <button id="submitBtn" onclick="submitDiagnose()">Envoyer au Supervisor Agent</button>
  </div>
  <div id="statusMsg" class="status"></div>

  <div id="reportCard" class="card">
    <h2>Rapport genere (en attente de validation humaine)</h2>
    <pre id="reportText"></pre>
    <div>
      <button id="approveBtn" onclick="approve(true)">Approuver</button>
      <button id="rejectBtn" class="reject" onclick="approve(false)">Refuser</button>
    </div>
  </div>

  <div id="resultCard" class="card">
    <h2>Resultat final</h2>
    <div id="resultAlert" class="badge"></div>
    <pre id="resultText" style="margin-top: 12px;"></pre>
    <div id="correlationId" class="corr"></div>
  </div>

  <div class="links">
    <a href="/dashboard">Dashboard de monitoring</a>
    <a href="/docs">Documentation API (Swagger)</a>
  </div>

<script>
let currentThreadId = null;

async function submitDiagnose() {
  const symptoms = document.getElementById('symptoms').value.trim();
  if (!symptoms) {
    document.getElementById('statusMsg').textContent = 'Veuillez decrire les symptomes du patient.';
    return;
  }
  currentThreadId = 'ui-' + Date.now();
  setBusy(true, 'Analyse en cours (Supervisor + 3 agents en parallele)...');
  document.getElementById('reportCard').classList.remove('visible');
  document.getElementById('resultCard').classList.remove('visible');

  try {
    const res = await fetch('/diagnose', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({user_message: symptoms, thread_id: currentThreadId})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Erreur inconnue');

    document.getElementById('reportText').textContent = data.final_response;
    document.getElementById('reportCard').classList.add('visible');
    setBusy(false, 'Rapport genere. En attente de votre validation.');
  } catch (err) {
    setBusy(false, 'Erreur : ' + err.message);
  }
}

async function approve(decision) {
  setBusy(true, decision ? 'Validation en cours (audit + routage)...' : 'Rejet en cours...');
  try {
    const res = await fetch(`/diagnose/${currentThreadId}/approve`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({approved: decision, comment: decision ? 'Approuve via interface UI' : 'Refuse via interface UI'})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Erreur inconnue');

    document.getElementById('reportCard').classList.remove('visible');

    if (data.status === 'rejected') {
      document.getElementById('resultAlert').textContent = 'RAPPORT REFUSE';
      document.getElementById('resultAlert').className = 'badge haut';
      document.getElementById('resultText').textContent = 'Execution arretee : le rapport a ete refuse par l\\'humain.';
    } else {
      const isHigh = data.risk_label === 'Haut';
      document.getElementById('resultAlert').textContent = data.final_alert;
      document.getElementById('resultAlert').className = 'badge ' + (isHigh ? 'haut' : 'bas');
      document.getElementById('resultText').textContent = data.final_response;
    }
    document.getElementById('correlationId').textContent = 'Correlation ID : ' + data.correlation_id;
    document.getElementById('resultCard').classList.add('visible');
    setBusy(false, 'Termine.');
  } catch (err) {
    setBusy(false, 'Erreur : ' + err.message);
  }
}

function setBusy(busy, message) {
  document.getElementById('submitBtn').disabled = busy;
  document.getElementById('approveBtn').disabled = busy;
  document.getElementById('rejectBtn').disabled = busy;
  document.getElementById('statusMsg').textContent = message || '';
}
</script>
</body>
</html>"""
