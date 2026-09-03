# Database migration policy

## Scope and naming

Django migrations are the only supported schema-evolution mechanism. Keep each migration
small enough to explain and roll back independently. Use a descriptive snake-case name,
such as `add_clinic_is_demo`, `name_persistence_indexes`, or
`add_clinic_slug_invariant`; never accept an opaque generated name without review.
Generated files must be deterministic and checked in with the model change they describe.

Prefer one concern per migration. Separate additive columns, index changes, constraints,
data movement, and destructive cleanup when doing so gives operators a meaningful stop or
rollback point. Use an expand/migrate/contract sequence when old and new application
versions may overlap.

## Review and rollout

Every migration requires review of generated operations and `migrate --plan`. Validate the
complete graph from an empty SQLite test database and an empty database on the supported
PostgreSQL major version. For constraints or indexes, read the resulting database catalog;
a successful command alone is insufficient evidence.

Before deploying a potentially blocking operation, assess table size, lock duration, and
whether PostgreSQL-specific non-atomic or concurrent operations are required. Backfill data
in bounded, idempotent batches rather than combining a large rewrite with a schema change.

## Destructive changes and rollback

Dropping or narrowing a column, table, constraint, or index; changing a type; rewriting
stored values; and irreversible `RunPython`/`RunSQL` operations require explicit reviewer
approval. Their review must include:

1. a backup or recovery point and a tested restore owner;
2. the forward data-preservation or backfill plan;
3. the application rollback order and compatibility window;
4. the migration rollback command or a documented forward-fix procedure; and
5. evidence from a production-shaped PostgreSQL rehearsal.

Do not describe every generated migration as reversible. Django marks some operations
irreversible, PostgreSQL cannot reconstruct discarded data, and a syntactically reversible
operation may still be operationally unsafe. Check `Migration.reversible`, inspect custom
reverse code, and test the actual rollback path before making a reversibility claim.

## Verification commands

Run these gates from the repository root:

```bash
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py makemigrations --check --dry-run
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py migrate --plan
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py migrate
```

The release report must record the settings module/database engine, migration plan, empty
database result, catalog evidence for relevant types/constraints/indexes, and any rollback
concern. Temporary PostgreSQL databases and containers must be removed after verification.
