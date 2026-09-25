# Chain Audit 04 - Noisy Jitter

## Scope
Chaîne auditée sous viabilité fortement bruitée et alternée.

## Result
`input_variance=0.020731`
`output_variance=0.004040`
`ratio=0.194864`

## Assessment
| Claim | Status | Evidence |
|---|---|---|
| L'EMA + momentum absorbent le jitter | DATA_SUPPORTED | variance sortie / entrée = 0.194864 |
| L'humeur oscille moins que la viabilité injectée | DATA_SUPPORTED | variance affect bien inférieure à variance entrée |
| La chaîne ne transmet pas le bruit brut tel quel | METHOD_SUPPORTED | ratio < 0.5, donc forte atténuation |

## Verdict
`ROBUST`

