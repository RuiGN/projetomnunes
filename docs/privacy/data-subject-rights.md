# Data-Subject Rights Operations

Owner: Privacy Engineering
Review cadence: quarterly and after material legal or integration changes

## Scope

The `privacy` domain implements tenant-scoped LGPD requests for confirmation, access, correction, portability, revocation, and erasure. It records the identity verification method, verifier, minimized evidence digest, assignment, decision, deadline, destination evidence, lawful retention reasons, completion time, and a canonical completion evidence digest. Only active actors can reach a request. Clinic administrators operate the workflow; the active data subject may read their own request.

## State machine

1. `identity_pending`: created with a clinic, subject, channel, request type, request date, and configured deadline.
2. `in_review`: an authorized clinic administrator verified identity and owns the review.
3. `approved` or `rejected`: a reasoned, terminal decision for review; rejected requests cannot execute.
4. `processing`: approved correction, revocation, or erasure is being propagated. A failed destination keeps this state.
5. `completed`: every declared destination returned `confirmed` or lawful `retained` evidence. Completed requests cannot regress.

The service rejects unsupported request types and invalid state transitions. Application code must not use `infrastructure_objects` outside migrations, administration scripts, and the domain services.

## Structured export

Access and portability exports require an approved request and two independent recent reauthentication actions: one to generate and one to download. `reauthenticate_actor` verifies the current password using Django's password hasher and persists a clinic- and actor-bound proof. Proofs expire according to `PRIVACY_REAUTH_MAX_AGE_SECONDS` and are consumed atomically once.

The export envelope is UTF-8 JSON with `schema_version`, the exact request subject UUID, and a `records` list assembled exclusively from authorized server-owned records filtered first by clinic and subject. The caller cannot provide the exported dataset. The envelope is encrypted with a fresh Fernet key; only ciphertext and SHA-256 integrity digests are persisted. The signed, short-lived download grant carries the key, tenant, artifact identifier, and ciphertext digest. Download rechecks tenant, actor, request authorization, expiry, grant/artifact version, and ciphertext integrity, then completes the access or portability request with canonical evidence. It emits audit events for generation and download.

Deployments must transport grants only over TLS, avoid logging query strings or grant values, and prefer an HttpOnly secure session exchange rather than placing the grant in a URL. Expired artifacts are operational cleanup candidates; a cleanup job must not remove a record under legal hold.

## Propagation and retention

Each destination adapter declares a stable `destination_key` and accepts a deterministic `operation_id` derived from request and destination. Adapters must apply that ID as an idempotency key. Destinations cover each applicable primary database, replica or search index, cache, object namespace, backup lifecycle, and integrated processor. Trusted server configuration is snapshotted as an immutable destination manifest when correction, revocation, or erasure is approved. A retry may execute a subset, but completion evaluates every manifest destination. Duplicate or unregistered keys are rejected.

Adapters return only minimized evidence: destination, outcome, provider confirmation reference, and lawful retention reason when applicable. They must not return deleted content, credentials, or clinical text. Exceptions are normalized to the exception class name and recorded as `failed`; the message is discarded. Reprocessing uses the same operation ID and updates the same request/destination row.

`confirmed` and `retained` are resolved only with a non-empty provider confirmation reference. `retained` additionally requires a reason stating the applicable obligation; it does not mean deleted. Completion evidence is canonical JSON with explicit fields before SHA-256 hashing. Operations must review retained destinations when their legal deadline expires and start the appropriate follow-up request.

## Operational checklist

1. Validate identity through the approved clinic channel and record the administrator responsible.
2. Determine scope, applicable systems, legal retention, processors, and deadline.
3. Record a reasoned approval or rejection.
4. For access/portability, reauthenticate, let the server build the minimized records list, generate, and deliver through the protected flow.
5. For correction/revocation/erasure, review the trusted destination manifest, invoke the required adapters, and reprocess only unresolved destinations.
6. Confirm every destination, review retention reasons, and verify the completion evidence digest.
7. Provide the subject with a human-readable completion response and retain the operational record under the approved schedule.

## Verification

Run:

    python -m pytest tests/test_data_subject_rights.py -q
    mypy privacy tests/test_data_subject_rights.py
    DJANGO_SETTINGS_MODULE=config.settings.test python manage.py makemigrations --check --dry-run

Tests use synthetic identities only and cover tenant denial, inactive actors, reauthentication failure and one-use proofs, encryption, audit, propagation, lawful retention, provider failure, duplicate destinations, and terminal state protection.
