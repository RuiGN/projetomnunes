# PRD 8.4.5 Independent Review Remediation Plan

> **For agentic workers:** Execute inline with strict RED -> GREEN slices. The user explicitly prohibited commits, pushes, deploys, and marking the PRD complete.

**Goal:** Close every independent-review finding while preserving durable evidence, tenant authorization, race idempotency, and truthful operational command status.

**Architecture:** Keep revocation dispatches as durable delivery obligations, add a separate tenant-scoped operational work item for the default clinic destination, and require explicit acknowledgement before confirmation. Harden representation and access-review transitions at service boundaries, serialize daily reviews on the clinic row with uniqueness recovery, and make the dispatch command report actual outcomes and overdue work.

**Tech Stack:** Django 6.1, PostgreSQL/SQLite test settings, pytest-django, Ruff, mypy.

## Global Constraints

- Preserve the dirty worktree and all unrelated work.
- Add regression tests and capture expected RED before production changes.
- Keep code identifiers in en-US and user-facing copy in PT-BR with accents.
- Do not commit, push, deploy, or mark PRD 8.4.5 complete.

---

### Task 1: Durable clinic-operations acknowledgement

**Files:**
- Modify: `tests/test_consent_access_lifecycle.py`
- Modify: `consents/models.py`
- Modify: `consents/adapters.py`
- Modify: `consents/services.py`
- Create: `consents/migrations/0007_revocation_operational_work_item.py`

- [ ] Add tests proving the default adapter creates one durable work item, remains unconfirmed while open, and confirms only after an authorized explicit acknowledgement.
- [ ] Add a test proving an unregistered or unconfigured mandatory destination fails visibly.
- [ ] Run the focused tests and retain the expected failures.
- [ ] Add the protected work-item model and acknowledgement service, with minimized digest evidence and audit events.
- [ ] Make `clinic_operations` idempotently create/read the work item and return confirmation only after acknowledgement.
- [ ] Run the focused tests to GREEN.

### Task 2: Representation authorization state machine

**Files:**
- Modify: `tests/test_consent_access_lifecycle.py`
- Modify: `consents/services.py`

- [ ] Add tests denying `revoked`/`expired` to `verified`, denying suspended-record reactivation, and denying represented `Audience.ALL` manifestations when the subject lacks active membership.
- [ ] Run the focused tests and retain the expected failures.
- [ ] Enforce terminal states and require a new evidence-bearing registration for any re-verification.
- [ ] Require current represented-subject membership before any represented manifestation.
- [ ] Run the focused tests to GREEN and verify no successful manifestation/audit is created on denial.

### Task 3: Recurring exception lifecycle and race-idempotent daily review

**Files:**
- Modify: `tests/test_consent_access_lifecycle.py`
- Modify: `consents/services.py`

- [ ] Add a recurrence test that resolves an exception, observes the condition on a later run, reopens it, retains prior resolution fields, and records a reopen audit event.
- [ ] Add a PostgreSQL transaction test with two connections synchronized before clinic locking; both callers must receive one run ID.
- [ ] Run the focused tests and retain the expected failures (with the concurrency case skipped only when PostgreSQL is unavailable).
- [ ] Reopen recurring exceptions under lock without erasing prior resolution evidence, and append a dedicated minimized audit event.
- [ ] Lock the clinic before recheck/create and recover a residual unique race through a nested savepoint.
- [ ] Run the focused tests to GREEN on SQLite and PostgreSQL where available.

### Task 4: Truthful dispatch operations command

**Files:**
- Modify: `tests/test_consent_access_lifecycle.py`
- Modify: `consents/management/commands/process_revocation_dispatches.py`
- Modify: `config/settings/base.py`
- Modify: `config/settings/development.py`
- Modify: `config/settings/production.py`
- Modify: `config/settings/test.py`

- [ ] Add command tests for separate confirmed/failed counts, nonzero failure exit, retrying failed obligations by default, and overdue pending/failed exposure.
- [ ] Run the focused tests and retain the expected failures.
- [ ] Select pending and failed rows by default, count persisted outcomes, report overdue obligations using a documented settings threshold, and raise `CommandError` after the summary when failures remain.
- [ ] Run the focused tests to GREEN.

### Task 5: Documentation and verification

**Files:**
- Modify: `docs/security/consent-access-lifecycle.md`
- Verify unchanged unchecked state: `PRD.md`

- [ ] Document acknowledgement, retry, failure-exit, overdue, state-machine, recurrence, and race-idempotency contracts.
- [ ] Run focused tests.
- [ ] Run the full test suite.
- [ ] Run `ruff check .`.
- [ ] Run `mypy` with the project configuration.
- [ ] Run `python manage.py check`.
- [ ] Run `python manage.py makemigrations --check --dry-run`.
- [ ] Review the final diff/status and prove PRD 8.4.5 remains unchecked.
