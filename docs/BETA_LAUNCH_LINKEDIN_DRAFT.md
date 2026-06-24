# Brouillon LinkedIn — Beta Béa

> ⚠️ Ne pas publier sans validation manuelle. Brouillon technique uniquement.

---

🧠 **Béa est en beta testable.**

Béa est un agent IA autonome open-source que j'ai construit — capable de soumettre, approuver, et exécuter des missions de façon autonome, avec un vrai modèle de sécurité multi-principal.

Ce qui vient d'être durci avant d'ouvrir la beta :

🔐 **Principal binding end-to-end**
Chaque mission est liée à l'identité authentifiée du soumetteur (`submitted_by`), persistée dès la soumission et réutilisée à chaque reprise. L'approbateur est distinct et ne peut pas usurper l'identité d'exécution.

🗝️ **Sessions PolicyEngine isolées**
Les sessions de limite d'actions sont indexées par `principal_id:mission_id` — deux utilisateurs avec la même mission ne partagent jamais leur quota.

🔒 **Session store multi-worker**
Abstraction `InMemorySessionStore` (dev) / `RedisSessionStore` (beta/prod) — fail-closed si Redis requis mais indisponible.

🛡️ **Ratchets CI**
8 ratchets automatiques empêchent la réintroduction de patterns dangereux (principal falsifiable, session indexée par mission seule, `approved_by` comme identité d'exécution).

---

C'est une **beta technique**. Pas une prod. Pas un SaaS fini.

Si tu travailles sur des agents IA autonomes, de l'orchestration multi-agents, ou de la sécurité applicative — je cherche des testeurs qui veulent casser des choses.

👉 https://github.com/IA-optimist/Bea

Feedback bienvenu, issues ouvertes, PRs acceptées.

---

*#OpenSource #AgentIA #Sécurité #Python #Beta*
