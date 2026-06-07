"""
BEA MAX — ExecutionGuard                             v1.0
Niveau 1 : vérification formelle de chaque action critique.

Principe : pour CHAQUE action, la preuve de l'effet est obligatoire.
Jamais implicite — toujours vérifiée, toujours loggée.

5 étapes pour les actions fichier :
    1. WRITE   — écriture / modification demandée
    2. EXISTS  — vérification que le fichier existe sur disque
    3. READ    — lecture du contenu réel
    4. EXECUTE — si script Python : exécution réelle + capture sortie
    5. VALIDATE — comparaison attendu ↔ réel (contenu, returncode, syntaxe)

Logs structurés :
    [GUARD OK]   tag="[GUARD OK]"   → toutes les étapes passées
    [GUARD FAIL] tag="[GUARD FAIL]" → première étape échouée + détail

Interface principale :
    guard = get_guard()

    # Après write_file :
    result = await guard.guard_write(path, expected_content)

    # Après replace_in_file :
    result = await guard.guard_replace(path, old_str, new_str)

    # Après exécution script :
    result = await guard.guard_script(script_path)

    # Dans pipeline.apply_patch (self_improve) :
    result = await guard.guard_patch(file_path, old_str, new_str, finding_id)

Intégration :
    - executor/runner.py      : _write_file, _replace_in_file
    - self_improve/pipeline.py: apply_patch
    - (optionnel) tools/       : tout write externe

Aucune dépendance interne (stdlib uniquement) — pas de import circulaire.
"""
from __future__ import annotations

import ast
import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Constantes ─────────────────────────────────────────────────────────────────
SCRIPT_TIMEOUT_S = 30    # max secondes pour exécution d'un script de garde


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURES DE DONNÉES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class StepResult:
    """Résultat d'une étape individuelle."""
    step:       str   # "write" | "exists" | "read" | "execute" | "validate" | "syntax"
    passed:     bool
    detail:     str = ""
    elapsed_ms: int = 0

    def icon(self) -> str:
        return "✓" if self.passed else "✗"


@dataclass
class GuardResult:
    """
    Résultat complet d'une garde.

    Attributs :
        passed      : True ssi toutes les étapes ont réussi
        action_type : "write_file" | "replace_in_file" | "run_python_script" | "patch"
        target      : chemin ou identifiant de la cible
        steps       : étapes ordonnées avec leur résultat individuel
        proof       : dict de preuves structurées (tailles, returncode, hash partiel...)
        elapsed_ms  : durée totale de la garde
        error       : message d'erreur si passed=False
    """
    passed:      bool
    action_type: str
    target:      str
    steps:       list[StepResult] = field(default_factory=list)
    proof:       dict             = field(default_factory=dict)
    elapsed_ms:  int              = 0
    error:       str              = ""

    def failed_step(self) -> Optional[StepResult]:
        """Première étape échouée."""
        for s in self.steps:
            if not s.passed:
                return s
        return None

    def summary(self) -> str:
        """Résumé lisible pour emit / notifications."""
        tag        = "[GUARD OK]" if self.passed else "[GUARD FAIL]"
        steps_str  = " → ".join(f"{s.icon()}{s.step}" for s in self.steps)
        name       = Path(self.target).name if self.target else self.target
        base       = f"{tag} {self.action_type} @ {name} | {steps_str}"
        if not self.passed and self.error:
            base  += f"\nErreur : {self.error[:140]}"
        return base

    def to_dict(self) -> dict:
        return {
            "passed":      self.passed,
            "action_type": self.action_type,
            "target":      self.target,
            "steps":       [{"step": s.step, "passed": s.passed,
                             "detail": s.detail, "elapsed_ms": s.elapsed_ms}
                            for s in self.steps],
            "proof":       self.proof,
            "elapsed_ms":  self.elapsed_ms,
            "error":       self.error,
        }


# ══════════════════════════════════════════════════════════════════════════════
# EXECUTION GUARD
# ══════════════════════════════════════════════════════════════════════════════

