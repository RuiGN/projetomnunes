# Clinic authorization matrix

Technical action identifiers remain in en-US. User-facing labels remain in pt-BR.
All decisions are evaluated on the backend and default to denial.

| Action | Clinic admin | Therapist | Administrative staff | Patient | Additional conditions |
|---|---:|---:|---:|---:|---|
| `clinic.read` | Yes | Yes | Yes | No | Active user, clinic and membership |
| `clinic.manage` | Yes | No | No | No | Active user, clinic and membership |
| `professionals.manage` | Yes | No | No | No | Active user, clinic and membership |
| `patients.create` | Yes | No | Yes | No | Active user, clinic and membership |
| `patient.demographics.read` | Yes | Yes | Yes | No | Patient must have a current patient membership in the same clinic; resource must be active |
| `patient.clinical.read` | No | Yes | No | No | Patient must have a current patient membership and an active, dated therapist-patient relationship in the same clinic; resource must be active |
| `audit.read` | Yes | No | No | No | Active user, clinic and membership; audit-specific policy still applies |
| `invitation.issue` | Yes | No | No | No | Active user, clinic and membership |
| `invitation.revoke` | Yes | No | No | No | Active user, clinic and membership |
| `membership.enumerate` | Yes | No | No | No | Active user, clinic and membership |
| `membership.update` | Yes | No | No | No | Target membership must belong to the active clinic |
| `mfa.reset` | Yes | No | No | No | Target must belong to the active clinic; reset is audited and revokes sessions |

## Enforcement rules

1. The authenticated identity has no global business role. Roles are dated `ClinicMembership` records.
2. An inactive identity, clinic, membership or resource grants no access.
3. Unknown action identifiers are denied.
4. A patient identifier is resolved through a tenant-scoped membership before the user record is returned.
5. Clinical access requires an active `CareRelationship`; demographic access does not imply clinical access.
6. Altering a URL or UUID cannot move authorization to another tenant or bypass the relationship requirement.
7. Interface visibility is not an authorization control. Services, selectors and policies enforce the same decision on the server.
