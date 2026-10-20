# DOT Security Self-Assessment Report

**Project:** DOT — Cross-border & Student Finance Assistant
**Team:** Dotopia
**Track:** Topic C
**Deployment mode:** Non-on-chain
**Review date:** 21 October 2026

## Summary

DOT was built on one principle: **the AI can help with everything except moving money on its own.** The assistant reads data, runs calculations and prepares drafts, but every payment approval, every submission and every sensitive change stays in the user's hands — and the backend, not the prompt, enforces this.

Security is not an add-on in DOT. It is part of every layer:

- **AI under control.** Only registered tools can run; every argument is schema-checked; the model cannot choose its own role, and it has no tool to approve or submit a payment.
- **Money handled exactly.** All amounts are integer minor units; approvals are bound to a SHA-256 digest of the exact payment; 13 guardrails run before approval and again before submission.
- **Strong account protection.** Salted scrypt passwords, HttpOnly + SameSite=Strict sessions, CSRF protection, sign-in lockout, sign-up rate limits and strictly separated workspaces.
- **Privacy by default.** Account numbers, card numbers, IBANs and email addresses are masked before any text reaches the model; users can export or delete their data at any time.
- **Regression-tested controls.** Two rounds of attack testing (157 cases) were run against DOT. Every finding was fixed and turned into a permanent regression test. A hardening round added controls and regression cases for the risk register. The full suite of **423 tests passes**, and a recorded end-to-end session confirms the same boundaries in the running system.

## 1. Security posture at a glance

| Area | What DOT does |
|---|---|
| Payments | Non-on-chain local simulation; no real funds move. Public mode refuses to start if a chain or live payments are configured. |
| AI agent | Tool allowlist, schema validation, fixed `agent` role, bounded model loop, owner confirmation for every sensitive change, proposals normalised before they are shown |
| Identity | scrypt password hashes, 8-hour sessions stored as hashes, a five-minute lockout after five failed sign-ins, one credential per request, owner-token claim of existing data |
| Isolation | One database and one service instance per account; demo visitors get throw-away workspaces |
| Integrity | Write transactions, idempotency keys, atomic confirmations and conditional exchanges, protected balance snapshots |
| Privacy | Text redaction before the model, in-browser image masking, data export, deletion with a retry queue |
| Accountability | Append-only, hash-chained audit log for every action, tool call and decision, with a verification endpoint |
| Web | Strict same-origin CSP and security headers, DNS-pinned bank-page fetching, per-workspace rate limits, read-only non-root containers |

## 2. Permission tiers

### 2.1 Roles and tool tiers

DOT separates **who is calling** from **what a tool may do**. The roles are `owner`, `agent` and `viewer`; tools are either `view` (read and calculate) or `prepare` (create a draft, plan or proposal). The model never supplies its own role: tool execution always runs as `agent`.

### 2.2 Permission matrix

| Operation | Viewer | Agent | Owner |
|---|---|---|---|
| Read workspace data, compare and plan | Read | Through registered tools | Allowed |
| Prepare a payment draft | Denied | Allowed | Allowed |
| Propose a balance, budget, limit or recipient change | Denied | Proposal only | Allowed |
| Confirm a proposal | Denied | Denied | Allowed |
| Approve or submit a payment | Denied | **Denied** | Allowed, after all guardrails |
| Manage the user's own accounts ("Me") and sandbox currencies | Denied | Denied | Allowed |
| Clear memory or delete the account | Denied | Denied | Allowed |
| Access another user's workspace | Denied | Denied | Denied |

### 2.3 Enforcement on the server

Every request follows the same path: authenticate → select the workspace → validate arguments → check the role in the service → apply business rules → write the change and its audit record. Hiding a button is never the control; the backend is.

## 3. Account and session protection

- **Passwords** are stored only as salted scrypt hashes (`n=2^14`, `r=8`, `p=1`).
- **Sessions** use 256-bit random tokens in HttpOnly, SameSite=Strict cookies and expire after eight hours. Only a hash of each token is stored, so even a copy of the database hands out no live session. Every cookie-based write requires a same-origin header, blocking cross-site request forgery.
- **One credential per request:** a request carrying both a session cookie and a bearer token is refused outright.
- **Brute-force attempts** are limited: five failed sign-ins lock that email on that device for five minutes, and the lockout survives a restart.
- **Mass sign-up** is limited: at most five new accounts per hour per client, counted atomically in the database.
- **Existing data** can only be claimed with the server's owner token — being the first to register grants nothing.
- **Demo visitors** each receive their own temporary workspace, removed automatically after 24 hours.
- **Reserved identity:** the user's own accounts use reserved IDs (`me-<currency>`), so no recipient can impersonate the user.

## 4. Payment safety

DOT's payment flow is designed so that a payment can only happen exactly as the user approved it:

1. **Digest-bound approval.** Approval is tied to a SHA-256 digest of the exact amount, recipient, rate and fees. Change anything and the approval no longer matches.
2. **Thirteen guardrails**, run at approval and again at submission: permission, required fields, environment, route, recipient, quote expiry, per-payment limit, rolling 24-hour limit, available funds, duplicates, outstanding transactions, arrival deadline and authorisation.
3. **Idempotency.** Every draft has a unique key, so a retried request can never create a second payment.
4. **Safe recovery.** If a response is lost, the payment is marked `unknown` and reconciled under its original identity — never resubmitted blindly.
5. **Correct balances.** Payments can only draw on currencies the user actually holds or has added; a transfer between the user's own accounts is credited back, not counted as spending.
6. **No AI approval path.** Saying "yes" in chat is not approval. Approval is owner-only and enforced in the service, including direct API requests; the interface exposes that owner action.
7. **On-chain code switched off.** The legacy wallet path needs an explicit `ENABLE_ONCHAIN=true`, and public mode refuses to start with it.

## 5. Data integrity

- All writes run inside SQLite write transactions (`BEGIN IMMEDIATE`, WAL mode); a failure rolls back completely.
- Every confirmation is claimed atomically before it runs — four simultaneous clicks apply it exactly once — and a confirmation interrupted by a crash is never re-run by itself.
- Conditional exchange rules re-check status, date, rate and balance inside one transaction — tested with eight parallel requests and competing rules: each rule executes exactly once.
- Bank-statement balances cannot be replayed: future-dated, re-imported or outdated snapshots never overwrite later movements.
- Amounts are integer minor units end to end; split payments conserve every cent (verified across 25 randomised amounts).
- Spending paid by someone else (for example parents) is counted as the user's spending but never as the user's cash or debt, with one shared rule so the totals always add up.

## 6. AI safety

- **Allowlisted tools only**, each with a declared schema; unknown tools, extra fields, wrong types and oversize values are rejected before anything runs.
- **Bounded reasoning:** at most eight model rounds per turn.
- **Confirmation cards:** any sensitive change proposed by the AI becomes a pending proposal that only the owner can confirm.
- **Exact cards:** before a card is shown, the proposal is checked against the action catalogue and values the model words freely are normalised — "phone" becomes the utility category, "every month" becomes monthly, "the 5th" becomes a calendar date. What the user confirms is exactly what runs.
- **Tested against a hostile model:** a scripted model that tries to approve a payment, smuggle in the owner role, raise limits and plant a fake "approval" in memory achieves none of it.
- **Untrusted content stays data.** Bank pages, receipts, statements and memory are passed to the model as data, never as instructions; memory can never prove a balance or authorise an action.
- **Evidence before trust.** A bank fee or rate is accepted only if its exact quote is on the bank's own page, with the amount bound to its currency, and the rate is within 15% of the reference rate. Unverified figures are clearly labelled and never ranked as "best".
- **Safe browsing.** The AI's bank-page reader accepts only public HTTPS addresses, connects to exactly the address it checked (no DNS-rebinding window), checks every redirect and caps page size. A fee page suggested by the AI must be on the bank's own website.
- **Usage budgets:** assistant requests, image readings and page fetches are rate-limited per workspace.

## 7. Privacy

- **Masking before the model:** account numbers, card numbers, IBANs and email addresses become placeholders such as `[ACCT_1 …2222]`; the real values are restored only locally.
- **User control:** export all data as JSON, clear conversations or memory notes, and close the account at any time.
- **Reliable deletion:** account deletion revokes all sessions immediately; any file that cannot be removed at once is queued and retried, never falsely reported as deleted.
- **Image masking:** before a receipt or screenshot is sent, the user drags boxes over private details; those areas are painted black into the picture itself in the browser, so the original pixels never leave the device. The masking area matches the picture exactly at any shape, including tall phone screenshots.
- **Secrets stay in the environment:** API keys and mail credentials are read only from `.env` and never appear in error messages.

## 8. Audit and transparency

Every action, tool call, guardrail result and decision is written to an audit log with its actor, outcome, time and request ID. Database triggers reject updates and deletes on the audit table, making it append-only, and every entry is linked to the previous one by a SHA-256 hash chain: altering any entry breaks the chain, and the owner's `/audit/verify` check points to exactly where. The chain can also be verified outside the server: the evidence tool recomputes every link from an exported session. Every number shown to the user carries its source and date — reference rate, bank page, third-party data or estimate.

## 9. Web and deployment hardening

- Strict Content Security Policy (`default-src 'self'`), `frame-ancestors 'none'` and `nosniff` on the application.
- `X-Frame-Options`, a strict referrer policy and a Permissions-Policy limit what pages and embeds can do.
- The backend runs as a non-root user; both containers have read-only file systems, drop unneeded Linux capabilities and run with `no-new-privileges`.
- Secure (HTTPS-only) cookies are enforced automatically in public mode.
- The default port binds to the local machine only.
- Public deployment mode refuses to start if any on-chain or live-payment setting is present.

## 10. Verification and adversarial testing

DOT's security was tested by attacking it.

