# Quality, testing, and observability

## Required local gates

Run from the repository root with the test settings explicitly selected:

```bash
export DJANGO_SETTINGS_MODULE=config.settings.test
ruff format --check .
ruff check .
mypy .
python manage.py check --database default
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python -m pytest --cov-fail-under=90
git diff --check
```

The CI workflow repeats these gates on Python 3.14 with PostgreSQL 17 and also
runs Django's production deployment checks. Requirements are exact-pinned in
`requirements.txt` and `requirements-dev.txt`.

## Test pyramid

- Unit tests cover pure policies, events, value validation, formatting, and
  request-correlation behavior.
- Database integration tests cover models, constraints, migrations, services,
  factories, health dependencies, and authorization.
- HTTP tests cover middleware order, tenant denial, safe errors, health probes,
  and request/response correlation.
- `tests/test_clinic_authorization.py` and `tests/test_tenant_middleware.py` are
  the dedicated multi-tenant isolation suite. Every tenant-owned feature must
  add negative tests for another clinic, missing membership, inactive state,
  stale actors, and direct identifier manipulation.

The minimum total branch-aware coverage is 90%. Coverage is a regression gate,
not evidence that authorization or privacy requirements are complete.

## Structured logging contract

Application logs are JSON and expose only an allowlist of operational fields:
`timestamp`, `level`, `logger`, `request_id`, `tenant_id`, pseudonymized
`actor_ref`, `event`, `outcome`, and optional `latency_ms`.

Never log request or response bodies, free-form clinical content, credentials,
cookies, session identifiers, authorization headers, raw tokens, documents,
health-probe dependency details, or exception text from external services.
Actor references are one-way SHA-256-derived labels and are not user IDs.

`RequestCorrelationMiddleware` must remain the first project middleware and
before `ClinicTenantMiddleware`. It validates bounded ASCII request IDs,
generates a UUID-derived replacement when needed, returns `X-Request-ID`, and
resets context-local state after every response or exception.

## Health and safe errors

- `/health/live/` verifies process responsiveness only and never touches the
  database or cache.
- `/health/ready/` verifies database and cache and returns only `ok` or
  `unavailable`; it never returns provider names, hosts, credentials, or
  exception details.
- `/health/` is the only non-admin tenant exemption. Health endpoints remain
  public so infrastructure can probe them; responses intentionally reveal no
  tenant or dependency detail.
- PT-BR error pages for 400, 403, 404, and 500 display the request reference but
  no stack trace or sensitive context.
