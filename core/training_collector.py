"""
core/training_collector.py — Raw LLM-call training-data collector.

Captures every LLM round-trip (prompt + response + tokens + latency)
for later fine-tuning. Distinct from `core.training_data_collector`
which collects mission-level outcomes ; this module operates one
level lower, at the `safe_invoke()` boundary.

Storage layout :
    data/training/raw/YYYY-MM-DD.jsonl   — one record per LLM call
    data/training/validated/             — manually-curated copies
    data/training/stats.json             — aggregate counters

Record schema (per spec) :
    {
      "id":            uuid4,
      "timestamp":     ISO8601 UTC,
      "domain":        code|cyber|agent|patch|general,
      "instruction":   merged system + user prompt,
      "context":       optional extra context,
      "response":      model output,
      "model":         provider/model name,
      "quality_score": float | null (auto_score result or manual review),
      "tokens_in":     int,
      "tokens_out":    int,
      "latency_ms":    int,
      "source":        agent / module that issued the call,
      "validated":     bool (always false on raw write)
    }

Concurrency model :
    Public API is fire-and-forget : `record_llm_interaction(...)` puts
    a record on a bounded `queue.Queue` and returns immediately. A
    daemon thread drains the queue, batches by day, and writes
    atomically (tmp → rename). On queue overflow the record is dropped
    and a counter is incremented — never blocks the caller.

Activation :
    Off by default. Set `JARVIS_TRAINING_COLLECT=1` to enable.
    `JARVIS_TRAINING_DIR=<path>` overrides the storage root
    (default : repo-root/data/training).

CLI :
    python -m core.training_collector stats
    python -m core.training_collector validate <id>
    python -m core.training_collector export --format {alpaca,chatml,sharegpt} \
                                              [--out file.jsonl] [--validated-only]
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import structlog

from core.training_data_collector import classify_domain as _mission_classify_domain

log = structlog.get_logger(__name__)

# ── Domains required by spec ─────────────────────────────────
# Spec asks for : code | cyber | agent | patch | general.
# `core.training_data_collector.classify_domain` returns :
#   security|code|business|research|ops|general.
# We map the existing labels onto the spec's labels so we reuse the
# heuristic while honoring the requested vocabulary.
_DOMAIN_MAP = {
    "security": "cyber",
    "code":     "code",
    "ops":      "code",       # ops work is mostly code (CI, infra-as-code)
    "business": "general",
    "research": "general",
    "general":  "general",
}
_AGENT_HINT_RE = re.compile(r"\b(agent|tool|orchestrat|delegate|crew)\b", re.I)
_PATCH_HINT_RE = re.compile(r"\b(patch|diff|fix|refactor|self_improvement)\b", re.I)


def classify_domain(instruction: str, source: str = "") -> str:
    """Map an instruction to {code, cyber, agent, patch, general}.

    Reuses the existing keyword scoring, then refines with two
    instruction-level heuristics : agent / patch.
    """
    if _PATCH_HINT_RE.search(instruction or "") or "self_improvement" in (source or "").lower():
        return "patch"
    if _AGENT_HINT_RE.search(instruction or "") or "agent" in (source or "").lower():
        return "agent"
    base = _mission_classify_domain(instruction or "")
    return _DOMAIN_MAP.get(base, "general")


# ── Auto-score ───────────────────────────────────────────────
_JSON_LIKELY_RE = re.compile(r'^\s*[\{\[]')
_REFUSAL_PHRASES = (
    "i can't",
    "i cannot",
    "i am not able",
    "i'm not able",
    "as an ai",
    "désolé, je ne peux pas",
    "je ne peux pas",
    "i apologize",
)
_ERROR_MARKERS = ("traceback", "exception", "stack trace", "internal server error")


def auto_score(instruction: str, response: str, *, expect_json: Optional[bool] = None) -> float:
    """Return a heuristic 0-10 quality score.

    Considers : JSON validity (when expected), length coherence,
    refusal phrases, error markers, ratio response/instruction. The
    function is a tiny rule engine — not an LLM judge — so it stays
    deterministic and free.

    Args:
        instruction : combined system+user prompt
        response    : model output
        expect_json : if True, score 0.0 unless response parses as JSON.
                      If False, do not penalize JSON.
                      If None, auto-detect : "json" word in instruction.
    """
    if not response or not response.strip():
        return 0.0
    if expect_json is None:
        expect_json = "json" in (instruction or "").lower() or _JSON_LIKELY_RE.match(response or "") is not None

    score = 5.0  # baseline
    resp = response.strip()
    low = resp.lower()

    # JSON validity — heavyweight signal
    if expect_json:
        try:
            json.loads(resp)
            score += 2.0
        except Exception:
            score -= 3.0

    # Refusal / disclaimer — strong negative
    if any(phrase in low for phrase in _REFUSAL_PHRASES):
        score -= 2.5

    # Error trace leaked into the response
    if any(marker in low for marker in _ERROR_MARKERS):
        score -= 2.0

    # Length coherence : too short is suspect, very long is fine
    if len(resp) < 30:
        score -= 1.5
    elif len(resp) > 200:
        score += 1.0

    # Response should be at least as long as a one-line refusal
    if instruction and len(resp) < min(40, len(instruction) // 4):
        score -= 1.0

    return max(0.0, min(10.0, round(score, 2)))


# ── Storage paths ────────────────────────────────────────────
def _root() -> Path:
    return Path(os.getenv("JARVIS_TRAINING_DIR", "data/training"))


def _raw_dir() -> Path:
    return _root() / "raw"


def _validated_dir() -> Path:
    return _root() / "validated"


def _stats_path() -> Path:
    return _root() / "stats.json"


def _today_file() -> Path:
    return _raw_dir() / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"


# ── Writer thread ────────────────────────────────────────────
_QUEUE_MAX = 1024
_collector_lock = threading.RLock()
_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=_QUEUE_MAX)
_worker: Optional[threading.Thread] = None
_stop_event = threading.Event()
_stats: Dict[str, Any] = {"written": 0, "dropped_full": 0, "errors": 0}


def _is_enabled() -> bool:
    return os.getenv("JARVIS_TRAINING_COLLECT", "0").lower() in ("1", "true", "yes")


def _ensure_worker() -> None:
    """Start the writer thread on first use. Idempotent + thread-safe."""
    global _worker
    with _collector_lock:
        if _worker is not None and _worker.is_alive():
            return
        _stop_event.clear()
        _worker = threading.Thread(
            target=_writer_loop, daemon=True, name="training-collector"
        )
        _worker.start()


def _atomic_append(path: Path, line: str) -> None:
    """Append a line atomically : write tmp → rename onto target.

    For JSONL we tolerate a slight race : the rename overwrites the
    target. The "atomic" guarantee is that no partial line is ever
    visible. Implementation : read existing → append → write tmp →
    rename. Costs a re-read per write but keeps a strict single-line
    append semantics suitable for low-volume training capture.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    existing = path.read_bytes() if path.exists() else b""
    payload = existing + line.encode("utf-8")
    if not payload.endswith(b"\n"):
        payload += b"\n"
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def _writer_loop() -> None:
    while not _stop_event.is_set():
        try:
            record = _queue.get(timeout=0.5)
        except queue.Empty:
            log.debug("swallowed_exception", exc_info=True)
            continue
        try:
            _atomic_append(_today_file(), json.dumps(record, ensure_ascii=False))
            with _collector_lock:
                _stats["written"] += 1
        except Exception as exc:
            with _collector_lock:
                _stats["errors"] += 1
            log.warning("training_collector.write_failed", err=str(exc)[:160])
        finally:
            _queue.task_done()


