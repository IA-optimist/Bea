# Affect baseline audit 02: Delay vs protocol shape

## Scope
Attack 2 asks whether the delay signature is specific to one step protocol, or whether it survives multiple bounded input profiles.

## Method
Compared `momentum = 0.8` vs `0.95` on five bounded profiles:
- `pos_step`
- `neg_step`
- `mid_step`
- `alt_sign`
- `rand_seq`

The delay metric is the index of the largest absolute state value in the trace.

## Raw numbers

| profile | delay @ 0.8 | delay @ 0.95 | monotone? |
|---|---:|---:|---|
| pos_step | 3 | 8 | yes |
| neg_step | 3 | 8 | yes |
| mid_step | 3 | 8 | yes |
| alt_sign | 2 | 2 | tie |
| rand_seq | 1 | 4 | yes |

Trace excerpts:
- `pos_step` @ 0.8: `[0.09999999999999998, 0.16999999999999998, 0.209, 0.2193, 0.20561000000000001, 0.17409700000000003, 0.13147690000000004, 0.08423313000000004, 0.03801480100000005]`
- `pos_step` @ 0.95: `[0.025000000000000022, 0.04812500000000004, 0.06889062500000007, 0.08689570312500008, 0.10182813476562509, 0.11346824145507822, 0.12168963677368173, 0.12645772140701303, 0.12782595877350242]`
- `alt_sign` @ 0.8: `[0.09999999999999998, 0.06999999999999998, 0.13899999999999996, 0.08029999999999997, 0.02530999999999998, -0.021213000000000017, -0.056310100000000016, -0.07875677000000002, -0.08883842900000002]`
- `alt_sign` @ 0.95: `[0.025000000000000022, 0.023125000000000024, 0.045765625000000046, 0.04113007812500004, 0.03569805664062503, 0.02964518481445315, 0.023153826959228532, 0.016408191322784434, 0.00958963268509293]`

## Attack result
- The delay effect is monotone for 4 of the 5 tested profiles and tied for the alternating-sign profile.
- The signature is therefore not confined to one hand-picked step.
- The tie in `alt_sign` is a warning that the metric is sensitive to sequence shape, but it does not overturn the monotone trend across the other profiles.

## Verdict
- **DATA_SUPPORTED**: the delay signature survives multiple bounded input families.
- **METHOD_SUPPORTED**: the observed monotonicity is not a single-protocol artifact.
- **PLAUSIBLE**: sequence shape still matters for the magnitude.

Conclusion: **protocol-robust within the tested family, with a shape-sensitive edge case**.
