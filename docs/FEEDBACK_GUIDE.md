# Béa — Feedback Guide

> For private beta testers. Use the issue templates in `.github/ISSUE_TEMPLATE/`.

## What we want

- **Bugs**: crashes, wrong errors, silent failures, auth bypasses.
- **Confusion**: steps that a junior developer would not understand.
- **Performance**: slow missions, high memory usage, repeated timeouts.
- **Docs gaps**: anything missing, outdated, or misleading.

## What we do not want yet

- Feature requests for big new capabilities.
- Public marketing or screenshots without approval.
- Reports containing secrets, personal data, or customer data.

## How to write a great bug report

1. **One issue per report.** Do not pile five bugs into one ticket.
2. **Reproduce first.** If you cannot reproduce it, label it “intermittent”.
3. **Use the template.** It asks for OS, commit SHA, provider, endpoint, steps, expected, observed, logs.
4. **Redact logs.** Replace tokens, passwords, IPs, and emails with `REDACTED`.
5. **Confirm cleanliness.** Check the box that says “I have removed secrets and private data”.

## Bug severity

- **Critical**: security issue, data loss, system cannot start.
- **High**: crash, auth bypass, mission results silently lost.
- **Medium**: confusing behavior, performance regression, docs wrong.
- **Low**: typo, cosmetic issue.

## Security reports

**Never** open a public issue for a suspected security problem. Use `.github/ISSUE_TEMPLATE/security_report.md` and send it privately to the operator.

## Feedback loop

1. Tester opens an issue from a template.
2. Operator triages within 48 hours.
3. If accepted, the issue is labeled `beta/private` and assigned.
4. A fix lands on `beta/private-readiness-kilo-kimi` or `main`.
5. Tester verifies the fix and closes or comments.

## Claim honesty

When describing Béa to others, use only these terms:

- private beta
- developer preview
- experimental

Do **not** say: stable, production-ready, fully autonomous, enterprise-grade.

## Template quick links

- [Bug report](../.github/ISSUE_TEMPLATE/bug_report.yml)
- [Beta feedback](../.github/ISSUE_TEMPLATE/beta_feedback.yml)
- [Security report](../.github/ISSUE_TEMPLATE/security_report.md)
