# Consent access lifecycle

## Scope

This document describes the implementation evidence for PRD 8.4.5. User-facing copy remains in PT-BR translation catalogs; technical identifiers remain in en-US.

## Optional consent revocation

- `revoke_consent` appends a `revoked` manifestation to the exact published document history. Prior evidence is never overwritten.
- The generic decision flow accepts only `accepted` or `refused`. Once a version is accepted, refusal must use the dedicated revocation flow so downstream obligations cannot be bypassed. A revoked version is terminal and cannot be reactivated through the generic form; a fresh published version is required for a later authorization.
- The web flow requires an explicit reason and confirmation that revocation stops future use for the purpose without deleting historical evidence.
- The service accepts only the data subject acting for the active clinic, requires a current accepted manifestation, rejects mandatory documents, hashes the reason, and records an audit event.
- Purpose authorization resolves the newest manifestation, so a successful revocation blocks subsequent processing immediately.
- Server-owned `CONSENT_REVOCATION_DESTINATIONS` creates one idempotent pending `ConsentRevocationDispatch` per configured operational or integrated destination.
- Dispatch obligations reject ordinary update and delete operations. Every adapter execution appends an immutable `ConsentRevocationDispatchAttempt`, retains a keyed evidence digest, and emits an audit event. A claimed success without a non-empty confirmation reference is recorded as a failed attempt.
- Failed attempts remain inspectable after a later confirmation. The current obligation status is only a queue projection; it does not replace attempt history.
- The default `clinic_operations` destination creates a durable `ConsentRevocationWorkItem`. It never confirms the dispatch until an active clinic administrator records a non-empty operational reference through the tenant-scoped queue at `/consents/operations/revocations/`.
- Each queue row supplies the minimum references needed to locate the affected processing: a tenant-bound HMAC-SHA256 subject reference, document/version, purpose and dispatch UUID. It never exposes the subject's raw UUID.
- Pending work is visible as an administrative navigation notification. The work item derives its tenant exclusively from its dispatch; the database constraint requires open items to have no acknowledgement evidence and acknowledged items to have actor, time, and a non-empty keyed digest.

## Legal representation

- `LegalRepresentation` records representative, represented subject, relationship type, bounded purpose list, validity, verification, reviewer, and next review date.
- Raw evidence references are never persisted. A keyed SHA-256 digest is stored for correlation and audit evidence.
- Only an active clinic administrator may verify a representation, and both people must have active memberships with the same active clinic on the verification date. Inactive, not-yet-valid, or expired memberships are rejected.
- Representation never infers civil capacity or unrestricted authority. A representative may act only while the record is verified, within validity and review dates, and for a purpose explicitly listed in the server-owned record.
- Represented manifestations preserve the actor, represented subject, and representation evidence digest.
- Evidence, relationship type, validity, and granted powers are immutable after registration. Ordinary model/queryset update and delete operations are rejected; `transition_legal_representation` is the explicit audited service for status and review lifecycle changes.
- `REVOKED` and `EXPIRED` are terminal states. Reactivation always requires a new representation record and new evidence.
- A suspended representation remains ineligible for use and is transitioned to `EXPIRED` by the periodic review when its validity ends.

## Periodic access review

`review_access_lifecycle` is restricted to an active clinic administrator and uses the current server time. It:

1. suspends active memberships whose validity ended;
2. suspends expired care relationships and active links whose therapist membership is inactive, expired, or no longer has the therapist role, or whose patient membership is inactive/expired;
3. marks expired legal representations as expired and overdue reviews as suspended;
4. reports a newest accepted manifestation whose exact document validity ended;
5. audits every changed or blocked resource and the review itself;
6. persists an idempotent `AccessReviewRun` for the clinic and review date;
7. persists deduplicated `AccessReviewException` records containing technical resource type, UUID, reason, action, first/last-seen run and resolution state;
8. returns the persisted run ID and minimized exceptions.

The review never accepts a caller-supplied inventory or future effective date. Tenant scope is derived from the authorized clinic and applied to every query. Replaying the review on the same date returns the existing run. A still-open condition observed on another date relinks the existing exception rather than creating duplicate evidence or duplicate resource audit events. `resolve_access_review_exception` requires an active clinic administrator and a non-empty resolution reference, retaining only its keyed digest.

Cross-domain model ownership remains private. Consent orchestration calls narrow public selectors/services in `clinics` and `people` to validate active memberships and suspend inconsistent care links.

## Operations

- Process a bounded pending/failed queue with `python manage.py process_revocation_dispatches --clinic-id <uuid>`. Use `--limit <n>` to tune a job. Failed obligations are retried by default; the compatibility flag `--include-failed` no longer changes that behavior. The exit status remains unhealthy while any failed dispatch exists for the clinic, including failures outside the current limited batch.
- Administrators consume local operational obligations at `/consents/operations/revocations/`. They must enter the downstream ticket/reference only after the affected processing has actually stopped.
- Run a review with attributable administrative authority using `python manage.py review_access_lifecycle --clinic-id <uuid> --actor-id <uuid>`.
- Schedule both commands in the deployment-owned scheduler. Command availability does not itself prove that a scheduler has been configured in a particular environment.
- Do not update/delete pending or failed obligations, immutable attempts, representation evidence, or review evidence through ORM maintenance scripts. Use the explicit lifecycle services.
- Alert on overdue pending dispatches, failed dispatches, overdue representation reviews, and access-review failures.
- Keep evidence references and revocation reasons outside logs and reports; only keyed digests and normalized reason codes are allowed.

## Verification

Focused acceptance coverage is in `tests/test_consent_access_lifecycle.py`, including the public operational queue and notification, database acknowledgement invariants, command execution, cross-tenant denial, multiple destinations, adapter exceptions, empty confirmation evidence, append-only protection, terminal representation states, role/link consistency, persisted idempotency and explicit resolution. Architecture boundaries are enforced by `tests/test_domain_architecture.py`. Versioning and purpose-gate regressions remain in `tests/test_versioned_consents.py`.
