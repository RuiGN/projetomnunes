# Security controls baseline

Version: 1.0
Owner: Security Engineering

## Transport and browser controls

Production forces HTTPS, one-year HSTS with subdomains and preload, secure cookies, `HttpOnly` session cookies, `SameSite=Lax`, CSRF middleware, framing denial, MIME-sniffing denial, restrictive referrer behavior and an application-owned Content Security Policy. The proxy must replace untrusted forwarding headers and send `X-Forwarded-Proto` only from the trusted network path.

## Secret rotation

- Separate credentials exist for development, test, staging and production.
- Secrets are injected at runtime; repository files contain names and placeholders only.
- Each credential has an owner, service scope, creation date, planned expiry and emergency revocation procedure.
- Rotation creates a new credential, deploys dual-read/single-write where required, verifies use, revokes the old credential and records evidence without recording either value.
- Suspected exposure triggers immediate revocation and incident handling rather than waiting for scheduled rotation.

## Least privilege

Application, migration, backup, monitoring and operator identities are distinct. Runtime database credentials cannot create roles or bypass tenant policy. Object-storage identities are restricted to tenant-prefixed quarantine/private namespaces and required operations. Human production access is time-bound, MFA-protected and audited.

## Private object storage

Uploads enter a non-public quarantine namespace under an opaque server-generated name. Validation checks size, allowlisted extension, declared media type and magic bytes. Downloads require current tenant and object authorization and use short-lived signed URLs with no public ACL. Browser-supplied paths and object keys are never trusted.

## Malware quarantine

Objects remain unavailable while the normalized scan state is `pending` or `error`, are rejected and isolated when `infected`, and become eligible for authorized delivery only when `clean`. Scanner outage fails closed, creates an operational exception and never publishes the object.

## Database encryption

Production databases and replicas require provider-managed volume encryption and encrypted service connections. High-risk free text and credential-like integration material use field-level encryption before persistence when introduced. Search/index design must not silently duplicate plaintext.

## Backup encryption

Every backup is encrypted before leaving the database boundary, stored in a separate account or security boundary and tested for restore. Backup identities can write new recovery points but cannot alter existing protected points. Retention expiry and legal hold are enforced independently.

## Field-level encryption

Field encryption uses authenticated encryption, a versioned key identifier and context binding for tenant, model and field. Ciphertext does not share a key with logs, backups or signing. Rotation supports decrypt-old/encrypt-new and records counts, not values.

## Independent key management

Encryption keys are held in a KMS or HSM service separate from protected data. Applications receive only the minimum cryptographic operation permission. Key administrators cannot read application data, data administrators cannot export key material, and emergency access requires documented approval and audit.
