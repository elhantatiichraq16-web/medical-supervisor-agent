# Agent Card — Medical Multi-Agent Supervisor

## Identité
- **Nom :** Medical-Supervisor-Agent
- **Version :** 1.0.0
- **Type :** Système multi-agent (pattern Supervisor) avec orchestration LangGraph
- **Auteur :** Ichrak Elhantati
- **Date de création :** 2026-06-24
- **Fichier source :** `supervisor_langgraph.py`

## Description
Agent conversationnel médical qui reçoit la description d'un patient, décide dynamiquement quels sous-agents spécialisés activer (symptômes, risque, antécédents), combine leurs analyses en un rapport structuré, le soumet à validation humaine, puis route une alerte finale selon le niveau de risque détecté.

## Architecture
```
ChatInput
   │
Supervisor Agent (decide quels agents activer)
   │
[Parallèle] Symptoms_Agent | Risk_Agent | Medical_History_Agent
   │
Combine
   │
Healthcare Response Agent (rapport structuré)
   │
*** HUMAN-IN-THE-LOOP (interrupt_before) ***
   │
Audit Agent (cohérence du niveau de risque)
   │
Risk Extractor ("Haut" / "Bas")
   │
SmartRouter
 ├─ Haut → High Risk Alert : "URGENT : consulter un médecin"
 └─ Bas  → Low Risk Alert  : "PAS URGENT"
   │
END
```

## Capacités
- Analyse des symptômes décrits en langage naturel
- Évaluation du niveau de risque (low/medium/high)
- Revue des antécédents médicaux (conditions chroniques, facteurs de risque)
- Génération d'un rapport patient structuré et lisible
- Point d'arrêt humain obligatoire avant diffusion du rapport (`human_approved`, `human_comment`)
- Audit automatique de cohérence avant le routage final
- Journalisation complète de chaque nœud (entrée/sortie/timestamp) via `log_node()`

## Limites / Garde-fous
- **Ne pose JAMAIS de diagnostic définitif** (contrainte explicite dans `RESPONSE_PROMPT`)
- Recommande systématiquement une consultation médicale si pertinent
- Ne doit pas être utilisé comme substitut à un avis médical professionnel
- Toute sortie doit passer par validation humaine avant action (`human_approved = false` bloque le pipeline)
- Hors scope : urgences vitales immédiates (orienter vers les services d'urgence réels, pas vers l'agent)

## Entrées / Sorties
- **Entrée :** `user_input` (texte libre décrivant l'état du patient)
- **Sortie :**
  - `final_response` : rapport médical structuré (résumé, antécédents, niveau de risque, recommandations)
  - `final_alert` : message "URGENT" ou "PAS URGENT"
  - Journal JSON complet de l'exécution (`save_json_log`)

## Dépendances
- **Modèle LLM :** Groq — `llama-3.1-8b-instant` (température 0.1)
- **Framework :** LangGraph (`StateGraph`, `MemorySaver` pour checkpointing)
- **Librairies :** `langchain_groq`, `langchain_core`

## Configuration sensible — ⚠️ À CORRIGER AVANT v1.0.0
> **Problème de sécurité détecté :** la clé API Groq est actuellement codée en dur dans `supervisor_langgraph.py` (ligne ~109). Avant de tagger v1.0.0, déplacer cette clé dans une variable d'environnement (`GROQ_API_KEY`) et ne jamais la committer dans Git.

## Contact / Responsable
- **Mainteneur :** Ichrak Elhantati
- **Contact :** elhantatiichraq16@gmail.com
