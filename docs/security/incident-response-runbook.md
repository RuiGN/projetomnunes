# Incident Response, Backup, and Continuity Runbook

Owner: Security and Privacy
Review cadence: quarterly and after every incident or exercise
Scope: application, database, object storage, integrations, credentials, and tenant isolation

This runbook applies to suspected and confirmed events. Responders must minimize personal data in tickets and chat, use UTC timestamps, preserve evidence before destructive containment, and never copy clinical content into operational records.

## Severity and escalation

| Level | Definition | Initial response | Mandatory escalation |
|---|---|---:|---|
| SEV-1 | Confirmed or credible cross-tenant exposure, destructive compromise, material loss of sensitive data, or broad production outage | 15 minutes | Incident Commander, Security Lead, Data Protection Officer, Legal, Engineering Lead, and executive owner immediately |
| SEV-2 | Confirmed unauthorized access contained to one tenant or material degradation without proven broad disclosure | 30 minutes | Incident Commander, Security Lead, Data Protection Officer, Legal, and service owner |
| SEV-3 | Limited event with no confirmed sensitive-data exposure and a functioning workaround | 4 hours | Service owner and Security Lead; escalate if scope or impact increases |
| SEV-4 | Low-risk anomaly, blocked attempt, or process defect with no current impact | 1 business day | Service owner; Security reviews trends |

The first qualified responder becomes Incident Commander until an explicit handoff is recorded. The Incident Commander owns classification, timeline, work assignments, decision log, and closure. The Security Lead owns technical containment and evidence. The Data Protection Officer owns privacy impact assessment. Legal determines contractual and regulatory duties. Communications prepares approved notices. Operations owns recovery. Clinical leadership is consulted when continuity can affect patient care, but operational responders do not inspect clinical content unless expressly authorized and necessary.

Create a restricted case and a secure incident channel outside a potentially compromised tenant. Do not use the affected integration, mailbox, or account as the only coordination channel. Record every escalation, handoff, decision, and reason in UTC. Reassess severity after each material fact; uncertainty defaults upward, not downward.

## First 30 minutes

1. Open the incident record with a random identifier; record reporter, discovery time, systems, tenants potentially affected, current severity, and Incident Commander.
2. Start an append-only UTC timeline. Preserve relevant logs, audit checkpoints, configuration snapshots, hashes, provider event identifiers, and volatile evidence before rotation or shutdown when safe.
3. Restrict access to named responders and begin chain of custody records for every evidence item.
4. Apply the narrowest effective containment. Do not delete records, rebuild hosts, revoke all tenants, or notify external parties without recording scope and rationale.
5. Confirm an independent communication route and schedule the next update.

## Containment matrix

### Account containment

Disable the affected account, prevent new authentication, revoke authentication factors only after preserving account state and login evidence, and require identity verification before recovery. Do not alter unrelated users.

### Session containment

Invalidate the affected session identifiers and refresh tokens, preserve their hashes and relevant timestamps, and verify that new requests fail. Use tenant-wide or global invalidation only when evidence supports that scope.

### Integration containment

Disable the specific webhook, OAuth grant, service account, or adapter; preserve sanitized request metadata and provider event IDs; pause retries that could amplify harm; and route failed work to the exception queue.

### Key containment

Record key identifier, scope, version, and last use; snapshot dependent configuration; rotate or revoke through the key manager; re-encrypt only under an approved plan; and verify old-key rejection. Never place key material in the incident record.

### Tenant containment

Activate a tenant-scoped feature flag, maintenance boundary, or credential block. Verify that other tenants remain available and isolated. A global shutdown requires Incident Commander approval and documented proportionality.

## Evidence and chain of custody

Each evidence record contains a random evidence ID, collector, UTC acquisition time, source, collection method, SHA-256 digest, encrypted storage location, access list, and every transfer. Store originals read-only; analyze verified copies. Never edit or redact an original. If acquisition can alter evidence, record the limitation before proceeding. Access to evidence is itself audited. Retention and disposal follow the approved evidence schedule and any legal hold.

## Impact and notification decision

The Data Protection Officer and Legal maintain a notification decision record for every SEV-1 and SEV-2 event, including known facts, affected data categories, approximate people and records, tenant and geographic scope, likely consequences, safeguards already applied, residual risk, uncertainties, decision owner, legal basis, applicable deadlines, and next review time.

They assess notice to ANPD and any other competent authority under the law and guidance in force at the time; this runbook does not hard-code a legal deadline. They separately assess affected clinics, affected data subjects, processors, insurers, law enforcement, and contractual contacts. No absence-of-notification decision is implicit: it requires a dated rationale and approval.

Approved notices use plain PT-BR for Brazilian recipients and contain the nature and period of the event, data categories, likely consequences, safeguards, actions taken, protective steps available to the recipient, a privacy contact, and the next update. Notices must not expose another tenant, credentials, exploit details that increase risk, or unverified speculation. Clinics receive tenant-specific facts. Data subjects receive actionable information without clinical content.

## Recovery and continuity

Recovery occurs in an isolated environment from a backup whose encryption, provenance, and integrity digest are verified. Use synthetic data for routine exercises. Validate schema, record counts, referential integrity, audit-chain verification, tenant isolation, application health, and access controls before promotion. Record observed recovery time, recoverable data point, failures, corrective actions, owner, and due date.

Production restoration requires separate approval from Operations and the Incident Commander. Keep affected credentials revoked, monitor for recurrence, reconcile jobs and integrations idempotently, and preserve the pre-recovery environment until evidence release is approved.

## Closure and follow-up

Closure requires containment verification, recovery acceptance, completed notification decisions, evidence inventory, timeline, root cause, control gaps, and corrective actions with owners and deadlines. Conduct a blameless review within five business days for SEV-1/SEV-2. Retest corrective controls and update this runbook, contact roster, threat model, and training evidence.

## Exercise

Run both synthetic encrypted restore exercises from the repository root:

    python scripts/incident_restore_drill.py --report .hermes/evidence/incident-restore-drill.json
    python scripts/postgres_restore_drill.py --report .hermes/evidence/postgres-restore-drill.json

The first command exercises incident records, containment, notification assessment, chain of custody, measured RTO/RPO, and fail-closed fault injection. Its `--inject-failure` option is restricted to tests and drills. The PostgreSQL exercise creates distinct source and restore containers on an internal Docker network with no published ports, persists and retrieves an encrypted `pg_dump`, restores into an ephemeral target, and verifies record counts plus row-level tenant isolation.

Both commands must exit non-zero on failed integrity, isolation, count, RPO, containment, notification, or custody verification. Store only generated JSON reports as durable evidence. Temporary databases, plaintext backups, credentials, and exercise keys are destroyed when each process exits. Production restoration remains a separately authorized operation.
