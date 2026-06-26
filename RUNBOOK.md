# Runbook — Medical-Supervisor-Agent

Document opérationnel décrivant la gestion des incidents, le kill-switch et la procédure de rollback pour l'agent `Medical-Supervisor-Agent` (v1.1.0, déployé via Docker sur [Railway](https://railway.com/) — https://med-agent.up.railway.app).

---

## 1. Kill-switch (arrêt d'urgence)

Objectif : désactiver immédiatement l'agent si un comportement dangereux ou incohérent est détecté (ex : diagnostic donné directement, alerte de risque incorrecte non bloquée par l'audit).

**Procédure :**
1. Couper l'accès au modèle : retirer ou invalider la clé API Groq utilisée par l'agent (`GROQ_API_KEY`).
2. Si déployé comme service, basculer une variable d'environnement `AGENT_ENABLED=false` lue au démarrage du process et stopper le service (`systemctl stop` / arrêt du conteneur / arrêt du process Python).
3. Bloquer le point d'entrée du graphe LangGraph (`StateGraph.compile()`) pour empêcher toute nouvelle invocation tant que l'incident n'est pas résolu.
4. Informer les utilisateurs/patients que le service est temporairement indisponible.
5. **Sur Railway :** suspendre le service (dashboard Railway → Settings → Remove/Sleep) ou retirer la variable d'environnement `GROQ_API_KEY` pour forcer l'échec au démarrage du conteneur.

**Délai cible :** kill-switch actionnable en moins de 5 minutes.

---

## 2. Détection d'incident

Signaux à surveiller :
- Le rapport final contient un diagnostic définitif (violation de la contrainte du `RESPONSE_PROMPT`)
- `risk_label` incohérent avec le contenu du rapport (l'Audit Agent ne l'a pas détecté)
- Le pipeline ne s'arrête pas au point `human-in-the-loop` (`interrupt_before` non respecté)
- Erreurs API répétées du modèle Groq (timeout, quota dépassé, clé invalide)
- Journal JSON (`save_json_log`) manquant ou incomplet pour une session
- **Monitoring :** un événement de nœud avec `status: "error"` dans `GET /runs/{correlation_id}` (voir `monitoring.py`) — indique une exception non gérée dans un nœud du graphe
- **API / déploiement :** `GET /health` (https://med-agent.up.railway.app/health) ne répond pas ou répond en erreur (le service Railway est down ou ne démarre pas — vérifier les logs de build/déploiement dans l'onglet Deployments de Railway)

---

## 3. Procédure de rollback

1. Identifier la dernière version stable :
   ```bash
   git tag -l
   ```
2. Revenir à la version stable (ex. v1.0.0) :
   ```bash
   git checkout v1.0.0
   ```
3. Redéployer cette version dans l'environnement cible.
4. Vérifier le bon fonctionnement avec un cas de test connu (ex. patient à risque "Bas" et patient à risque "Haut") et comparer la sortie au journal JSON de référence.
5. Documenter l'incident (cause, durée, correctif) avant de réautoriser la version corrigée.

---

## 4. Escalade

| Délai sans résolution | Action |
|---|---|
| 15 min | Notifier le mainteneur (Ichrak Elhantati) |
| 1 h | Activer le kill-switch si pas déjà fait |
| 24 h | Revue post-incident obligatoire avant remise en service |

---

## 5. Bonnes pratiques de prévention
- Ne jamais committer de clé API en dur dans le code (voir `AGENT_CARD.md`, section configuration sensible)
- Toujours tester sur le tag stable avant de merger une évolution de prompt
- Garder le `MemorySaver` (checkpointing) actif pour pouvoir auditer/reproduire une session incidentée
- Ne jamais merger sur `main` sans que la CI GitHub Actions (`.github/workflows/ci.yml`) soit verte (tests + build Docker)
- Toujours consulter `GET /runs/{correlation_id}` en premier réflexe lors d'un incident signalé par un utilisateur — il donne le détail nœud par nœud (statut, latence) de l'exécution concernée
