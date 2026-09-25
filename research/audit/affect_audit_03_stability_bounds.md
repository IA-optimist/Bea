# Affect baseline audit 03: Stability and bounds

## Scope
Attack 3 asks whether the state remains bounded and numerically stable under repeated extreme inputs, or whether `_clip` hides an underlying instability.

## Method
Stress-tested `AffectState` with repeated extreme targets:
- sustained positive input
- alternating positive / negative input

Tested `momentum in {0.0, 1.0}` and `rate in {1.0, 1.8, 2.0}`.

## Raw numbers

### Sustained positive target

| momentum | rate | last state | last velocity | max |state| | max |velocity| |
|---|---:|---|---|---:|---:|
| 0.0 | 1.0 | (1.0, 1.0, 1.0) | (0.0, 0.0, 0.0) | 1.0 | 1.0 |
| 0.0 | 1.8 | (1.0, 1.0, 1.0) | (0.0, 0.0, 0.0) | 1.0 | 1.0 |
| 0.0 | 2.0 | (1.0, 1.0, 1.0) | (0.0, 0.0, 0.0) | 1.0 | 1.0 |
| 1.0 | 1.0 | (0.0, 0.0, 0.0) | (0.0, 0.0, 0.0) | 0.0 | 0.0 |
| 1.0 | 1.8 | (0.0, 0.0, 0.0) | (0.0, 0.0, 0.0) | 0.0 | 0.0 |
| 1.0 | 2.0 | (0.0, 0.0, 0.0) | (0.0, 0.0, 0.0) | 0.0 | 0.0 |

### Alternating positive / negative target

| momentum | rate | last state | last velocity | max |state| | max |velocity| |
|---|---:|---|---|---:|---:|
| 0.0 | 1.0 | (-1.0, -1.0, -1.0) | (-2.0, -2.0, -2.0) | 1.0 | 2.0 |
| 0.0 | 1.8 | (-1.0, -1.0, -1.0) | (-2.0, -2.0, -2.0) | 1.0 | 2.0 |
| 0.0 | 2.0 | (-1.0, -1.0, -1.0) | (-2.0, -2.0, -2.0) | 1.0 | 2.0 |
| 1.0 | 1.0 | (0.0, 0.0, 0.0) | (0.0, 0.0, 0.0) | 0.0 | 0.0 |
| 1.0 | 1.8 | (0.0, 0.0, 0.0) | (0.0, 0.0, 0.0) | 0.0 | 0.0 |
| 1.0 | 2.0 | (0.0, 0.0, 0.0) | (0.0, 0.0, 0.0) | 0.0 | 0.0 |

## Attack result
- The observable state stays within `[-1, 1]` in all tested runs.
- There is no observed divergence on the tested horizon.
- `_clip` is active and does bound state values; it does not obviously hide state divergence here.
- Velocity can reach `2.0` in the alternating-sign stress case, so the internal velocity is not itself clipped, but no unstable growth was observed.

## Verdict
- **DATA_SUPPORTED**: the tested trajectories remain bounded.
- **METHOD_SUPPORTED**: no numeric instability was observed in the tested stress cases.
- **PLAUSIBLE**: longer horizons could still matter, but they are not evidenced here.

Conclusion: **stable on the tested horizon; no divergent or unbounded behavior seen**.
