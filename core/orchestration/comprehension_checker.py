"""
comprehension_checker.py
Diagnostic de comprehension reelle pour BeaMax (Mistral-7B via Ollama).
Auteur: BeaMax Research Lab | 2026-04-09
"""

import json
import time
import requests

# ── Donnees Test 1 ────────────────────────────────────────────────────────────
PHYSICAL_CAUSALITY_QUESTIONS = [
    {"id":"p01","question":"Si tu retournes un verre d'eau plein, que se passe-t-il ?","kw":["tombe","renverse","coule","sol","eau"],"concept":"l'eau tombe par gravite"},
    {"id":"p02","question":"Tu as une corde de 10 metres. Tu la coupes en 3 morceaux egaux. Combien mesure chaque morceau ?","kw":["3,33","3.33","3 m","tiers","environ 3"],"concept":"10/3=3.33m"},
    {"id":"p03","question":"Une boite fermee est posee dans l'eau. Sa densite est inferieure a 1. Que se passe-t-il ?","kw":["flotte","surface","monte","remonte","pousse"],"concept":"la boite flotte"},
    {"id":"p04","question":"Tu as un ballon gonfle a l'air. Tu le laches sous l'eau. Que se passe-t-il ?","kw":["remonte","surface","monte","flotte"],"concept":"le ballon remonte"},
    {"id":"p05","question":"Tu fais tomber une plume et une brique en meme temps dans le vide (sans air). Laquelle touche le sol en premier ?","kw":["meme temps","simultanem","ensemble","egal","toutes les deux"],"concept":"elles tombent en meme temps dans le vide"},
    {"id":"p06","question":"Tu mets un glaçon dans un verre d'eau rempli a ras bord. Quand le glaçon fond, est-ce que l'eau deborde ?","kw":["non","ne deborde","meme volume","pas"],"concept":"non, la glace deplace son propre poids en eau"},
    {"id":"p07","question":"Tu chauffes un metal. Que lui arrive-t-il au niveau de sa taille ?","kw":["dilate","grandit","augmente","plus grand","agrandit"],"concept":"le metal se dilate"},
    {"id":"p08","question":"Tu as une bougie allumee dans une piece fermee hermetiquement. Que se passe-t-il au bout d'un moment ?","kw":["eteint","s'eteint","oxygene","manque","epuise"],"concept":"la bougie s'eteint quand l'oxygene est epuise"},
    {"id":"p09","question":"Tu pousses une caisse lourde sur un sol lisse puis tu arretes de pousser. Que fait la caisse ?","kw":["ralentit","arrete","friction","frein","s'arrete"],"concept":"la caisse s'arrete par frottement"},
    {"id":"p10","question":"Tu souffles dans un ballon et tu le laches sans le nouer. Que se passe-t-il ?","kw":["degonfle","s'envole","vole","air sort","propulse"],"concept":"le ballon se propulse (3e loi Newton)"},
]

# ── Donnees Test 2 ────────────────────────────────────────────────────────────
COMPOSITIONAL_GENERALIZATION_RULES = [
    {"id":"c01","rule":"Les oiseaux ont des ailes et peuvent voler.","variation":"Un pingouin est un oiseau. Peut-il voler pour rejoindre le pole Sud ?","kw":["non","pas","ne peut pas","incapable","nage"],"exp":"Les pingouins ne volent pas."},
    {"id":"c02","rule":"Les liquides prennent la forme de leur contenant.","variation":"Tu verses du miel dans un moule en etoile. Quelle forme a le miel ?","kw":["etoile","forme du moule","moule"],"exp":"Le miel prend la forme etoile."},
    {"id":"c03","rule":"Les metaux conduisent l'electricite.","variation":"Tu as une cuillere en argent. Le courant passe-t-il ?","kw":["oui","conduit","passe","argent"],"exp":"L'argent est metal, donc conducteur."},
    {"id":"c04","rule":"Les objets plus denses que l'eau coulent.","variation":"Tu poses une piece de monnaie en fer sur l'eau. Que se passe-t-il ?","kw":["coule","fond","s'enfonce","dense","sombre"],"exp":"Le fer est plus dense, la piece coule."},
    {"id":"c05","rule":"La lumiere voyage en ligne droite.","variation":"Tu allumes une lampe dans un couloir droit. La lumiere eclaire-t-elle derriere un mur a angle droit ?","kw":["non","pas","ne tourne","obstacle","bloque","droite"],"exp":"La lumiere ne contourne pas le mur."},
    {"id":"c06","rule":"Les etres vivants ont besoin d'eau pour survivre.","variation":"Un cactus peut-il survivre plusieurs semaines sans arrosage ?","kw":["oui","peut","survie","adapte","reserve","desert"],"exp":"Le cactus stocke l'eau."},
    {"id":"c07","rule":"La chaleur monte.","variation":"Dans une piece chauffee par le sol, ou fait-il le plus chaud : au sol ou au plafond ?","kw":["plafond","haut","dessus","monte","sommet"],"exp":"L'air chaud monte, donc plus chaud en haut."},
    {"id":"c08","rule":"Couper un objet solide en deux parties cree deux morceaux distincts.","variation":"Tu coupes une feuille de papier en deux. Combien as-tu de morceaux ?","kw":["deux","2","deux morceaux"],"exp":"Couper cree deux morceaux."},
    {"id":"c09","rule":"Le froid ralentit les reactions chimiques.","variation":"Tu mets du lait au refrigerateur. Dure-t-il plus longtemps qu'a temperature ambiante ?","kw":["oui","plus longtemps","conserve","ralentit","bacteries"],"exp":"Le froid ralentit les bacteries."},
    {"id":"c10","rule":"Les sons se propagent dans l'air sous forme d'ondes.","variation":"Tu parles a quelqu'un dans l'espace (vide absolu). Peut-il t'entendre ?","kw":["non","pas","vide","silence","ne peut pas"],"exp":"Le son ne se propage pas dans le vide."},
]

