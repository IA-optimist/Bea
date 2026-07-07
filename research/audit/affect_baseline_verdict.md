# Affect baseline verdict

## Executive summary
The baseline passes the four hostile attacks on the current evidence set.

## Evidence summary

| Attack | Raw result | Status |
|---|---|---|
| Hysteresis vs rate | area stays > 0 for rates 0.1, 0.3, 0.5, 0.8, 1.0; values `0.815972973268253`, `2.8262314617434674`, `5.213265116999999`, `9.193978815826622`, `11.537163263999998` | robust on tested grid |
| Delay vs protocol shape | delay monotone in 4/5 profiles; `pos_step 3->8`, `neg_step 3->8`, `mid_step 3->8`, `alt_sign 2->2`, `rand_seq 1->4` | robust with one shape-sensitive tie |
| Stability / bounds | state remained within `[-1, 1]` on all tested stress runs; no divergence observed; velocity reached `2.0` only in alternating-sign stress | stable on tested horizon |
| First-order placebo | first-order reproduces step response and hysteresis, but delay stays at `2` across rates while second-order reaches `5` and `10` | coarse placebo passes, phase-lag remains second-order-specific |

## Verdict
**BASELINE_ROBUST**

## Classification
- **DATA_SUPPORTED**: the measured values above.
- **METHOD_SUPPORTED**: the hostile attacks did not invalidate the baseline on the tested probes.
- **PLAUSIBLE**: the second-order term adds a tunable phase-lag axis, even though coarse step/hysteresis signatures are not unique to it.

## Claims that remain bounded
- No claim of emotion.
- No claim of feeling.
- No claim of affective realism.
- Only functional temporal regulation is supported here.
