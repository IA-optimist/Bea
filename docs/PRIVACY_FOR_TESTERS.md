# Privacy For Testers

Private Beta 0.1 uses toy data only.

## Do Not Provide

- Real secrets.
- Real private data.
- Medical data.
- Financial data.
- Customer data.
- Confidential employer or client data.
- Regulated data.

## Memory Warning

The 2026-06-26 Qdrant live privacy scan found 1 private item in the live store.
That means Qdrant live memory is cleanup required until a later report proves a
clean scan.

## What Is Allowed

- Synthetic examples.
- Public documentation.
- Toy credentials like `example-token`.
- Redacted logs.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: clean private memory items before wider testing.
- HUMAN_REQUIRED: rotate any exposed secrets.