# ── Donnees Test 3 ────────────────────────────────────────────────────────────
TEMPORAL_COHERENCE_TRIPLETS = [
    {"id":"t01","topic":"Ebullition de l'eau","q1":"L'eau bout a quelle temperature (pression normale) ?","q2":"Si je mets de l'eau a 90C sur le feu, est-ce qu'elle bout ?","q3":"A 100C, l'eau est-elle encore liquide ?","hints":["100","ne bout pas","non","pas encore","gazeux","vapeur"]},
    {"id":"t02","topic":"Vitesse de la lumiere","q1":"A quelle vitesse voyage la lumiere dans le vide ?","q2":"Un photon met-il du temps pour traverser une piece de 10 metres ?","q3":"Si la lumiere est instantanee, pourquoi voit-on les etoiles dans le passe ?","hints":["300","tres rapide","oui","passe","temps","pas instantane"]},
    {"id":"t03","topic":"Gravite terrestre","q1":"Qu'est-ce qui fait tomber les objets sur Terre ?","q2":"Si je lache une balle dans les airs, vers ou va-t-elle ?","q3":"Les astronautes flottent dans l'ISS. Y a-t-il de la gravite la-haut ?","hints":["gravite","bas","tombe","non","chute libre","orbite"]},
    {"id":"t04","topic":"Conservation de la matiere","q1":"Quand tu brules du bois, ou va la matiere ?","q2":"Une buche de 2 kg brule completement. Combien pese la cendre ?","q3":"La matiere peut-elle disparaitre completement ?","hints":["gaz","co2","moins","non","transforme","conservation"]},
    {"id":"t05","topic":"Pression atmospherique","q1":"Pourquoi les oreilles 'bouchent' en montant en altitude ?","q2":"La pression est-elle plus forte en montagne ou au bord de la mer ?","q3":"Si je monte dans un avion, la pression exterieure augmente ou diminue ?","hints":["pression","mer","diminue","baisse","altitude"]},
    {"id":"t06","topic":"Reflexion de la lumiere","q1":"Pourquoi voit-on notre reflet dans un miroir ?","q2":"Est-ce que la lumiere traverse un miroir ?","q3":"Pourquoi ne voit-on pas notre reflet dans un mur blanc ?","hints":["reflet","non","diffuse","speculaire","directions"]},
    {"id":"t07","topic":"Cycle de l'eau","q1":"D'ou vient l'eau de pluie ?","q2":"L'eau des oceans peut-elle devenir pluie ?","q3":"L'eau qui s'evapore en mer est-elle salee quand elle tombe en pluie ?","hints":["evaporation","oui","non","sel","pure","reste"]},
    {"id":"t08","topic":"Photosynthese","q1":"De quoi les plantes ont-elles besoin pour pousser ?","q2":"Une plante dans le noir finit-elle par mourir ?","q3":"Si on donne eau et engrais sans lumiere, la plante survit-elle ?","hints":["lumiere","oui","non","photosynthese","meurt"]},
    {"id":"t09","topic":"Electricite statique","q1":"Pourquoi recoit-on un choc en touchant une poignee de porte ?","q2":"Ce choc est-il dangereux ?","q3":"Comment se decharger sans choc ?","hints":["statique","non","conducteur","terre","inoffensif","decharge"]},
    {"id":"t10","topic":"Ombre et lumiere","q1":"Comment se forme une ombre ?","q2":"Peut-on avoir une ombre sans source de lumiere ?","q3":"Pourquoi l'ombre est-elle plus longue le matin que le midi ?","hints":["non","lumiere","source","angle","bas","matin"]},
]


