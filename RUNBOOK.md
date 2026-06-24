# Runbook — Medical-Supervisor-Agent

Document opérationnel décrivant la gestion des incidents, le kill-switch et la procédure de rollback pour l'agent `Medical-Supervisor-Agent` (v1.0.0).

---

## 1. Kill-switch (arrêt d'urgence)

Objectif : désactiver immédiatement l'agent si un comportement dangereux ou incohérent est détecté (ex : diagnostic donné directement, alerte de risque incorrecte non bloquée par l'audit).

**Procédure :**
1. Couper l'accès au modèle : retirer ou invalider la clé API Groq utilisée par l'agent (`GROQ_API_KEY`).
2. Si déployé comme service, basculer une variable d'environnement `AGENT_ENABLED=false` lue au démarrage du process et stopper le service (`systemctl stop` / arrêt du conteneur / arrêt du process Python).
3. Bloquer le point d'entrée du graphe LangGraph (`StateGraph.compile()`) pour empêcher toute nouvelle invocation tant que l'incident n'est pas résolu.
4. Informer les utilisateurs/patients que le service est temporairement indisponible.

**Délai cible :** kill-switch actionnable en moins de 5 minutes.

---

## 2. Détection d'incident

Signaux à surveiller :
- Le rapport final contient un diagnostic définitif (violation de la contrainte du `RESPONSE_PROMPT`)
- `risk_label` incohérent avec le contenu du rapport (l'Audit Agent ne l'a pas détecté)
- Le pipeline ne s'arrête pas au point `human-in-the-loop` (`interrupt_before` non respecté)
- Erreurs API répétées du modèle Groq (timeout, quota dépassé, clé invalide)
- Journal JSON (`save_json_log`) manquant ou incomplet pour une session

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