# ── Public API ───────────────────────────────────────────────
def record_llm_interaction(
    *,
    instruction: str,
    response: str,
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    source: str = "",
    context: str = "",
    quality_score: Optional[float] = None,
    domain: Optional[str] = None,
) -> Optional[str]:
    """Queue a single LLM call for storage. Fire-and-forget.

    Returns the record id when accepted, None when collection is
    disabled or the queue is full. Never raises.
    """
    if not _is_enabled():
        return None
    try:
        rid = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        record = {
            "id":            rid,
            "timestamp":     ts,
            "domain":        domain or classify_domain(instruction, source=source),
            "instruction":   instruction,
            "context":       context,
            "response":      response,
            "model":         model,
            "quality_score": quality_score if quality_score is not None
                              else auto_score(instruction, response),
            "tokens_in":     int(tokens_in),
            "tokens_out":    int(tokens_out),
            "latency_ms":    int(latency_ms),
            "source":        source,
            "validated":     False,
        }
        _ensure_worker()
        try:
            _queue.put_nowait(record)
        except queue.Full:
            with _collector_lock:
                _stats["dropped_full"] += 1
            log.warning("training_collector.queue_full")
            return None
        return rid
    except Exception as exc:
        with _collector_lock:
            _stats["errors"] += 1
        log.warning("training_collector.enqueue_failed", err=str(exc)[:160])
        return None


