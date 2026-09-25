# Chain Audit 01 - Session Drift

## Scope
Chaîne auditée: `ViabilityAdapter -> Homeostasis -> AffectState` sous viabilité réaliste bruitée sur 200 tours.

## Result
`first50_mean_abs=0.069662`
`last50_mean_abs=0.074741`
`slope=0.00000050`
`final=(-0.019, +0.019, -0.019)`
`drift_ratio=1.072900`

## Assessment
| Claim | Status | Evidence |
|---|---|---|
| Pas de dérive monotone visible | DATA_SUPPORTED | pente ~0,00000050 sur 200 tours |
| La moyenne glissante reste proche de la baseline | DATA_SUPPORTED | 0,069662 -> 0,074741 |
| La session longue n'accumule pas de biais net | METHOD_SUPPORTED | ratio 1,072900, bien sous un facteur de dérive significatif |

## Verdict
`ROBUST`

