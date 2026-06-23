---
name: Security Report
about: Report a potential security vulnerability or data leak in Béa
title: "[SECURITY]: "
labels: ["security"]
---

## Important

**Do NOT include sensitive data, exploit details, or proof-of-concept code
in this issue.** Provide a summary only. Maintainers will contact you for
details if needed.

If you prefer, you may also report security issues privately via GitHub's
"Report a vulnerability" feature:
**https://github.com/IA-optimist/Bea/security/advisories/new**

## Summary

Briefly describe the potential security issue (1-3 sentences).

## Area

- [ ] API authentication / authorization
- [ ] Data leak (logs, memory, artifacts)
- [ ] Provider key exposure
- [ ] Self-improvement gate bypass
- [ ] Injection (prompt, SQL, command)
- [ ] Other

## Impact

What could an attacker do if this vulnerability is exploited?

## Affected version

- Commit hash: 
- OS: 

## Steps to reproduce

**Do NOT include actual exploit code or real secrets.** Describe at a high
level what conditions are needed to trigger the issue.

## Have you rotated any exposed keys?

- [ ] Yes, I have rotated all exposed API keys/tokens
- [ ] No keys were exposed
- [ ] I need guidance on how to rotate

## Additional context

Any other relevant information (redacted).
