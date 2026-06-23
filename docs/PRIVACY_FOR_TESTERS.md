# Béa — Privacy Guide for Testers

> Béa processes text through external LLM providers (OpenRouter, Ollama).
> This guide explains what data is safe to share and how to protect sensitive
> information.

---

## 1. Golden rules

1. **Never paste API keys, tokens, or passwords into Béa prompts.**
2. **Never use real customer data in test missions.**
3. **Never share your `.env` file.**
4. **Redact all secrets before posting logs or issues.**
5. **If you accidentally expose a secret, rotate it immediately.**

## 2. What Béa sends to external providers

When you submit a mission, Béa sends your prompt and relevant memory context
to the configured LLM provider (OpenRouter or Ollama). This data is processed
on the provider's servers.

**What gets sent:**
- Your mission goal/prompt text
- Relevant memory items retrieved from the local store
- System prompts with role instructions (no secrets)

**What does NOT get sent:**
- Your `.env` file contents
- Your API keys (used only for authentication headers)
- Files on your disk (unless explicitly attached to a mission)

## 3. Safe test data

Use only **synthetic, non-sensitive** data for testing:

| Safe to use | Do NOT use |
|-------------|------------|
| Lorem ipsum text | Real customer documents |
| Example names (`Alice`, `Bob`) | Real person names |
| Fake API keys (`sk-FAKE1234...`) | Real API keys |
| Public repo files (`docs/ARCHITECTURE.md`) | Private company code |
| Synthetic JSON (`{"advice": "test"}`) | Real financial/medical data |

## 4. How to anonymize logs

Before sharing logs in a GitHub issue, apply these replacements:

```
# API keys
sed -i 's/sk-or-v1-[A-Za-z0-9-]*/sk-or-v1-[REDACTED]/g' log.txt
sed -i 's/sk-ant-[A-Za-z0-9-]*/sk-ant-[REDACTED]/g' log.txt
sed -i 's/sk-[A-Za-z0-9]*/sk-[REDACTED]/g' log.txt

# Bearer tokens
sed -i 's/Bearer [A-Za-z0-9._-]*/Bearer [REDACTED]/g' log.txt

# Email addresses
sed -i 's/[A-Za-z0-9._%+-]*@[A-Za-z0-9.-]*\.[A-Za-z]*/[EMAIL REDACTED]/g' log.txt

# JWT tokens
sed -i 's/eyJ[A-Za-z0-9._-]*/[JWT REDACTED]/g' log.txt
```

Or use the privacy audit tool:

```bash
python scripts/audit_memory_store.py --dry-run --privacy-scan --json
```

## 5. How to report a potential data leak

If you believe Béa is leaking sensitive data (e.g., API keys appear in logs,
memory items contain personal data, or generated artifacts include secrets):

1. **Stop using the affected API key immediately.**
2. **Rotate the key** at the provider's dashboard.
3. **Do NOT post the leaked data in a public issue.**
4. **Open a private security report:**
   - GitHub: use the "Security Report" issue template (private)
   - Or email: see `SECURITY_AUDIT.md` for contact
5. **Include:** what data was leaked, where it appeared (logs, memory, artifact),
   and which provider was in use.

## 6. Memory and privacy

Béa stores mission results in a local SQLite database (`operational_memory.db`)
and optionally in Qdrant (vector store). Both are local to your machine.

- **Public seed** (`--profile public`) contains only neutral project facts.
- **Dev-private seed** (`--profile dev-private`) may contain personal items —
  never use this profile on a shared or public machine.
- **Audit your memory** before sharing or migrating:

```bash
python scripts/audit_memory_store.py --dry-run --privacy-scan --json
```

## 7. What Béa does NOT do with your data

- Béa does **not** upload your local files to any external service (unless you
  explicitly attach them to a mission).
- Béa does **not** send your `.env` file to any provider.
- Béa does **not** transmit your API keys in mission prompts or memory context.
- Béa does **not** phone home or collect usage telemetry.