class ExecutionGuard:
    """
    Vérificateur post-action.

    Chaque méthode correspond à un type d'action et retourne un GuardResult
    avec preuve explicite ([GUARD OK] ou [GUARD FAIL] dans les logs structlog).
    """

    # ── Guard : écriture de fichier ────────────────────────────────────────────

    async def guard_write(
        self,
        path:             str,
        expected_content: str,
        action_type:      str = "write_file",
    ) -> GuardResult:
        """
        Vérifie qu'un fichier a bien été écrit.

        Étapes :
            1. exists   — fichier présent sur disque
            2. read     — lecture du contenu réel
            3. validate — contenu == attendu (taille + octets)
        """
        t0    = time.monotonic()
        steps: list[StepResult] = []
        proof: dict = {}
        p     = Path(path)

        # ── 1. EXISTS ──────────────────────────────────────────────────────────
        st, exists = _step_start()
        if p.exists() and p.is_file():
            sz = p.stat().st_size
            proof["file_size_bytes"] = sz
            steps.append(StepResult("exists", True,
                                    f"présent ({sz:,} bytes)", _ms(exists)))
        else:
            steps.append(StepResult("exists", False,
                                    f"ABSENT : {path}", _ms(exists)))
            return self._emit(GuardResult(
                False, action_type, path, steps, proof,
                _ms(t0), f"Fichier absent après écriture : {path}",
            ))

        # ── 2. READ ────────────────────────────────────────────────────────────
        _, rd = _step_start()
        try:
            actual = p.read_text("utf-8", errors="replace")
            proof["chars_read"] = len(actual)
            steps.append(StepResult("read", True,
                                    f"{len(actual):,} chars lus", _ms(rd)))
        except Exception as e:
            steps.append(StepResult("read", False, str(e)[:100], _ms(rd)))
            return self._emit(GuardResult(
                False, action_type, path, steps, proof,
                _ms(t0), f"Lecture impossible : {e}",
            ))

        # ── 3. VALIDATE ────────────────────────────────────────────────────────
        _, vd = _step_start()
        if actual == expected_content:
            proof["content_match"] = True
            steps.append(StepResult("validate", True,
                                    "contenu identique", _ms(vd)))
        else:
            # Localiser la divergence
            pos = next(
                (i for i, (a, b) in enumerate(zip(actual, expected_content)) if a != b),
                min(len(actual), len(expected_content)),
            )
            snippet = repr(actual[max(0, pos - 15): pos + 25])
            proof.update({"content_match": False, "diverge_at": pos})
            steps.append(StepResult("validate", False,
                                    f"diverge à pos {pos}: {snippet:.60}", _ms(vd)))
            return self._emit(GuardResult(
                False, action_type, path, steps, proof,
                _ms(t0), f"Contenu diverge à pos {pos}",
            ))

        return self._emit(GuardResult(True, action_type, path, steps, proof, _ms(t0)))

    # ── Guard : remplacement dans fichier ──────────────────────────────────────

    async def guard_replace(
        self,
        path:        str,
        old_str:     str,
        new_str:     str,
        action_type: str = "replace_in_file",
    ) -> GuardResult:
        """
        Vérifie qu'un remplacement in-place a réussi.

        Étapes :
            1. exists   — fichier présent
            2. read     — lecture contenu
            3. validate — new_str présent ET old_str absent (si différents)
            4. syntax   — si .py : ast.parse() valide
        """
        t0    = time.monotonic()
        steps: list[StepResult] = []
        proof: dict = {}
        p     = Path(path)

        # ── 1. EXISTS ─────────────────────────────────────────────────────────
        _, t1 = _step_start()
        if p.exists() and p.is_file():
            steps.append(StepResult("exists", True,
                                    f"{p.stat().st_size:,} bytes", _ms(t1)))
        else:
            steps.append(StepResult("exists", False, f"ABSENT : {path}", _ms(t1)))
            return self._emit(GuardResult(
                False, action_type, path, steps, proof, _ms(t0),
                f"Fichier absent : {path}",
            ))

        # ── 2. READ ───────────────────────────────────────────────────────────
        _, t2 = _step_start()
        try:
            content = p.read_text("utf-8", errors="replace")
            proof["chars_read"] = len(content)
            steps.append(StepResult("read", True, f"{len(content):,} chars", _ms(t2)))
        except Exception as e:
            steps.append(StepResult("read", False, str(e)[:80], _ms(t2)))
            return self._emit(GuardResult(
                False, action_type, path, steps, proof, _ms(t0), str(e),
            ))

        # ── 3. VALIDATE ───────────────────────────────────────────────────────
        _, t3 = _step_start()
        new_present = new_str in content
        old_absent  = (old_str == new_str) or (old_str not in content)

        if new_present and old_absent:
            proof.update({"new_str_present": True, "old_str_removed": True})
            steps.append(StepResult("validate", True,
                                    "new_str ✓  old_str supprimé ✓", _ms(t3)))
        elif not new_present:
            proof["new_str_present"] = False
            preview = repr(content[:80])
            steps.append(StepResult("validate", False,
                                    f"new_str ABSENT (début: {preview:.50})", _ms(t3)))
            return self._emit(GuardResult(
                False, action_type, path, steps, proof, _ms(t0),
                "new_str absent après remplacement",
            ))
        else:  # old_str encore présent
            proof["old_str_removed"] = False
            steps.append(StepResult("validate", False,
                                    "old_str ENCORE PRÉSENT (remplacement partiel?)", _ms(t3)))
            return self._emit(GuardResult(
                False, action_type, path, steps, proof, _ms(t0),
                "old_str toujours présent après remplacement",
            ))

        # ── 4. SYNTAX (fichiers Python uniquement) ────────────────────────────
        if path.endswith(".py"):
            _, t4 = _step_start()
            ok, err = _py_syntax(content, path)
            proof["syntax_ok"] = ok
            if ok:
                steps.append(StepResult("syntax", True, "ast.parse OK", _ms(t4)))
            else:
                proof["syntax_err"] = err[:200]
                steps.append(StepResult("syntax", False, err[:80], _ms(t4)))
                return self._emit(GuardResult(
                    False, action_type, path, steps, proof, _ms(t0),
                    f"Syntaxe Python invalide après remplacement : {err[:100]}",
                ))

        return self._emit(GuardResult(True, action_type, path, steps, proof, _ms(t0)))

    # ── Guard : exécution de script Python ────────────────────────────────────

    async def guard_script(
        self,
        script_path:         str,
        args:                list[str] | None = None,
        expected_returncode: int = 0,
        action_type:         str = "run_python_script",
    ) -> GuardResult:
        """
        Vérifie l'exécution réelle d'un script Python.

        Étapes :
            1. exists   — script présent
            2. syntax   — ast.parse avant exécution
            3. execute  — exécution réelle (timeout SCRIPT_TIMEOUT_S)
            4. validate — returncode == expected_returncode
        """
        t0    = time.monotonic()
        steps: list[StepResult] = []
        proof: dict = {}
        p     = Path(script_path)
        rc    = -1
        out   = ""

        # ── 1. EXISTS ─────────────────────────────────────────────────────────
        _, t1 = _step_start()
        if p.exists() and p.is_file():
            steps.append(StepResult("exists", True,
                                    f"{p.stat().st_size:,} bytes", _ms(t1)))
        else:
            steps.append(StepResult("exists", False,
                                    f"ABSENT : {script_path}", _ms(t1)))
            return self._emit(GuardResult(
                False, action_type, script_path, steps, proof, _ms(t0),
                f"Script absent : {script_path}",
            ))

        # ── 2. SYNTAX ─────────────────────────────────────────────────────────
        _, t2 = _step_start()
        try:
            source    = p.read_text("utf-8", errors="replace")
            ok, err   = _py_syntax(source, script_path)
            proof["syntax_ok"] = ok
            if ok:
                steps.append(StepResult("syntax", True, "ast.parse OK", _ms(t2)))
            else:
                steps.append(StepResult("syntax", False, err[:80], _ms(t2)))
                return self._emit(GuardResult(
                    False, action_type, script_path, steps, proof, _ms(t0),
                    f"Syntaxe invalide avant exécution : {err}",
                ))
        except Exception as e:
            steps.append(StepResult("syntax", False, str(e)[:80], _ms(t2)))

        # ── 3. EXECUTE ────────────────────────────────────────────────────────
        _, t3 = _step_start()
        try:
            cmd  = ["python3", script_path] + (args or [])
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(p.parent),
                ),
                timeout=SCRIPT_TIMEOUT_S,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=SCRIPT_TIMEOUT_S
            )
            out = stdout.decode("utf-8", errors="replace")[:2000]
            rc  = proc.returncode
            proof.update({
                "returncode":     rc,
                "output_len":     len(out),
                "output_preview": out[:200],
            })
            steps.append(StepResult("execute", True,
                                    f"rc={rc}, {len(out)} chars output", _ms(t3)))
        except asyncio.TimeoutError:
            steps.append(StepResult("execute", False,
                                    f"timeout {SCRIPT_TIMEOUT_S}s", _ms(t3)))
            return self._emit(GuardResult(
                False, action_type, script_path, steps, proof, _ms(t0),
                f"Timeout {SCRIPT_TIMEOUT_S}s lors de l'exécution",
            ))
        except Exception as e:
            steps.append(StepResult("execute", False, str(e)[:80], _ms(t3)))
            return self._emit(GuardResult(
                False, action_type, script_path, steps, proof, _ms(t0), str(e),
            ))

        # ── 4. VALIDATE returncode ────────────────────────────────────────────
        _, t4 = _step_start()
        if rc == expected_returncode:
            steps.append(StepResult("validate", True,
                                    f"rc={rc} == attendu({expected_returncode})", _ms(t4)))
        else:
            steps.append(StepResult("validate", False,
                                    f"rc={rc} ≠ attendu({expected_returncode})", _ms(t4)))
            return self._emit(GuardResult(
                False, action_type, script_path, steps, proof, _ms(t0),
                f"returncode={rc} ≠ {expected_returncode}. Output: {out[:150]}",
            ))

        return self._emit(GuardResult(True, action_type, script_path, steps, proof, _ms(t0)))

    # ── Guard : patch self_improve ─────────────────────────────────────────────

    async def guard_patch(
        self,
        file_path:  str,
        old_str:    str,
        new_str:    str,
        finding_id: str = "",
    ) -> GuardResult:
        """
        Garde spécialisée pour les patches auto-amélioration.
        Appelée APRÈS application du patch (par pipeline.apply_patch).

        NE réapplique PAS le patch — vérifie uniquement l'état du fichier.

        Étapes :
            1. exists  — fichier cible existe
            2. new_str — new_str effectivement présent dans le fichier
            3. old_str — old_str absent (si différent de new_str)
            4. syntax  — fichier .py reste syntaxiquement valide
        """
        t0    = time.monotonic()
        steps: list[StepResult] = []
        proof = {"finding_id": finding_id}
        p     = Path(file_path)

        # ── 1. EXISTS ─────────────────────────────────────────────────────────
        _, t1 = _step_start()
        if p.exists() and p.is_file():
            proof["file_size_bytes"] = p.stat().st_size
            steps.append(StepResult("exists", True,
                                    f"{p.stat().st_size:,} bytes", _ms(t1)))
        else:
            steps.append(StepResult("exists", False,
                                    f"ABSENT : {file_path}", _ms(t1)))
            return self._emit(GuardResult(
                False, "patch", file_path, steps, proof, _ms(t0),
                f"Fichier cible absent : {file_path}",
            ))

        # ── Lecture du contenu courant ─────────────────────────────────────────
        try:
            content = p.read_text("utf-8", errors="replace")
        except Exception as e:
            return self._emit(GuardResult(
                False, "patch", file_path, steps, proof, _ms(t0),
                f"Lecture impossible : {e}",
            ))

        # ── 2. NEW_STR présent ────────────────────────────────────────────────
        _, t2 = _step_start()
        if new_str in content:
            proof["new_str_present"] = True
            steps.append(StepResult("new_str", True,
                                    f"new_str trouvé ({len(new_str)} chars)", _ms(t2)))
        else:
            proof["new_str_present"] = False
            steps.append(StepResult("new_str", False,
                                    "new_str ABSENT du fichier après patch", _ms(t2)))
            return self._emit(GuardResult(
                False, "patch", file_path, steps, proof, _ms(t0),
                f"new_str absent après application du patch ({finding_id})",
            ))

        # ── 3. OLD_STR absent ─────────────────────────────────────────────────
        _, t3 = _step_start()
        old_still_present = (old_str != new_str) and (old_str in content)
        if old_still_present:
            proof["old_str_removed"] = False
            steps.append(StepResult("old_str", False,
                                    "old_str ENCORE PRÉSENT (patch partiel?)", _ms(t3)))
            return self._emit(GuardResult(
                False, "patch", file_path, steps, proof, _ms(t0),
                f"old_str toujours présent après patch ({finding_id})",
            ))
        else:
            proof["old_str_removed"] = True
            steps.append(StepResult("old_str", True,
                                    "old_str absent (remplacé)", _ms(t3)))

        # ── 4. SYNTAX (Python uniquement) ─────────────────────────────────────
        if file_path.endswith(".py"):
            _, t4 = _step_start()
            ok, err = _py_syntax(content, file_path)
            proof["syntax_ok"] = ok
            if ok:
                steps.append(StepResult("syntax", True, "ast.parse OK", _ms(t4)))
            else:
                proof["syntax_err"] = err[:200]
                steps.append(StepResult("syntax", False, err[:80], _ms(t4)))
                return self._emit(GuardResult(
                    False, "patch", file_path, steps, proof, _ms(t0),
                    f"Syntaxe Python invalide après patch : {err[:100]}",
                ))

        return self._emit(GuardResult(True, "patch", file_path, steps, proof, _ms(t0)))

    # ── Émission log structuré ────────────────────────────────────────────────

    def _emit(self, result: GuardResult) -> GuardResult:
        """Log [GUARD OK] ou [GUARD FAIL] avec preuve structurée."""
        tag  = "[GUARD OK]" if result.passed else "[GUARD FAIL]"
        name = Path(result.target).name if result.target else result.target

        if result.passed:
            log.info(
                tag,
                action=result.action_type,
                target=name[:80],
                steps=len(result.steps),
                elapsed_ms=result.elapsed_ms,
                proof=result.proof,
            )
        else:
            failed = result.failed_step()
            log.warning(
                tag,
                action=result.action_type,
                target=name[:80],
                failed_step=failed.step if failed else "?",
                failed_detail=(failed.detail[:80] if failed else ""),
                err=result.error[:140],
                elapsed_ms=result.elapsed_ms,
                proof=result.proof,
            )
        return result


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS INTERNES
# ══════════════════════════════════════════════════════════════════════════════

def _step_start() -> tuple[None, float]:
    """Retourne (None, monotonic_start) pour mesure de chaque étape."""
    return None, time.monotonic()


def _ms(start: float) -> int:
    """Millisecondes depuis start."""
    return int((time.monotonic() - start) * 1000)


def _py_syntax(source: str, filename: str = "<unknown>") -> tuple[bool, str]:
    """
    Tente ast.parse() sur le source Python.
    Retourne (True, "") si valide, (False, message) sinon.
    """
    try:
        ast.parse(source, filename=filename)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError L{e.lineno}: {e.msg}"
    except Exception as e:
        return False, str(e)[:200]


# ── Singleton global (instanciation paresseuse) ────────────────────────────────
_GUARD: Optional[ExecutionGuard] = None


def get_guard() -> ExecutionGuard:
    """Retourne l'instance singleton de l'ExecutionGuard (thread-safe en asyncio)."""
    global _GUARD
    if _GUARD is None:
        _GUARD = ExecutionGuard()
    return _GUARD
