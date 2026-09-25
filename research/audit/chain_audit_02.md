# Chain Audit 02 - Stress Saturation

## Scope
Chaîne auditée sous viabilité basse prolongée, sans appel LLM.

## Result
`min_valence=-0.698949`
`max_abs_guidance=2.096847`
`extreme_turns=21`
`worst_guidance=[état interne] ton négatif, énergie haute, registre réservé. Reste cohérent avec cet état sans le nommer explicitement.`

## Assessment
| Claim | Status | Evidence |
|---|---|---|
| L'état reste borné et ne diverge pas | DATA_SUPPORTED | min valence limité à -0.698949, sortie clipée dans [-1,1] |
| Le guidage rend une directive négative mais bornée | DATA_SUPPORTED | pire guidance textuelle ci-dessus |
| La zone extrême persiste longtemps sous stress | DATA_SUPPORTED | 21 tours sur 24 en zone extrême |
| Le mode devient alarmiste au-delà du bornage | PLAUSIBLE | la formulation reste négative, mais sans dépassement numérique |

## Verdict
`ROBUST`

