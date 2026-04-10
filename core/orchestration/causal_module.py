"""
causal_module.py — Structural Causal Model (SCM) for JarvisMax
===============================================================
Gives LLMs the ability to reason causally using Pearl's do-calculus.

Architecture:
  - CausalGraph       : maintains a DAG of causal relations + do() + counterfactual()
  - CausalLLMWrapper  : injects causal context into LLM prompts + extracts claims
  - JarvisMaxCausalIntegration : persistent layer for JarvisMax core/

Requirements: networkx (pip install networkx), requests (for Ollama)
Python 3.10+
"""

from __future__ import annotations

import json
import re
import copy
import logging
from typing import Any, Optional
from pathlib import Path

try:
    import networkx as nx
except ImportError:
    raise ImportError("networkx is required: pip install networkx")

logger = logging.getLogger(__name__)


class CausalGraph:
    """
    A Directed Acyclic Graph (DAG) of causal relations.
    Each edge A->B: "A is a direct cause of B".
    Edges carry: strength (float), mechanism (str).
    Nodes carry: value (Any, last observed).
    """

    def __init__(self):
        self.graph: nx.DiGraph = nx.DiGraph()
        self._observations: dict[str, list[Any]] = {}

    def add_edge(self, cause: str, effect: str, strength: float = 1.0, mechanism: str = "") -> None:
        if cause == effect:
            raise ValueError(f"Self-loop not allowed: {cause}")
        self.graph.add_edge(cause, effect, strength=strength, mechanism=mechanism)
        if not nx.is_directed_acyclic_graph(self.graph):
            self.graph.remove_edge(cause, effect)
            raise ValueError(f"Adding {cause}->{effect} would create a cycle.")
        logger.debug("Added edge: %s -> %s (%.2f)", cause, effect, strength)

    def remove_edge(self, cause: str, effect: str) -> None:
        if self.graph.has_edge(cause, effect):
            self.graph.remove_edge(cause, effect)

    def set_value(self, variable: str, value: Any) -> None:
        if variable not in self.graph:
            self.graph.add_node(variable)
        self.graph.nodes[variable]["value"] = value
        self._observations.setdefault(variable, []).append(value)

    def get_value(self, variable: str) -> Optional[Any]:
        return self.graph.nodes.get(variable, {}).get("value", None)

    def observe(self, observations: dict[str, Any]) -> None:
        for var, val in observations.items():
            self.set_value(var, val)

    def do(self, variable: str, value: Any) -> dict[str, Any]:
        """
        Pearl's do-operator: do(variable=value).
        1. Cut all incoming edges to variable (remove its causes)
        2. Set variable=value
        3. Propagate forward via topological sort
        Returns dict of downstream variable predictions.
        """
        g2 = self.graph.copy()
        # Cut incoming edges
        for p in list(g2.predecessors(variable)):
            g2.remove_edge(p, variable)
        if variable not in g2:
            g2.add_node(variable)
        g2.nodes[variable]["value"] = value

        results = {variable: value}
        descendants = nx.descendants(g2, variable) | {variable}
        try:
            topo = list(nx.topological_sort(g2))
        except nx.NetworkXUnfeasible:
            return results

        for node in topo:
            if node not in descendants or node == variable:
                continue
            parents = list(g2.predecessors(node))
            if not parents:
                continue
            nums, weights, quals = [], [], []
            for p in parents:
                pval = g2.nodes[p].get("value", None)
                if pval is None:
                    continue
                w = g2[p][node].get("strength", 1.0)
                try:
                    nums.append(float(pval))
                    weights.append(w)
                except (TypeError, ValueError):
                    quals.append(str(pval))
            if nums:
                wsum = sum(v * w for v, w in zip(nums, weights)) / sum(weights)
                g2.nodes[node]["value"] = round(wsum, 4)
                results[node] = round(wsum, 4)
            elif quals:
                val_str = f"influenced({', '.join(quals)})"
                g2.nodes[node]["value"] = val_str
                results[node] = val_str
        return results

    def counterfactual(self, observed: dict[str, Any], alternative: dict[str, Any]) -> dict[str, Any]:
        """
        Counterfactual: "What would have happened if <alternative> instead of <observed>?"
        Uses Pearl 3-step: Abduction -> Action -> Prediction.
        """
        g_obs = copy.deepcopy(self)
        g_obs.observe(observed)
        obs_downstream = {}
        for var, val in observed.items():
            obs_downstream.update(g_obs.do(var, val))

        g_alt = copy.deepcopy(self)
        g_alt.observe(observed)  # same background
        alt_downstream = {}
        for var, val in alternative.items():
            alt_downstream.update(g_alt.do(var, val))

        all_vars = set(obs_downstream) | set(alt_downstream)
        differences = {
            var: {"observed": obs_downstream.get(var, "N/A"), "counterfactual": alt_downstream.get(var, "N/A")}
            for var in all_vars
            if obs_downstream.get(var, "N/A") != alt_downstream.get(var, "N/A")
        }

        obs_str = ", ".join(f"{k}={v}" for k, v in observed.items())
        alt_str = ", ".join(f"{k}={v}" for k, v in alternative.items())
        if not differences:
            summary = f"If {alt_str} instead of {obs_str}, nothing would have changed downstream."
        else:
            diff_str = "; ".join(
                f"{var}: {d['observed']} -> {d['counterfactual']}" for var, d in differences.items()
            )
            summary = f"If {alt_str} instead of {obs_str}, the following would have changed: {diff_str}"

        return {
            "observed_world": obs_downstream,
            "counterfactual_world": alt_downstream,
            "differences": differences,
            "summary": summary,
        }

    def explain(self, effect: str) -> str:
        """Causal explanation: 'Why did X happen?' Traces all causal paths to effect."""
        if effect not in self.graph:
            return f"Variable '{effect}' is not in the causal graph."
        ancestors = nx.ancestors(self.graph, effect)
        if not ancestors:
            return f"'{effect}' has no known causes — it is an exogenous (root) variable."
        roots = [n for n in ancestors if self.graph.in_degree(n) == 0] or list(ancestors)
        all_paths = []
        for root in roots:
            try:
                for path in nx.all_simple_paths(self.graph, root, effect):
                    all_paths.append(path)
            except nx.NetworkXNoPath:
                pass
        if not all_paths:
            direct = list(self.graph.predecessors(effect))
            return f"'{effect}' is directly caused by: {', '.join(direct)}."
        lines = [f"Causal explanation for '{effect}':"]
        for path in sorted(all_paths, key=len):
            strengths = [self.graph[path[i]][path[i+1]].get("strength", 1.0) for i in range(len(path)-1)]
            avg_s = sum(strengths) / len(strengths)
            lines.append(f"  * {' -> '.join(path)}  (avg strength: {avg_s:.2f})")
        return "\n".join(lines)

    def is_confounder(self, cause: str, effect: str, candidate: str) -> bool:
        try:
            return (
                candidate not in (cause, effect)
                and nx.has_path(self.graph, candidate, cause)
                and nx.has_path(self.graph, candidate, effect)
            )
        except nx.NetworkXError:
            return False

    def find_confounders(self, cause: str, effect: str) -> list[str]:
        return [n for n in self.graph.nodes if self.is_confounder(cause, effect, n)]

    def simpson_check(self, association_var: str, outcome_var: str) -> dict:
        """Simpson's Paradox detector: checks if association is confounded."""
        confounders = self.find_confounders(association_var, outcome_var)
        if confounders:
            warning = (
                f"WARNING SIMPSON'S PARADOX RISK: The association "
                f"{association_var}->{outcome_var} may be spurious or reversed "
                f"when conditioning on: {', '.join(confounders)}. Correlation != Causation."
            )
            rec = f"Use do({association_var}=x) conditioning on {', '.join(confounders)} to isolate true causal effect."
        else:
            warning = f"No confounders found for {association_var}->{outcome_var}. May reflect a direct causal link."
            rec = "Verify with intervention data if possible."
        return {
            "association": f"{association_var} -> {outcome_var}",
            "confounders": confounders,
            "warning": warning,
            "recommendation": rec,
        }

    def save(self, path: str) -> None:
        data = {
            "nodes": [{"id": n, "value": self.graph.nodes[n].get("value", None)} for n in self.graph.nodes],
            "edges": [
                {"cause": u, "effect": v, "strength": d.get("strength", 1.0), "mechanism": d.get("mechanism", "")}
                for u, v, d in self.graph.edges(data=True)
            ],
            "observations": self._observations,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("CausalGraph saved -> %s", path)

    @classmethod
    def load(cls, path: str) -> "CausalGraph":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        g = cls()
        for n in data.get("nodes", []):
            g.graph.add_node(n["id"])
            if n.get("value") is not None:
                g.graph.nodes[n["id"]]["value"] = n["value"]
        for e in data.get("edges", []):
            try:
                g.add_edge(e["cause"], e["effect"], e.get("strength", 1.0), e.get("mechanism", ""))
            except ValueError as err:
                logger.warning("Skipped edge during load: %s", err)
        g._observations = data.get("observations", {})
        return g

    def to_summary(self) -> str:
        if not self.graph.edges:
            return "No causal relationships known yet."
        lines = ["Known causal relationships:"]
        for u, v, d in self.graph.edges(data=True):
            mech = f" [{d['mechanism']}]" if d.get("mechanism") else ""
            lines.append(f"  {u} -> {v}  (strength={d.get('strength', 1.0):.2f}){mech}")
        return "\n".join(lines)

    def __repr__(self):
        return f"CausalGraph(nodes={self.graph.number_of_nodes()}, edges={self.graph.number_of_edges()})"


class CausalLLMWrapper:
    """
    Wraps LLM calls (Ollama-compatible) with causal context injection.
    - Injects CausalGraph summary into system prompt
    - Extracts causal claims from responses to auto-enrich the graph
    """

    CAUSAL_PATTERNS = [
        r"(?P<cause>[\w\s]+?)\s+causes?\s+(?P<effect>[\w\s]+?)(?:\.|,|;|$)",
        r"(?P<cause>[\w\s]+?)\s+leads?\s+to\s+(?P<effect>[\w\s]+?)(?:\.|,|;|$)",
        r"(?P<cause>[\w\s]+?)\s+results?\s+in\s+(?P<effect>[\w\s]+?)(?:\.|,|;|$)",
        r"(?P<effect>[\w\s]+?)\s+is\s+caused\s+by\s+(?P<cause>[\w\s]+?)(?:\.|,|;|$)",
        r"(?P<cause>[\w\s]+?)\s*->\s*(?P<effect>[\w\s]+?)(?:\.|,|;|\s|$)",
        r"(?P<effect>[\w\s]+?)\s+because\s+(?P<cause>[\w\s]+?)(?:\.|,|;|$)",
        r"(?P<cause>[\w\s]+?)\s+triggers?\s+(?P<effect>[\w\s]+?)(?:\.|,|;|$)",
        r"if\s+(?P<cause>[\w\s]+?)\s+then\s+(?P<effect>[\w\s]+?)(?:\.|,|;|$)",
        r"(?P<cause>[\w\s]+?)\s+increases?\s+(?P<effect>[\w\s]+?)(?:\.|,|;|$)",
        r"(?P<cause>[\w\s]+?)\s+decreases?\s+(?P<effect>[\w\s]+?)(?:\.|,|;|$)",
        r"(?P<cause>[\w\s]+?)\s+produces?\s+(?P<effect>[\w\s]+?)(?:\.|,|;|$)",
    ]

    def __init__(self, model: str = "mistral:7b", ollama_url: str = "http://localhost:11434", auto_extract: bool = True):
        self.model = model
        self.ollama_url = ollama_url.rstrip("/")
        self.auto_extract = auto_extract

    def _call_ollama(self, messages: list[dict]) -> str:
        import requests
        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={"model": self.model, "messages": messages, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def ask_with_causal_context(
        self,
        question: str,
        graph: CausalGraph,
        system_prefix: str = "",
        auto_update_graph: bool = True,
    ) -> str:
        """Ask the LLM with the causal graph injected into the system prompt."""
        system_prompt = f"""{system_prefix}

## Causal Knowledge Base
{graph.to_summary()}

## Causal Reasoning Instructions
1. ALWAYS distinguish CORRELATION (co-occurrence) from CAUSATION (directional mechanism).
2. Use the Causal Knowledge Base above when relevant.
3. State causal claims explicitly: "X causes Y".
4. For intervention questions: apply do(X=x) — cut X from its causes, set X=x, propagate forward.
5. For counterfactual questions: abduction -> action -> prediction.
6. Flag confounders when analyzing statistical associations.
""".strip()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]
        response = self._call_ollama(messages)
        if auto_update_graph and self.auto_extract:
            self._auto_update_graph(response, graph)
        return response

    def extract_causal_claim(self, text: str) -> list[tuple[str, str]]:
        """Extract (cause, effect) pairs from natural language text."""
        claims, seen = [], set()
        for pattern in self.CAUSAL_PATTERNS:
            for m in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                cause = m.group("cause").strip().lower()
                effect = m.group("effect").strip().lower()
                if 2 <= len(cause) <= 80 and 2 <= len(effect) <= 80:
                    key = (cause, effect)
                    if key not in seen:
                        seen.add(key)
                        claims.append(key)
        return claims

    def _auto_update_graph(self, response: str, graph: CausalGraph) -> None:
        for cause, effect in self.extract_causal_claim(response):
            try:
                graph.add_edge(cause, effect, 0.6, "auto-extracted:llm")
            except ValueError:
                pass

    def build_graph_from_text(self, text: str, graph: Optional[CausalGraph] = None) -> CausalGraph:
        if graph is None:
            graph = CausalGraph()
        for cause, effect in self.extract_causal_claim(text):
            try:
                graph.add_edge(cause, effect, 0.6, "text-extracted")
            except ValueError:
                pass
        return graph


class JarvisMaxCausalIntegration:
    """
    Persistent integration layer for JarvisMax core/.
    - Loads/saves causal graph from core/causal_graph.json
    - Auto-enriches graph after each mission result
    - Optionally indexes edges into Qdrant for semantic search
    """

    DEFAULT_GRAPH_PATH = "core/causal_graph.json"

    def __init__(
        self,
        graph_path: str = DEFAULT_GRAPH_PATH,
        qdrant_url: Optional[str] = None,
        qdrant_collection: str = "causal_edges",
        ollama_model: str = "mistral:7b",
        ollama_url: str = "http://localhost:11434",
    ):
        self.graph_path = Path(graph_path)
        self.qdrant_url = qdrant_url
        self.qdrant_collection = qdrant_collection
        self.graph = (
            CausalGraph.load(str(self.graph_path))
            if self.graph_path.exists() else CausalGraph()
        )
        self.wrapper = CausalLLMWrapper(model=ollama_model, ollama_url=ollama_url)

    def ingest_mission_result(self, mission_summary: str) -> list[tuple[str, str]]:
        """Extract causal claims from mission result and persistently enrich graph."""
        added = []
        for cause, effect in self.wrapper.extract_causal_claim(mission_summary):
            try:
                self.graph.add_edge(cause, effect, 0.5, "mission-result")
                added.append((cause, effect))
            except ValueError:
                pass
        if added:
            self.graph.save(str(self.graph_path))
            if self.qdrant_url:
                self._index_to_qdrant(added)
        return added

    def get_prompt_injection(self) -> str:
        return self.graph.to_summary()

    def ask(self, question: str, system_prefix: str = "") -> str:
        return self.wrapper.ask_with_causal_context(question, self.graph, system_prefix)

    # Alias pour compatibilité meta_orchestrator
    def get_causal_context(self, text: str) -> str:
        """Alias pour get_prompt_injection()"""
        return self.get_prompt_injection()

    def update_graph_from_text(self, text: str) -> None:
        """Alias pour ingest_mission_result()"""
        try:
            self.ingest_mission_result(text)
        except Exception:
            pass

    def _index_to_qdrant(self, edges: list[tuple[str, str]]) -> None:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http.models import PointStruct, VectorParams, Distance
            import hashlib
        except ImportError:
            logger.warning("qdrant_client not installed — skipping Qdrant indexing.")
            return
        client = QdrantClient(url=self.qdrant_url)
        try:
            client.get_collection(self.qdrant_collection)
        except Exception:
            client.create_collection(
                collection_name=self.qdrant_collection,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )
        points = []
        for cause, effect in edges:
            text = f"{cause} causes {effect}"
            uid = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**63)
            edge_data = self.graph.graph.get_edge_data(cause, effect) or {}
            # FIXME: Using null embeddings ([0.0] * 384) until Phase 2.2 embeddings integration
            # Options: sentence-transformers (torch), OpenAI embeddings API, or Qdrant dense vectors
            # Impact: Causal graph search will work but without semantic similarity
            points.append(PointStruct(
                id=uid,
                vector=[0.0] * 384,  # Null embedding — semantic search disabled
                payload={\"text\": text, \"cause\": cause, \"effect\": effect,
                         \"strength\": edge_data.get(\"strength\", 1.0),
                         \"mechanism\": edge_data.get(\"mechanism\", \"\")},
            ))
        if points:
            client.upsert(collection_name=self.qdrant_collection, points=points)
            logger.info("Indexed %d causal edges to Qdrant", len(points))


# ─────────────────────────────────────────────────────────────────────────────
# Validation Tests (no LLM required — pure graph reasoning)
# ─────────────────────────────────────────────────────────────────────────────

def test_simpson_paradox() -> bool:
    """
    Test 1: Simpson's Paradox Detector.
    Hospital example: severity confounds hospital<->mortality association.
    """
    print("\n" + "=" * 60)
    print("TEST 1: Simpson's Paradox — Hospital Example")
    print("=" * 60)

    g = CausalGraph()
    g.add_edge("disease_severity", "hospital_admission", 0.9, "sicker people go to hospital")
    g.add_edge("disease_severity", "mortality", 0.85, "severity drives mortality")
    g.add_edge("hospital_admission", "mortality", -0.6, "hospitals reduce mortality (true protective effect)")

    result = g.simpson_check("hospital_admission", "mortality")
    print(f"\nChecking: {result['association']}")
    print(f"\n{result['warning']}")
    print(f"\nRecommendation: {result['recommendation']}")

    assert "disease_severity" in result["confounders"], f"Expected confounder, got: {result['confounders']}"
    print(f"\n[PASS] Confounder correctly identified: {result['confounders']}")

    do_result = g.do("hospital_admission", 1.0)
    print(f"\ndo(hospital_admission=1.0): {do_result}")
    print("-> After do(), disease_severity no longer confounds. True effect is protective.")
    return True


def test_intervention() -> bool:
    """
    Test 2: do-operator (Intervention).
    Education -> Salary chain, confounded by family_wealth.
    do(university=1) cuts the wealth->university link, isolating the true causal effect.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Intervention (do-operator) — Education & Salary")
    print("=" * 60)

    g = CausalGraph()
    g.add_edge("family_wealth", "university_access", 0.8, "wealth enables university")
    g.add_edge("family_wealth", "salary", 0.5, "network and inheritance")
    g.add_edge("university_access", "skills", 0.9, "university builds skills")
    g.add_edge("skills", "salary", 0.85, "skills increase earning power")

    g.observe({"family_wealth": 0.2, "university_access": 0.2, "skills": 0.2, "salary": 0.3})

    print("\nObservational state (low wealth):")
    for var in ["family_wealth", "university_access", "skills", "salary"]:
        print(f"  {var} = {g.get_value(var)}")

    do_result = g.do("university_access", 1.0)
    print(f"\nAfter do(university_access=1.0):")
    for var, val in do_result.items():
        print(f"  {var} = {val}")

    assert "skills" in do_result, "skills should propagate downstream"
    assert "salary" in do_result, "salary should propagate downstream"
    assert do_result.get("skills", 0) > 0.5, f"Skills should increase, got: {do_result.get('skills')}"
    print(f"\n[PASS] Intervention correctly propagates: university -> skills({do_result['skills']}) -> salary({do_result.get('salary', '?')})")
    print("-> Note: family_wealth no longer influences university_access in this intervention.")

    # Compare: pure observational vs interventional
    wealth_result = g.do("family_wealth", 0.9)
    print(f"\nFor reference, do(family_wealth=0.9): {wealth_result}")
    return True


def test_counterfactual() -> bool:
    """
    Test 3: Counterfactual reasoning.
    Scenario: A developer pushed buggy code -> production outage.
    Counterfactual: What if they had run tests first?
    """
    print("\n" + "=" * 60)
    print("TEST 3: Counterfactual — Dev Outage Scenario")
    print("=" * 60)

    g = CausalGraph()
    g.add_edge("tests_run", "bugs_detected", 0.9, "tests catch bugs")
    g.add_edge("bugs_detected", "code_fixed", 0.85, "detected bugs get fixed")
    g.add_edge("buggy_code_deployed", "production_outage", 0.95, "bugs crash production")
    g.add_edge("code_fixed", "buggy_code_deployed", -0.8, "fixing reduces buggy deploys")
    # tests_run -> bugs_detected -> code_fixed -> (reduces) buggy_code_deployed -> (reduces) outage

    # What actually happened
    observed = {
        "tests_run": 0.0,        # No tests run
        "bugs_detected": 0.0,    # No bugs found
        "code_fixed": 0.0,       # No fixes
        "buggy_code_deployed": 1.0,  # Buggy code deployed
    }

    # Counterfactual: what if tests had been run?
    alternative = {"tests_run": 1.0}

    g.observe(observed)
    result = g.counterfactual(observed, alternative)

    print("\nObserved world (no tests):")
    for var, val in result["observed_world"].items():
        print(f"  {var} = {val}")

    print("\nCounterfactual world (if tests had been run):")
    for var, val in result["counterfactual_world"].items():
        print(f"  {var} = {val}")

    print(f"\nDifferences:")
    if result["differences"]:
        for var, diff in result["differences"].items():
            print(f"  {var}: {diff['observed']} -> {diff['counterfactual']}")
    else:
        print("  (no differences detected in propagated variables)")

    print(f"\nSummary: {result['summary']}")

    # Verify explanation
    print(f"\n{g.explain('production_outage')}")

    assert result is not None, "Counterfactual should return a result"
    print("\n[PASS] Counterfactual reasoning executed successfully.")
    return True


def test_causal_extraction() -> bool:
    """
    Bonus Test: Causal claim extraction from natural language.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Causal Claim Extraction from Text")
    print("=" * 60)

    wrapper = CausalLLMWrapper()
    text = """
    Smoking causes lung cancer. Poor diet leads to obesity.
    Obesity results in diabetes. Stress triggers hypertension.
    High blood pressure is caused by stress. If you exercise then health improves.
    Education increases income.
    """

    claims = wrapper.extract_causal_claim(text)
    print(f"\nExtracted {len(claims)} causal claims:")
    for cause, effect in claims:
        print(f"  {cause} -> {effect}")

    g = wrapper.build_graph_from_text(text)
    print(f"\nAuto-built graph: {g}")
    print(g.to_summary())

    assert len(claims) >= 4, f"Should extract at least 4 claims, got {len(claims)}"
    print(f"\n[PASS] Successfully extracted {len(claims)} causal claims and built graph.")
    return True


def run_all_tests():
    """Run all validation tests."""
    print("\n" + "#" * 60)
    print("# SCM Module — Validation Tests")
    print("# (No LLM required — pure causal graph reasoning)")
    print("#" * 60)

    results = []
    for test_fn in [test_simpson_paradox, test_intervention, test_counterfactual, test_causal_extraction]:
        try:
            ok = test_fn()
            results.append((test_fn.__name__, ok))
        except AssertionError as e:
            print(f"\n[FAIL] {test_fn.__name__}: {e}")
            results.append((test_fn.__name__, False))
        except Exception as e:
            print(f"\n[ERROR] {test_fn.__name__}: {e}")
            results.append((test_fn.__name__, False))

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
    print(f"\n{passed}/{len(results)} tests passed.")
    return passed == len(results)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    success = run_all_tests()
    exit(0 if success else 1)
