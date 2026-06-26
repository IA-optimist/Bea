# Beta Tester Guide

This guide is for Bea Private Beta 0.1 testers only.
PUBLIC_BETA_READY: false.

## What You Can Test

- Local API setup.
- Basic mission submission.
- Policy/auth failures with toy data.
- Documentation accuracy.
- Android launch/connectivity only if the owner provides an APK and token.

## What You Must Not Test

- Real secrets or credentials.
- Real private, medical, financial, customer, or regulated data.
- Unsupervised self-improvement.
- Dangerous third-party actions.
- Multi-tenant use.
- Offensive/cyber workflows.

## Known Partial Areas

- Android mission UI and offline/network-failure behavior are HUMAN_REQUIRED.
- Qdrant live memory cleanup is HUMAN_REQUIRED until a clean scan is recorded.
- `RedisSessionStore` is needed for multi-process or multi-worker testing.

## Feedback

Follow [FEEDBACK_GUIDE.md](FEEDBACK_GUIDE.md). Redact everything sensitive before
posting.
