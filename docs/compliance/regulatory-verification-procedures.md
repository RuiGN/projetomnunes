# Regulatory Verification Procedures

Owner: Compliance Engineering
Human approvers: Clinical owner and Legal/Regulatory owner
Review cadence: each release, each matrix change, and when an applicable source changes

These procedures are evidence definitions, not approvals. Results must be recorded in a review artifact, linked from the matching acceptance, and hashed by `scripts/check_regulatory_matrix.py`. Regulated release remains blocked until both designated human owners accept the exact matrix version.

## Clinical confidentiality copy review

1. Confirm that privacy, consent, sharing, emergency, and professional-limit copy is in PT-BR and states the actual purpose and audience.
2. Confirm that no administrative role receives implied access to clinical content.
3. Record reviewer, date, matrix version, findings, exceptions, and decision.
4. Attach the completed artifact to the clinical acceptance.

## Retention and record schema review

1. Compare every record category with the data inventory and processing register.
2. Confirm access scope, retention trigger, retention period, legal hold, deletion/anonymous outcome, and evidence produced.
3. Exercise `tests/test_data_subject_rights.py` and record the result.
4. Record unresolved conflicts as release blockers.

## Psychological documents

1. Before Sprint 18 release, map each document class to its applicable CFP provision, required author, recipient, purpose, signature class, custody, and retention rule.
2. Review every production template clinically and legally.
3. Run the Sprint 18 document-class and signature acceptance suites when implemented.
4. Block release if a class, template, reviewer, or applicable provision is missing.

## Legal entity eligibility

1. Confirm organization category, jurisdiction, professional registration requirements, technical responsibility, validity period, and evidence source.
2. Test inactive, expired, wrong-jurisdiction, and cross-tenant records.
3. Record clinical and legal/regulatory decisions for the exact matrix version.
4. Block regulated activation on missing or expired evidence.

## TDIC service and emergency boundaries

1. Review versioned service terms, professional suitability, territorial eligibility, monitoring hours, and emergency limitations.
2. Confirm that the application does not promise continuous monitoring or automated clinical decisions.
3. Run the relevant identity/consent tests and the regulated-module release gate.
4. Record findings and both required decisions before TDIC-mediated clinical release.

## CRP-02 legal entity registration

1. Validate CRP-02 registration, certificate validity, renewal status, technical supervisor, and professional regularity against the current official source.
2. Record source URL and verification date without copying unnecessary personal data.
3. Test missing, expired, revoked, wrong-tenant, and wrong-jurisdiction evidence before tenant activation.
4. Obtain legal/regulatory acceptance and clinical acceptance for the exact matrix version.
