# Affect baseline audit 01: Hysteresis vs rate

## Scope
Attack 1 asks whether the hysteresis signature only exists at one specific `rate`, or whether it remains positive across a range of rates at fixed `momentum`.

## Method
Fixed `momentum = 0.8`. Swept `rate` over `{0.1, 0.3, 0.5, 0.8, 1.0}`. Used the existing forward/backward probe structure against `AffectState` as-is.

## Raw numbers

| rate | hysteresis area | forward end state | backward end state |
|---|---:|---|---|
| 0.1 | 0.815972973268253 | (0.06760303999999998, 0.06760303999999998, 0.06760303999999998) | (-0.0034919026063201398, -0.0034919026063201398, -0.0034919026063201398) |
| 0.3 | 2.8262314617434674 | (0.17829744, 0.17829744, 0.17829744) | (-0.10639953181014362, -0.10639953181014362, -0.10639953181014362) |
| 0.5 | 5.213265116999999 | (0.2583, 0.2583, 0.2583) | (-0.267528969, -0.267528969, -0.267528969) |
| 0.8 | 9.193978815826622 | (0.32584704000000003, 0.32584704000000003, 0.32584704000000003) | (-0.49284082156594783, -0.49284082156594783, -0.49284082156594783) |
| 1.0 | 11.537163263999998 | (0.33919999999999995, 0.33919999999999995, 0.33919999999999995) | (-0.582699008, -0.582699008, -0.582699008) |

## Attack result
- The area stays strictly positive for every tested rate.
- The area does not collapse to zero and does not invert sign in the tested range.
- The magnitude increases with `rate` in this probe.

## Verdict
- **DATA_SUPPORTED**: the measured signature is present across the tested rate sweep.
- **METHOD_SUPPORTED**: the signature is not an artifact of one exact rate value.
- **SPECULATIVE**: no claim is made beyond the tested range.

Conclusion: **not fragile on the tested rate grid**.
