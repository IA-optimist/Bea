# Tester Safety Rules

These rules apply to every Private Beta 0.1 tester.

## Never Use

- Real API keys, passwords, tokens, private keys, or credentials.
- Real private data.
- Real medical data.
- Real financial data.
- Real customer data.
- Confidential employer or client material.
- Dangerous actions against third-party systems.

## Required Behavior

- Use toy data.
- Keep logs redacted.
- Use one tester token per tester.
- Report policy bypasses, auth surprises, and memory leaks immediately.
- Stop testing if a secret or sensitive item appears in output, logs, memory, or
  an issue.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: owner rotates any exposed token.
- HUMAN_REQUIRED: owner cleans any sensitive memory item.
- HUMAN_REQUIRED: owner records any incident before inviting more testers.