| Verification | Result |
|---|---|
| Full project test suite | **423 passed, 0 failed** |
| Security regression cases (two attack rounds, included above) | **159 passed** |
| Risk-register hardening cases, incl. a hostile-model test (included above) | **23 passed** |
| Concurrency tests (parallel execution, competing rules, cancellation, rollback) | Passed |
| Randomised money-conservation tests | Passed (25 seeds) |
| Recorded end-to-end session (5-minute demo, real browser, Docker deployment) | 102 audit entries, hash chain intact and independently recomputed; **0** payment approvals or submissions by the AI |

Two internal rounds of adversarial testing probed access control, CSRF, SSRF, race conditions, ledger integrity and evidence checks. Every issue they found was fixed and is now a permanent regression test:

| ID | Issue found | Fix | Status |
|---|---|---|---|
| N01 | Fee evidence could take an amount from the wrong context | Amount bound to its currency within one clause; limits excluded | Fixed and tested |
| N02 | Invalid dates accepted on edit | Strict calendar validation | Fixed and tested |
| N03 | Oversized amounts caused server errors | Typed, bounded inputs with clear errors | Fixed and tested |
| N04 | Parallel sign-ups could exceed the limit | Atomic counting in one transaction | Fixed and tested |
| N05 | Future-dated balances could be reused | Future snapshots excluded | Fixed and tested |
| N06 | Re-importing a statement could restore spent money | Duplicate and stale snapshots rejected | Fixed and tested |
| N07 | Expired rules still showed as active | Expiry committed before refusal | Fixed and tested |

Earlier attack-round findings (S01–S13) were fixed in the same way. The team then went through its own risk register and implemented the listed hardening controls — atomic confirmations, one credential per request, image masking, DNS pinning, persistent sessions, rate limits, a hash-chained audit log and normalised assistant proposals — each with its own test. Fast, test-backed remediation is part of how DOT is built.

## 11. Continuous hardening roadmap

DOT has controls for a non-on-chain competition demonstration; they do not establish complete security coverage. The remaining steps belong to a public launch and its hosting environment:

1. Red-team testing with the live AI model (hostile pages, memory and multilingual prompts).
2. TLS certificates, encrypted storage and backups on the production host.
3. Anchoring the audit chain in an external write-once store.
4. Dependency scanning and load testing in the deployed environment.

## 12. Conclusion

DOT shows that an AI finance assistant can be genuinely helpful without being trusted with money. The model plans and prepares; the backend decides; the user approves. Strong authentication, digest-bound approvals, thirteen guardrails, atomic confirmations, transactional integrity, text and image masking and a hash-chained audit trail work together, and a 423-test suite — including two rounds of adversarial cases and a hardening round — verifies them, together with a recorded end-to-end session whose audit log proves that only the user approved.

For a non-on-chain cross-border and student-finance assistant, DOT delivers a robust, transparent and well-tested security design.

## Appendix: Code references

| Control | Source |
|---|---|
| Authentication and workspaces | [api.py](../finance/api.py), [auth.py](../finance/auth.py) |
| Roles and payment guardrails | [service.py](../finance/service.py) |
| Tools and agent | [tools.py](../finance/tools.py), [agent.py](../finance/agent.py) |
| Proposals and confirmed actions | [planning.py](../finance/planning.py), [actions.py](../finance/actions.py) |
| Transactions, audit and hash chain | [store.py](../finance/store.py) |
| Hardening tests | [test_hardening.py](../tests/test_hardening.py) |
| Execution evidence (demo recording, operation log) | [demo_full.py](../tests/browser/demo_full.py), [evidence_report.py](../scripts/evidence_report.py) |
| Privacy and memory | [privacy.py](../finance/privacy.py), [memory.py](../finance/memory.py) |
| Spending, statements and payers | [expenses.py](../finance/expenses.py), [money.py](../finance/money.py) |
| Budgets and conditional rules | [decide.py](../finance/decide.py), [student.py](../finance/student.py) |
| Bank evidence and knowledge base | [banks.py](../finance/banks.py), [bank_kb.py](../finance/bank_kb.py) |
| Deployment | [compose.yaml](../compose.yaml), [Dockerfile](../Dockerfile), [nginx.conf](../frontend/nginx.conf) |


## Submission verification and residual scope

The latest runnable setup and test commands are in [README.md](../README.md). See [TEST-RESULTS.md](TEST-RESULTS.md) for the 21 October 2026 submission run; the counts above describe the earlier application-only run and should not be added to the latest total.

Implemented controls replace earlier missing-control findings, but their scope remains specific:

| Area | Current boundary | Follow-up |
|---|---|---|
| Proposal execution | Atomic claiming prevents concurrent duplicate confirmation. Claiming, business writes and final status are separate transactions. | Reconcile interrupted operations; assess failures after partial effects. |
| Privacy | Text patterns are redacted; users can paint over sensitive image regions. | Check names, context and unmasked pixels before upload. |
| Audit | Hash-chain verification detects tested edits. A host administrator can replace both records and the chain. | Anchor checkpoints outside the host; define backup retention. |
| Model and web evidence | Scripted hostile-model cases and source checks pass. | Live-model evaluation and complex fee interpretation need continued testing. |
| Hosting | Local containers and public-mode checks are provided. | HTTPS, encrypted storage, dependency scanning and measured load tests remain deployment work. |
