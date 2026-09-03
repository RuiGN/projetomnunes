# Django Foundation Setup

This repository targets Python 3.14 and Django 6.1. Application identifiers,
configuration, tests, and technical documentation use American English. All
user-visible content must use Brazilian Portuguese.

## Local environment

1. Create and activate a virtual environment:

   ```bash
   python3.14 -m venv .venv
   source .venv/bin/activate
   ```

2. Install pinned development dependencies:

   ```bash
   python -m pip install -r requirements-dev.txt
   ```

3. Copy `.env.example` to `.env`, replace every placeholder, and export the
   values into the shell. Django deliberately does not read `.env` files by
   itself, which keeps secret loading explicit.

4. Create the configured PostgreSQL database, then run:

   ```bash
   python manage.py migrate
   python manage.py runserver
   ```

The development settings require `DJANGO_SECRET_KEY` and every `DB_*` value.
The production settings additionally require `DJANGO_ALLOWED_HOSTS`. Missing
mandatory values raise `ImproperlyConfigured` and name the missing variable.
SQLite is configured only by `config.settings.test`.

For local demonstrations only, set `DJANGO_ENV=development` and
`DJANGO_ALLOW_DEMO_SEED=true`, then create the reserved synthetic clinic and
its `clinic_admin`, `therapist`, and `patient` memberships with:

```bash
python manage.py seed_demo
```

The command is idempotent only for the exact records it previously created,
uses `example.test` identities with unusable passwords, creates no clinical
profiles or clinical records, and fails closed outside an explicitly opted-in
development runtime. Reserved-identity collisions abort without altering the
existing account.
See `docs/migration-policy.md` before creating or reviewing schema changes.

## Environment variables

- `DJANGO_SECRET_KEY`: mandatory secret key outside tests.
- `DJANGO_TIME_ZONE`: optional IANA timezone; defaults to
  `America/Sao_Paulo`.
- `DJANGO_ALLOWED_HOSTS`: comma-separated hosts; mandatory in production.
- `DJANGO_ALLOW_DEMO_SEED`: optional development-only opt-in; must be `true`
  together with `DJANGO_ENV=development` and `DEBUG=True` to run `seed_demo`.
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`: mandatory,
  explicit PostgreSQL connection values outside tests.
- `CACHE_LOCATION`: optional local-memory cache namespace.
- `MAILER_BACKEND`, `MAILER_HOST`, `MAILER_PORT`, `MAILER_USERNAME`,
  `MAILER_PASSWORD`, and `MAILER_USE_TLS`: optional e-mail transport settings.
- `DEFAULT_FROM_EMAIL`: optional default sender address.
- `PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND`: scanner command and fixed arguments
  used before an uploaded logo is persisted (for example,
  `clamdscan --no-summary`). The temporary file path is appended as the final
  argument. Uploads fail closed when the command is absent, unavailable,
  times out, or returns a nonzero status.
- `PRIVACY_REQUEST_DUE_DAYS`: operational deadline for data-subject requests;
  defaults to `15` days and does not replace legal review.
- `PRIVACY_REAUTH_MAX_AGE_SECONDS`: lifetime of a one-use server-side
  reauthentication proof; defaults to `600` seconds.
- `PRIVACY_EXPORT_TTL_SECONDS`: encrypted export and signed download-grant
  lifetime; defaults to `900` seconds.

Never commit `.env` or log secret, clinical, or user data. Data-subject request
operations are documented in `docs/privacy/data-subject-rights.md`; incident
response and restore exercises are documented in
`docs/security/incident-response-runbook.md`.

## Quality gates

Run the hermetic test and static-analysis suite from the repository root:

```bash
python -m pytest
ruff check .
ruff format --check .
mypy
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py check
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py makemigrations --check --dry-run
```

Production processes should load `config.settings.production`; ASGI and WSGI
use it by default. The test suite always selects `config.settings.test` through
`pyproject.toml`.
