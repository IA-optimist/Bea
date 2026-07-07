# Affect baseline audit 04: First-order placebo

## Scope
Attack 4 asks whether a first-order state update (`momentum = 0`) already reproduces the coarse signatures, which would make the second-order layer potentially over-specified.

## Method
Compared the existing second-order settings against `momentum = 0.0` on the same characterization probes. Also checked whether the first-order model has any momentum-like tunability of delay.

## Raw numbers

### Step response

| momentum | peak | trough | final |
|---|---:|---:|---:|
| 0.0 | 0.5 | 0.0 | 0.0009765625 |
| 0.8 | 0.2193 | -0.0027613422999999554 | -0.0027613422999999554 |
| 0.95 | 0.12782595877350242 | 0.0 | 0.12593013530232977 |

### Hysteresis area

| momentum | area |
|---|---:|
| 0.0 | 8.771484375 |
| 0.8 | 5.213265116999999 |
| 0.95 | 1.0297046659222309 |

### Inertia signature

| momentum | delay | recovery |
|---|---:|---:|
| 0.0 | 2 | 4 |
| 0.8 | 5 | 5 |
| 0.95 | 10 | 2 |

### Extra placebo probe: first-order delay vs rate

`momentum = 0.0`

| rate | peak | final | delay |
|---|---:|---:|---:|
| 0.1 | 0.1 | 0.038742048900000006 | 2 |
| 0.3 | 0.3 | 0.0121060821 | 2 |
| 0.5 | 0.5 | 0.0009765625 | 2 |
| 0.8 | 0.8 | 4.095999999999988e-07 | 2 |
| 1.0 | 1.0 | 0.0 | 2 |

## Attack result
- The first-order placebo does reproduce the coarse step-response and hysteresis signatures.
- That means those two signatures alone do not force a second-order interpretation.
- However the first-order placebo does **not** reproduce the momentum-linked delay axis: delay stays at `2` across the tested rates, while the second-order system moves to `5` and `10` at higher momentum.
- So the second-order layer adds a measurable phase-lag axis that the first-order placebo does not supply.

## Verdict
- **DATA_SUPPORTED**: first-order is enough for the coarse signatures.
- **METHOD_SUPPORTED**: first-order is not enough for the momentum-linked delay signature.
- **PLAUSIBLE**: the second-order layer is still justified by tunable lag, not by step/hysteresis alone.

Conclusion: **not over-specified by the coarse signatures, but the coarse signatures are not unique to second order**.
