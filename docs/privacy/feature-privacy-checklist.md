# Privacy gate for new features

A feature cannot be marked complete until every applicable item has evidence and unresolved items have a named approver and blocking decision.

## Data minimization

- [ ] Every field maps to a category in `data-inventory.md` and a row in `processing-register.md`.
- [ ] Optional fields are genuinely optional and the empty state works.
- [ ] Free text is avoided when a bounded value meets the purpose.
- [ ] The UI explains why a sensitive field is needed and who can see it.

## Purpose and legal basis

- [ ] Purpose, necessity, controller, processor, recipients and proposed legal basis are documented.
- [ ] No implicit secondary use: analytics, advertising, AI training and unrelated product experiments require a separate assessment.
- [ ] Sensitive fields require justification and the approved LGPD basis before collection.
- [ ] Consent is granular, unbundled, versioned and revocable when it is the selected basis.

## Authorization and tenancy

- [ ] Tenant isolation is enforced in models/selectors/services, jobs, cache keys, files, reports and tests.
- [ ] Object access combines active membership, role, relationship, purpose and item visibility.
- [ ] Negative tests cover guessed IDs, another tenant, ended relationships and revoked authorization.

## Professional and regulatory eligibility

- [ ] Every regulated capability identifies the profession, jurisdiction, governing matrix entry and evidence required before authorization.
- [ ] Eligibility is resolved from current server-owned professional regulatory evidence; a generic role, UI state or caller-supplied council status is never sufficient.
- [ ] Clinic legal-entity registration, technical supervisor and certificate evidence are current when the competent jurisdiction requires them.
- [ ] Expired, revoked, unverified or superseded evidence fails closed while preserving the historical record required for accountability.
- [ ] A digitally mediated psychological service has a versioned TDIC service agreement covering service characteristics, rights and duties, technologies, confidentiality resources, forum and organization.

## Psychological records and restricted material

- [ ] Each clinical field is classified as patient self-report, Psychological record, administrative data or Restricted assessment material before implementation.
- [ ] Psychological record content implements the approved minimum fields, authorship, version/adendum, access, referral/closure and retention rules.
- [ ] Restricted assessment material has separate policies, storage, export and tests and is never exposed by a general clinical-data permission.
- [ ] Emergency and protection actions record only the minimum necessary context, professional decision, disclosure/referral recipient and rationale.

## Logs and telemetry

- [ ] Logs and telemetry omit secrets, tokens, message text, journal content, attachments and direct identifiers where a pseudonym works.
- [ ] Audit metadata is sufficient to investigate the operation without copying the protected content.
- [ ] Dashboards use aggregation and suppress groups that create reidentification risk.

## Retention and disposal

- [ ] Retention and disposal rules name the trigger, duration, legal hold behavior, destination and evidence produced.
- [ ] Deletion/revocation propagates to caches, generated files and approved processors.
- [ ] Backups have documented expiry and restored data is re-subjected to pending deletion commands.

## Suppliers and user rights

- [ ] Supplier terms, subprocessors, processing region, security controls, incident route and exit plan are approved.
- [ ] Access, correction, portability, revocation and deletion impact are defined.
- [ ] Product copy is in PT-BR; technical identifiers, contracts and logs remain in en-US.

## Regulated release gate

- [ ] Every applicable obligation links to a current entry in the versioned CFP/CRP regulatory matrix, a backlog task, evidence and a test or documented verification procedure.
- [ ] Superseded, revoked or newly published rules have been assessed for impact before release.
- [ ] Required clinical and Legal/regulatory approver decisions identify scope, date, conditions, unresolved issues and the next review date.
- [ ] An unresolved item has a named owner and explicit blocking decision; regulated functionality cannot be released through a feature flag, administrator override or undocumented exception.

Privacy/Security reviewer: __________  Date: __________  Decision: approve / changes required / reject

Clinical approver: __________  Date: __________  Decision: approve / changes required / reject

Legal/regulatory approver: __________  Date: __________  Decision: approve / changes required / reject
