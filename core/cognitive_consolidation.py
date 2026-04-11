"""
Bio-inspired Cognitive Consolidation Module
Implements hippocampal replay / sleep consolidation for AGI learning.

Mimics the brain's nighttime memory consolidation process:
- Reads recent mission traces (last 24h)
- Extracts patterns by domain: success rates, common failures, lessons
- Computes dopaminergic signals (reward prediction error via delta_score)
- Saves compressed summary to consolidation_log.jsonl

Designed to run nightly at 3am UTC (cron: 0 3 * * *)
"""
from __future__ import annotations

import json
import structlog
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any

log = structlog.get_logger(__name__)

WORKSPACE = Path(__file__).parent.parent / "workspace"
TRAINING_DATA_DIR = WORKSPACE / "training_data"
CONSOLIDATION_LOG = WORKSPACE / "consolidation_log.jsonl"
EXECUTION_TRACE = WORKSPACE / "execution_trace.jsonl"
FAILURE_LOG = WORKSPACE / "failure_log.jsonl"


def _read_jsonl(path: Path, max_age_hours: int = 24) -> List[Dict[str, Any]]:
    """Read JSONL file, filtering by timestamp if available."""
    if not path.exists():
        return []
    
    cutoff_time = datetime.now().timestamp() - (max_age_hours * 3600)
    entries = []
    
    try:
        with open(path, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        # Check timestamp field (could be 'ts', 'timestamp', or 'time')
                        ts = entry.get('ts') or entry.get('timestamp') or entry.get('time', 0)
                        if ts > cutoff_time:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        log.warning("cognitive_consolidation.read_error", path=str(path), error=str(e))
    
    return entries


def _extract_domain_patterns(traces: List[Dict]) -> Dict[str, Any]:
    """
    Extract patterns by domain/agent:
    - Count of missions per domain
    - Average score (if present)
    - Top lessons learned
    - Common failure modes
    - Dopamine signal statistics (delta_score)
    """
    domain_stats = defaultdict(lambda: {
        'count': 0,
        'success': 0,
        'failed': 0,
        'scores': [],
        'delta_scores': [],  # Dopamine signal (reward prediction error)
        'lessons': [],
        'errors': []
    })
    
    for trace in traces:
        agent = trace.get('agent', 'unknown')
        domain = agent.split('-')[0] if '-' in agent else agent
        
        stats = domain_stats[domain]
        stats['count'] += 1
        
        # Track success/failure
        status = trace.get('status', '').upper()
        if status == 'SUCCESS':
            stats['success'] += 1
        elif status in ('FAILED', 'ERROR'):
            stats['failed'] += 1
        
        # Collect scores
        if 'score' in trace:
            stats['scores'].append(trace['score'])
        
        # Dopamine signal: reward prediction error (delta from expected)
        if 'delta_score' in trace:
            stats['delta_scores'].append(trace['delta_score'])
        elif 'score' in trace and 'expected_score' in trace:
            delta = trace['score'] - trace['expected_score']
            stats['delta_scores'].append(delta)
        
        # Extract lessons
        if 'lesson' in trace or 'feedback' in trace:
            lesson = trace.get('lesson') or trace.get('feedback', '')
            if lesson and len(lesson) > 10:
                stats['lessons'].append(lesson[:200])
        
        # Track errors
        if trace.get('error'):
            error_msg = str(trace['error'])[:100]
            stats['errors'].append(error_msg)
    
    # Compute aggregates
    consolidated = {}
    for domain, stats in domain_stats.items():
        avg_score = sum(stats['scores']) / len(stats['scores']) if stats['scores'] else 0.0
        avg_delta = sum(stats['delta_scores']) / len(stats['delta_scores']) if stats['delta_scores'] else 0.0
        success_rate = stats['success'] / stats['count'] if stats['count'] > 0 else 0.0
        
        # Top 3 most common errors
        error_counts = defaultdict(int)
        for err in stats['errors']:
            error_counts[err] += 1
        top_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        
        consolidated[domain] = {
            'total_missions': stats['count'],
            'success_count': stats['success'],
            'failure_count': stats['failed'],
            'success_rate': round(success_rate, 3),
            'avg_score': round(avg_score, 3),
            'avg_dopamine_signal': round(avg_delta, 3),  # Reward prediction error
            'dopamine_variance': round(_variance(stats['delta_scores']), 3),
            'top_lessons': stats['lessons'][:5],  # Top 5 lessons
            'top_errors': [{'error': err, 'count': cnt} for err, cnt in top_errors]
        }
    
    return consolidated


def _variance(values: List[float]) -> float:
    """Compute variance of a list of numbers."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((x - mean) ** 2 for x in values) / len(values)


async def run_nightly_consolidation() -> Dict[str, Any]:
    """
    Main consolidation routine - mimics hippocampal replay during sleep.
    
    Process:
    1. Load recent mission traces (last 24h)
    2. Extract patterns by domain/agent
    3. Compute dopamine signals (reward prediction error)
    4. Save consolidated summary
    
    Returns summary dict with stats.
    """
    log.info("cognitive_consolidation.starting", mode="hippocampal_replay")
    
    # Ensure directories exist
    TRAINING_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Read recent traces from multiple sources
    execution_traces = _read_jsonl(EXECUTION_TRACE, max_age_hours=24)
    failure_traces = _read_jsonl(FAILURE_LOG, max_age_hours=24)
    
    # Also scan training_data/*.jsonl
    training_files = []
    if TRAINING_DATA_DIR.exists():
        for jsonl_file in TRAINING_DATA_DIR.glob("*.jsonl"):
            training_files.extend(_read_jsonl(jsonl_file, max_age_hours=24))
    
    all_traces = execution_traces + failure_traces + training_files
    
    if not all_traces:
        log.warning("cognitive_consolidation.no_data", message="No recent traces found")
        return {
            'status': 'empty',
            'total_traces': 0,
            'domains_processed': 0,
            'timestamp': datetime.now().isoformat()
        }
    
    # Extract domain patterns
    patterns = _extract_domain_patterns(all_traces)
    
    # Create consolidation summary
    summary = {
        'timestamp': datetime.now().isoformat(),
        'consolidation_window_hours': 24,
        'total_traces_processed': len(all_traces),
        'domains_analyzed': len(patterns),
        'domain_patterns': patterns,
        'meta': {
            'total_successes': sum(p['success_count'] for p in patterns.values()),
            'total_failures': sum(p['failure_count'] for p in patterns.values()),
            'avg_global_dopamine': round(
                sum(p['avg_dopamine_signal'] * p['total_missions'] for p in patterns.values()) /
                sum(p['total_missions'] for p in patterns.values()),
                3
            ) if patterns else 0.0
        }
    }
    
    # Append to consolidation log
    try:
        with open(CONSOLIDATION_LOG, 'a') as f:
            f.write(json.dumps(summary) + '\n')
        log.info("cognitive_consolidation.complete",
                 domains=len(patterns),
                 traces=len(all_traces),
                 avg_dopamine=summary['meta']['avg_global_dopamine'])
    except Exception as e:
        log.error("cognitive_consolidation.save_failed", error=str(e))
        raise
    
    return {
        'status': 'success',
        'total_traces': len(all_traces),
        'domains_processed': len(patterns),
        'timestamp': summary['timestamp'],
        'summary': summary
    }