# ── Classe principale ─────────────────────────────────────────────────────────

class ComprehensionChecker:
    """
    Verifie la comprehension reelle vs simulation via 3 types de tests.
    Compatible Ollama (Mistral, Llama, etc.).
    """

    COS_PREFIX = (
        "Avant de repondre, simule mentalement la situation :\n"
        "1. Decris l'etat initial\n"
        "2. Decris ce qui change (l'action ou l'evenement)\n"
        "3. Decris l'etat final\n"
        "4. Reponds a la question\n\nQuestion : "
    )

    def __init__(self, ollama_url="http://localhost:11434", model="mistral",
                 timeout=60, verbose=False):
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.verbose = verbose

    # ── Bas niveau ────────────────────────────────────────────────────────────

    def ask(self, question: str, use_cos: bool = False) -> str:
        """Appelle Ollama et retourne la reponse texte."""
        prompt = f"{self.COS_PREFIX}{question}" if use_cos else question
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 512},
        }
        if self.verbose:
            print(f"\n>> {'[CoS] ' if use_cos else ''}{question[:70]}...")
        try:
            r = requests.post(f"{self.ollama_url}/api/generate",
                              json=payload, timeout=self.timeout)
            r.raise_for_status()
            ans = r.json().get("response", "").strip()
        except requests.exceptions.ConnectionError:
            ans = "[ERREUR] Ollama inaccessible."
        except requests.exceptions.Timeout:
            ans = "[ERREUR] Timeout."
        except Exception as e:
            ans = f"[ERREUR] {e}"
        if self.verbose:
            print(f"<< {ans[:100]}...")
        return ans

    def _has_kw(self, text: str, keywords: list) -> bool:
        t = text.lower()
        return any(k.lower() in t for k in keywords)

    def score_to_level(self, score: float) -> str:
        """Convertit un score 0-1 en niveau de comprehension."""
        if score < 0.30:
            return "Simulation pure (< 30%)"
        elif score < 0.60:
            return "Comprehension partielle (30-60%)"
        elif score < 0.80:
            return "Bonne comprehension (60-80%)"
        else:
            return "Comprehension robuste (>= 80%)"

    # ── Test 1 : Causalite physique ───────────────────────────────────────────

    def test_physical_causality(self, questions=None, use_cos=False) -> dict:
        """
        Test 1 : coherence causale physique.
        Valide par presence de mots-cles semantiques corrects.
        Retourne : {score, correct, total, level, errors, details}
        """
        if questions is None:
            questions = PHYSICAL_CAUSALITY_QUESTIONS
        details, errors, correct = [], [], 0

        for q in questions:
            ans = self.ask(q["question"], use_cos=use_cos)
            passed = self._has_kw(ans, q["kw"])
            details.append({"id": q["id"], "question": q["question"],
                             "expected": q["concept"], "answer": ans,
                             "passed": passed})
            if passed:
                correct += 1
            else:
                errors.append({"id": q["id"], "expected": q["concept"],
                                "got": ans[:180]})
            time.sleep(0.3)

        score = correct / len(questions) if questions else 0.0
        return {"test": "physical_causality", "use_cos": use_cos,
                "score": round(score, 3), "correct": correct,
                "total": len(questions), "level": self.score_to_level(score),
                "errors": errors, "details": details}

    # ── Test 2 : Generalisation compositionnelle ──────────────────────────────

    def test_compositional_generalization(self, concept_rules=None, use_cos=False) -> dict:
        """
        Test 2 : generalisation compositionnelle.
        Presente une regle puis une variation dans un nouveau contexte.
        Retourne : {score, correct, total, level, errors, details}
        """
        if concept_rules is None:
            concept_rules = COMPOSITIONAL_GENERALIZATION_RULES
        details, errors, correct = [], [], 0

        for r in concept_rules:
            prompt = f"Regle connue : {r['rule']}\nQuestion : {r['variation']}"
            ans = self.ask(prompt, use_cos=use_cos)
            passed = self._has_kw(ans, r["kw"])
            details.append({"id": r["id"], "rule": r["rule"],
                             "variation": r["variation"],
                             "expected": r["exp"], "answer": ans,
                             "passed": passed})
            if passed:
                correct += 1
            else:
                errors.append({"id": r["id"], "variation": r["variation"],
                                "expected": r["exp"], "got": ans[:180]})
            time.sleep(0.3)

        score = correct / len(concept_rules) if concept_rules else 0.0
        return {"test": "compositional_generalization", "use_cos": use_cos,
                "score": round(score, 3), "correct": correct,
                "total": len(concept_rules), "level": self.score_to_level(score),
                "errors": errors, "details": details}

    # ── Test 3 : Coherence temporelle ─────────────────────────────────────────

    def test_temporal_coherence(self, question_triplets=None, use_cos=False) -> dict:
        """
        Test 3 : coherence temporelle.
        Pose 3 formulations du meme sujet, verifie la coherence par hints.
        Retourne : {score, correct, total, level, errors, details}
        """
        if question_triplets is None:
            question_triplets = TEMPORAL_COHERENCE_TRIPLETS
        details, errors, correct = [], [], 0

        for triplet in question_triplets:
            a1 = self.ask(triplet["q1"], use_cos=use_cos); time.sleep(0.2)
            a2 = self.ask(triplet["q2"], use_cos=use_cos); time.sleep(0.2)
            a3 = self.ask(triplet["q3"], use_cos=use_cos); time.sleep(0.2)

            combined = f"{a1} {a2} {a3}".lower()
            found = sum(1 for h in triplet["hints"] if h.lower() in combined)
            threshold = max(1, len(triplet["hints"]) // 2)
            passed = found >= threshold

            details.append({"id": triplet["id"], "topic": triplet["topic"],
                             "q1": triplet["q1"], "a1": a1,
                             "q2": triplet["q2"], "a2": a2,
                             "q3": triplet["q3"], "a3": a3,
                             "hints_found": found,
                             "hints_total": len(triplet["hints"]),
                             "passed": passed})
            if passed:
                correct += 1
            else:
                errors.append({"id": triplet["id"], "topic": triplet["topic"],
                                "hints_found": found, "threshold": threshold,
                                "a1": a1[:100], "a2": a2[:100], "a3": a3[:100]})
            time.sleep(0.3)

        score = correct / len(question_triplets) if question_triplets else 0.0
        return {"test": "temporal_coherence", "use_cos": use_cos,
                "score": round(score, 3), "correct": correct,
                "total": len(question_triplets), "level": self.score_to_level(score),
                "errors": errors, "details": details}

    # ── Diagnostic complet ────────────────────────────────────────────────────

    def run_full_diagnosis(self, compare_cos=True) -> dict:
        """
        Lance les 3 tests (avec et sans CoS) et retourne le rapport complet.

        Args:
            compare_cos: Si True, double chaque test avec Chain-of-Simulation.

        Returns:
            Dictionnaire rapport complet avec scores, comparaisons, verdict.
        """
        print(f"\n{'='*60}")
        print(f"  DIAGNOSTIC BeaMax | {self.model} @ {self.ollama_url}")
        print(f"{'='*60}")

        R = {}

        print("\n[TEST 1] Causalite physique — mode direct")
        R["phys_direct"] = self.test_physical_causality(use_cos=False)
        _p(R["phys_direct"])

        print("\n[TEST 2] Generalisation compositionnelle — mode direct")
        R["comp_direct"] = self.test_compositional_generalization(use_cos=False)
        _p(R["comp_direct"])

        print("\n[TEST 3] Coherence temporelle — mode direct")
        R["temp_direct"] = self.test_temporal_coherence(use_cos=False)
        _p(R["temp_direct"])

        if compare_cos:
            print("\n[TEST 1] Causalite physique — Chain-of-Simulation")
            R["phys_cos"] = self.test_physical_causality(use_cos=True)
            _p(R["phys_cos"])

            print("\n[TEST 2] Generalisation compositionnelle — Chain-of-Simulation")
            R["comp_cos"] = self.test_compositional_generalization(use_cos=True)
            _p(R["comp_cos"])

            print("\n[TEST 3] Coherence temporelle — Chain-of-Simulation")
            R["temp_cos"] = self.test_temporal_coherence(use_cos=True)
            _p(R["temp_cos"])

        # Scores globaux
        direct_scores = [R["phys_direct"]["score"],
                         R["comp_direct"]["score"],
                         R["temp_direct"]["score"]]
        g_direct = sum(direct_scores) / 3

        report = {
            "model": self.model,
            "ollama_url": self.ollama_url,
            "global_score_direct": round(g_direct, 3),
            "global_level_direct": self.score_to_level(g_direct),
            "per_test_direct": {
                "physical_causality": R["phys_direct"]["score"],
                "compositional_generalization": R["comp_direct"]["score"],
                "temporal_coherence": R["temp_direct"]["score"],
            },
        }

        if compare_cos:
            cos_scores = [R["phys_cos"]["score"],
                          R["comp_cos"]["score"],
                          R["temp_cos"]["score"]]
            g_cos = sum(cos_scores) / 3
            improvement = g_cos - g_direct

            report["global_score_cos"] = round(g_cos, 3)
            report["global_level_cos"] = self.score_to_level(g_cos)
            report["per_test_cos"] = {
                "physical_causality": R["phys_cos"]["score"],
                "compositional_generalization": R["comp_cos"]["score"],
                "temporal_coherence": R["temp_cos"]["score"],
            }
            report["cos_improvement"] = round(improvement, 3)
            report["cos_verdict"] = _cos_verdict(improvement)

        report["raw_results"] = R

        print("\n" + "="*60)
        print(f"  SCORE GLOBAL (direct) : {g_direct:.0%}  — {report['global_level_direct']}")
        if compare_cos:
            print(f"  SCORE GLOBAL (CoS)    : {g_cos:.0%}  — {report['global_level_cos']}")
            print(f"  AMELIORATION CoS      : {improvement:+.1%}")
        print("="*60 + "\n")

        return report


    # ── Wrapper meta_orchestrator ───────────────────────────────────────────────

    async def check(self, goal: str) -> dict:
        """
        Wrapper léger pour meta_orchestrator : vérifie si le goal est bien formulé.
        Retourne {"understood": bool, "clarification_needed": str}
        """
        try:
            # Prompt minimal de vérification de compréhension
            prompt = (
                f"Tu dois exécuter cette mission : {goal[:300]}\n\n"
                "Est-ce que l'objectif est clair et complet ? "
                "Réponds en JSON : {\"understood\": true/false, \"clarification_needed\": \"<vide ou question>\"}. "
                "Ne réponds qu'avec le JSON, rien d'autre."
            )
            response = self.ask(prompt, use_cos=False)
            import json as _json
            # Extraire le JSON de la réponse
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return _json.loads(response[start:end])
            return {"understood": True, "clarification_needed": ""}
        except Exception:
            return {"understood": True, "clarification_needed": ""}


# ── Helpers module-level ──────────────────────────────────────────────────────

def _p(result: dict):
    print(f"  -> {result['correct']}/{result['total']}  "
          f"Score={result['score']:.0%}  |  {result['level']}")

def _cos_verdict(improvement: float) -> str:
    if improvement > 0.20:
        return ("Amelioration forte (>20%). CoS aide significativement, "
                "mais reste une compensation superficielle : le modele simule "
                "mieux quand on lui donne la structure, pas quand il comprend vraiment.")
    elif improvement > 0.10:
        return ("Amelioration moderee (10-20%). CoS oriente le modele vers "
                "un raisonnement structure. L'effet est reel mais fragile : "
                "il disparait sur des variantes non vues.")
    elif improvement > 0.03:
        return ("Amelioration marginale (3-10%). CoS aide peu. Le modele "
                "plafonne probablement par manque de grounding physique.")
    else:
        return ("Pas d'amelioration (<3%). CoS n'a pas d'impact. "
                "Le probleme est plus profond que le prompting peut resoudre.")


# ── CLI rapide ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Diagnostic de comprehension pour LLMs via Ollama")
    parser.add_argument("--url", default="http://localhost:11434",
                        help="URL Ollama (defaut: http://localhost:11434)")
    parser.add_argument("--model", default="mistral",
                        help="Modele Ollama (defaut: mistral)")
    parser.add_argument("--no-cos", action="store_true",
                        help="Desactive la comparaison Chain-of-Simulation")
    parser.add_argument("--verbose", action="store_true",
                        help="Affiche les questions/reponses brutes")
    parser.add_argument("--output", default=None,
                        help="Sauvegarde le rapport JSON dans ce fichier")
    args = parser.parse_args()

    checker = ComprehensionChecker(
        ollama_url=args.url,
        model=args.model,
        verbose=args.verbose,
    )

    report = checker.run_full_diagnosis(compare_cos=not args.no_cos)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Rapport sauvegarde dans : {args.output}")
    else:
        # Affiche un resume
        print(json.dumps({k: v for k, v in report.items()
                          if k != "raw_results"}, ensure_ascii=False, indent=2))