def flush(timeout_s: float = 2.0) -> bool:
    """Block until the queue drains (test fixture)."""
    end = time.time() + timeout_s
    while time.time() < end:
        if _queue.empty():
            return True
        time.sleep(0.05)
    return False


def get_stats() -> Dict[str, Any]:
    """Snapshot of writer counters + on-disk stats."""
    with _collector_lock:
        snap = dict(_stats)
    snap["enabled"] = _is_enabled()
    snap["dir"] = str(_root())
    snap["raw_files"] = []
    if _raw_dir().exists():
        for f in sorted(_raw_dir().glob("*.jsonl")):
            try:
                lines = sum(1 for _ in f.open("r", encoding="utf-8"))
            except Exception:
                lines = 0
            snap["raw_files"].append({"file": f.name, "records": lines})
    snap["total_records"] = sum(f["records"] for f in snap["raw_files"])
    return snap


def iter_records(*, validated_only: bool = False) -> Iterable[Dict[str, Any]]:
    """Generator over every record on disk."""
    if validated_only:
        target_dir = _validated_dir()
    else:
        target_dir = _raw_dir()
    if not target_dir.exists():
        return
    for f in sorted(target_dir.glob("*.jsonl")):
        with f.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    log.debug("swallowed_exception", exc_info=True)
                    continue


def validate_record(record_id: str) -> bool:
    """Mark a record validated and copy to data/training/validated/."""
    found: Optional[Dict[str, Any]] = None
    src_file: Optional[Path] = None
    for f in sorted(_raw_dir().glob("*.jsonl")) if _raw_dir().exists() else []:
        with f.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    log.debug("swallowed_exception", exc_info=True)
                    continue
                if rec.get("id") == record_id:
                    found = rec
                    src_file = f
                    break
        if found is not None:
            break
    if not found or not src_file:
        return False
    found["validated"] = True
    out_path = _validated_dir() / src_file.name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_append(out_path, json.dumps(found, ensure_ascii=False))
    return True


# ── Export formats ───────────────────────────────────────────
def export_records(*, format: str, validated_only: bool = False) -> List[Dict[str, Any]]:
    """Convert records to a fine-tuning format.

    format = alpaca | chatml | sharegpt
    """
    fmt = format.lower()
    if fmt not in {"alpaca", "chatml", "sharegpt"}:
        raise ValueError(f"unknown format : {format!r}")
    out: List[Dict[str, Any]] = []
    for rec in iter_records(validated_only=validated_only):
        if fmt == "alpaca":
            out.append({
                "instruction": rec.get("instruction", ""),
                "input":       rec.get("context", ""),
                "output":      rec.get("response", ""),
            })
        elif fmt == "chatml":
            messages = []
            inst = rec.get("instruction", "")
            ctx = rec.get("context", "")
            if ctx:
                messages.append({"role": "system", "content": ctx})
            messages.append({"role": "user", "content": inst})
            messages.append({"role": "assistant", "content": rec.get("response", "")})
            out.append({"messages": messages})
        else:  # sharegpt
            conversations = []
            ctx = rec.get("context", "")
            if ctx:
                conversations.append({"from": "system", "value": ctx})
            conversations.append({"from": "human", "value": rec.get("instruction", "")})
            conversations.append({"from": "gpt", "value": rec.get("response", "")})
            out.append({"conversations": conversations})
    return out


# ── CLI ──────────────────────────────────────────────────────
def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser("python -m core.training_collector")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="Print collection stats")

    val = sub.add_parser("validate", help="Mark a record as validated")
    val.add_argument("record_id")

    exp = sub.add_parser("export", help="Export records to a fine-tuning format")
    exp.add_argument("--format", choices=["alpaca", "chatml", "sharegpt"], required=True)
    exp.add_argument("--out", default="-", help="Output file path or '-' for stdout")
    exp.add_argument("--validated-only", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "stats":
        print(json.dumps(get_stats(), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "validate":
        ok = validate_record(args.record_id)
        print("validated" if ok else "not_found")
        return 0 if ok else 1
    if args.cmd == "export":
        records = export_records(format=args.format, validated_only=args.validated_only)
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
        if args.out == "-":
            print(text)
        else:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text + "\n", encoding="utf-8")
            print(f"wrote {len(records)} records → {args.out}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
