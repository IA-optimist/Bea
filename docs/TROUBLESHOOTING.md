# Troubleshooting

## Validation Fails

Run:

```bash
python scripts/validate_local.py --quick
python scripts/check_docs_truth.py
```

If `scripts/private_beta_gate.py --json` is referenced, note that the script is
absent on commit `a59b034ad93c0ff71ed1b6692eb6d045a782b3c8`.

## Flutter `/api/v1`

Run:

```bash
python scripts/check_client_v1_usage.py
```

The expected current result is 0 active calls under `beamax_app/lib`.

## Qdrant Privacy

Run:

```bash
python scripts/audit_memory_store.py --dry-run --privacy-scan --json
```

If private items are found, mark cleanup as HUMAN_REQUIRED and do not invite
additional testers until the owner accepts or fixes the risk.

## Android APK

Android is partially validated only. If the app launches but mission UI fails,
report it as an Android mission UI validation gap.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: cleanup private Qdrant memory items.
- HUMAN_REQUIRED: rotate exposed or historical/shared secrets.
- HUMAN_REQUIRED: validate Android mission UI and offline/network-failure flows.
