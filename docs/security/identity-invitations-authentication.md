# Identity, Invitations, and Authentication

## Scope

The `accounts` domain owns the global login identity and credential lifecycle. A `User` has a UUID primary key, a canonical case-folded e-mail identifier, Django's active status, security timestamps, and no global business role. Clinic roles remain exclusively in `ClinicMembership`.

The implementation exposes no open registration flow. New clinic identities are created only by consuming a live `ClinicInvitation` through the transactional service boundary.

## Domain boundaries

`accounts` may orchestrate only the public `clinics.selectors`, `clinics.services`, and `audit.services` contracts. It does not import clinic or audit models. Clinic authorization uses the framework-neutral `core.policies.current_actor_is_active` check, avoiding an `accounts <-> clinics` dependency cycle.

Invitation records are tenant-scoped by default. Common queries require `ClinicInvitation.objects.for_clinic(clinic_id)`; the unrestricted manager is reserved for bearer-token resolution inside the invitation service.

## Invitation lifecycle

`issue_invitation` requires a current active `clinic_admin` membership in the target clinic. It records issuer, canonical recipient e-mail, initial role, expiration, and a SHA-256 digest of a cryptographically random token. The raw bearer token is returned once and is never persisted.

`accept_invitation` locks the invitation row, rejects expired, revoked, used, inactive-tenant, duplicate-account, and invalid-token cases with one generic PT-BR response, then creates the identity and clinic membership atomically. Reuse is rejected. `revoke_invitation` is tenant-scoped, permission-checked, row-locked, and audited.

## Login and logout

`POST /accounts/login/` authenticates by canonical e-mail, applies shared-cache fixed-window failure limits to both the pseudonymized identity and the combination of network origin plus identity, rotates the session through Django login, and selects only a currently authorized active clinic. Unknown identity, wrong password, inactive identity, and identity without an active clinic share the same PT-BR response. Production requires `CACHE_URL` and uses Django's shared Redis cache backend so limits remain coherent across worker processes; process-local cache is limited to development and tests.

`POST /accounts/logout/` is intentionally POST-only. It audits the active authorized clinic context when available and always flushes the session.

Relevant settings:

- `LOGIN_RATE_LIMIT_ATTEMPTS` (default `5`)
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS` (default `300`)
- `LOGIN_URL` (default `/accounts/login/`)

## Password recovery

`POST /accounts/password-recovery/` returns the same response for known and unknown e-mail addresses and has a separate rate limit. A message is sent only for an active identity with at least one current active clinic membership.

The reset credential uses Django's signed, short-lived, single-use token contract. `PASSWORD_RESET_TIMEOUT` defaults to 900 seconds. Successful reset validates the new password, advances both credential and security timestamps, invalidates all existing Django sessions through the changed authentication hash, and appends a minimized audit event for each affected active clinic.

Relevant settings:

- `PASSWORD_RECOVERY_RATE_LIMIT_ATTEMPTS` (default `5`)
- `PASSWORD_RECOVERY_RATE_LIMIT_WINDOW_SECONDS` (default `900`)
- `PASSWORD_RESET_TIMEOUT` (default `900`)

## Managed sessions and multifactor authentication

Every canonical login registers a pseudonymized `AccountSession` before the next protected request. The middleware rejects unknown sessions in production, enforces absolute and idle expiration, and preserves the original absolute deadline when an intentional clinic switch rotates the Django session key. Users can inspect minimized client and network hints and revoke one session or all other sessions. Global revocation requires the current password and invalidates both tracked records and their Django session rows.

TOTP enrollment is confirmed before activation. Recovery codes are stored only as digests, displayed once under `Cache-Control: no-store`, and consumed atomically once. MFA attempt limits and sensitive reauthentication limits reserve attempts atomically in the shared cache. Clinic administrators, therapists, administrative staff, Django staff and superusers must complete MFA when production enforcement is active. The Django Admin password entrypoint redirects through the primary login so rate limiting and authentication auditing cannot be bypassed; after enrollment or verification, only a validated same-host local destination is restored.

Administrative MFA recovery requires an active clinic administrator in the same tenant, verified MFA, current-password reauthentication and a non-empty justification. It removes the target TOTP and recovery credentials, invalidates the target sessions, advances the target security timestamp and records only a digest of the justification in the append-only audit chain.

Relevant settings:

- `ACCOUNT_SESSION_IDLE_SECONDS` (default `1800`)
- `ACCOUNT_SESSION_ABSOLUTE_SECONDS` (default `28800`)
- `MFA_ENFORCEMENT_ENABLED` (enabled by default in production)
- `MFA_RATE_LIMIT_ATTEMPTS` and `MFA_RATE_LIMIT_WINDOW_SECONDS`
- `SENSITIVE_REAUTH_RATE_LIMIT_ATTEMPTS` and `SENSITIVE_REAUTH_RATE_LIMIT_WINDOW_SECONDS`

## Security and privacy invariants

- Raw invitation and reset credentials never enter logs or database fields.
- Rate-limit keys contain only an HMAC-derived digest, not raw e-mail or network origin.
- Audit events contain tenant, actor UUID, technical action, resource identifier, outcome, request correlation, and a digest of network origin; they contain no credential or message body.
- Authentication responses do not disclose account or membership existence.
- Tenant selection and invitation administration are reauthorized against current database state.
- All user-facing authentication copy and validation are PT-BR; technical identifiers, routes, settings, and persisted enum values are en-US.

## Verification

The acceptance suites are `tests/test_accounts_identity.py` and `tests/test_accounts_authentication.py`. Cross-tenant authorization and dependency direction are covered by `tests/test_clinic_authorization.py`, `tests/test_tenant_middleware.py`, and `tests/test_domain_architecture.py`.
