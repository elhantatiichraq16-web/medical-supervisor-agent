"""
Generation de la page dashboard HTML (latence, tokens, Correlation ID).

Page autonome (CSS inline, pas de dependance JS externe) pour pouvoir etre
demontree meme sans connexion internet pendant la presentation.
"""

import html


def render_dashboard(metrics: dict, runs: list) -> str:
    per_node_rows = "".join(_node_row(node, stats) for node, stats in metrics["per_node"].items())
    run_rows = "".join(_run_row(run) for run in sorted(runs, key=lambda r: r["started_at"], reverse=True))
    tokens = metrics["total_tokens"]
    status = metrics["status_counts"]

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Medical Supervisor Agent — Dashboard</title>
<meta http-equiv="refresh" content="15">
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .subtitle {{ color: #94a3b8; margin-bottom: 24px; font-size: 13px; }}
  .cards {{ display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap; }}
  .card {{ background: #1e293b; border-radius: 10px; padding: 16px 20px; min-width: 150px; border: 1px solid #334155; }}
  .card .label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
  .card .value {{ font-size: 26px; font-weight: 700; margin-top: 4px; }}
  .value.green {{ color: #4ade80; }}
  .value.red {{ color: #f87171; }}
  .value.amber {{ color: #fbbf24; }}
  table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 10px; overflow: hidden; margin-bottom: 28px; }}
  th, td {{ padding: 10px 14px; text-align: left; font-size: 13px; border-bottom: 1px solid #334155; }}
  th {{ color: #94a3b8; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; }}
  tr:last-child td {{ border-bottom: none; }}
  .badge {{ padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; }}
  .badge.completed {{ background: #14532d; color: #4ade80; }}
  .badge.rejected {{ background: #450a0a; color: #f87171; }}
  .badge.running {{ background: #422006; color: #fbbf24; }}
  .corr {{ font-family: monospace; font-size: 11px; color: #94a3b8; }}
  section h2 {{ font-size: 15px; color: #cbd5e1; margin: 0 0 10px; }}
</style>
</head>
<body>
  <h1>Medical Supervisor Agent — Dashboard de monitoring</h1>
  <div class="subtitle">Rafraichissement automatique toutes les 15s — Correlation ID, latence par noeud, consommation de tokens Groq</div>

  <div class="cards">
    <div class="card"><div class="label">Executions totales</div><div class="value">{metrics['nb_runs']}</div></div>
    <div class="card"><div class="label">Completees</div><div class="value green">{status.get('completed', 0)}</div></div>
    <div class="card"><div class="label">Rejetees</div><div class="value red">{status.get('rejected', 0)}</div></div>
    <div class="card"><div class="label">En cours</div><div class="value amber">{status.get('running', 0)}</div></div>
    <div class="card"><div class="label">Tokens totaux</div><div class="value">{tokens['total_tokens']}</div></div>
    <div class="card"><div class="label">Tokens entree / sortie</div><div class="value" style="font-size:18px">{tokens['input_tokens']} / {tokens['output_tokens']}</div></div>
  </div>

  <section>
    <h2>Latence et tokens par noeud du graphe</h2>
    <table>
      <tr><th>Noeud</th><th>Appels</th><th>Erreurs</th><th>Latence moy. (ms)</th><th>Latence totale (ms)</th><th>Tokens (in/out/total)</th></tr>
      {per_node_rows or '<tr><td colspan="6">Aucune execution encore enregistree.</td></tr>'}
    </table>
  </section>

  <section>
    <h2>Executions recentes (Correlation ID)</h2>
    <table>
      <tr><th>Correlation ID</th><th>Statut</th><th>Demarre a</th><th>Nb evenements</th></tr>
      {run_rows or '<tr><td colspan="4">Aucune execution encore enregistree.</td></tr>'}
    </table>
  </section>
</body>
</html>"""


def _node_row(node: str, stats: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(node)}</td>"
        f"<td>{stats['calls']}</td>"
        f"<td>{stats['errors']}</td>"
        f"<td>{stats['duration_ms_avg']}</td>"
        f"<td>{stats['duration_ms_total']}</td>"
        f"<td>{stats['input_tokens']} / {stats['output_tokens']} / {stats['total_tokens']}</td>"
        "</tr>"
    )


def _run_row(run: dict) -> str:
    status = html.escape(run["status"])
    return (
        "<tr>"
        f"<td class=\"corr\">{html.escape(run['correlation_id'])}</td>"
        f"<td><span class=\"badge {status}\">{status}</span></td>"
        f"<td>{html.escape(run['started_at'])}</td>"
        f"<td>{run['nb_events']}</td>"
        "</tr>"
    )
