"""Database-enforced same-tenant invariant across the content tree.

Content rows own a tenant (clinic). ContentVersion and ContentMedia rows must
always reference a Content row of the SAME tenant, and the tenant of a Content
row is immutable. This migration installs per-dialect triggers:

- PostgreSQL: plpgsql trigger functions + BEFORE INSERT/UPDATE triggers.
- SQLite: RAISE(ABORT) triggers (proven dialect-compatible).

All operations are reversible (drop trigger/function in reverse).
"""

from django.db import migrations

_PG_STATEMENTS = (
    """
    CREATE OR REPLACE FUNCTION content_assert_same_tenant() RETURNS trigger AS $$
    DECLARE
      parent_clinic UUID;
    BEGIN
      SELECT clinic_id INTO parent_clinic
        FROM content_content WHERE id = NEW.content_id;
      IF parent_clinic IS NULL OR parent_clinic <> NEW.clinic_id THEN
        RAISE EXCEPTION 'cross-tenant reference into content tree';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER content_contentversion_same_tenant
    BEFORE INSERT OR UPDATE OF content_id, clinic_id ON content_contentversion
    FOR EACH ROW EXECUTE FUNCTION content_assert_same_tenant()
    """,
    """
    CREATE TRIGGER content_contentmedia_same_tenant
    BEFORE INSERT OR UPDATE OF content_id, clinic_id ON content_contentmedia
    FOR EACH ROW EXECUTE FUNCTION content_assert_same_tenant()
    """,
    """
    CREATE OR REPLACE FUNCTION content_tenant_immutable() RETURNS trigger AS $$
    BEGIN
      IF OLD.clinic_id <> NEW.clinic_id THEN
        RAISE EXCEPTION 'content tenant is immutable';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER content_content_tenant_immutable
    BEFORE UPDATE ON content_content
    FOR EACH ROW EXECUTE FUNCTION content_tenant_immutable()
    """,
)

_PG_REVERSE = (
    "DROP TRIGGER IF EXISTS content_content_tenant_immutable ON content_content",
    "DROP FUNCTION IF EXISTS content_tenant_immutable()",
    "DROP TRIGGER IF EXISTS content_contentmedia_same_tenant ON content_contentmedia",
    "DROP TRIGGER IF EXISTS content_contentversion_same_tenant ON content_contentversion",
    "DROP FUNCTION IF EXISTS content_assert_same_tenant()",
)

_SQLITE_STATEMENTS = (
    """
    CREATE TRIGGER content_contentversion_same_tenant_ins
    BEFORE INSERT ON content_contentversion
    FOR EACH ROW
    BEGIN
      SELECT RAISE(ABORT, 'cross-tenant reference into content tree')
      WHERE NEW.clinic_id IS NOT
        (SELECT clinic_id FROM content_content WHERE id = NEW.content_id);
    END
    """,
    """
    CREATE TRIGGER content_contentversion_same_tenant_upd
    BEFORE UPDATE OF content_id, clinic_id ON content_contentversion
    FOR EACH ROW
    BEGIN
      SELECT RAISE(ABORT, 'cross-tenant reference into content tree')
      WHERE NEW.clinic_id IS NOT
        (SELECT clinic_id FROM content_content WHERE id = NEW.content_id);
    END
    """,
    """
    CREATE TRIGGER content_contentmedia_same_tenant_ins
    BEFORE INSERT ON content_contentmedia
    FOR EACH ROW
    BEGIN
      SELECT RAISE(ABORT, 'cross-tenant reference into content tree')
      WHERE NEW.clinic_id IS NOT
        (SELECT clinic_id FROM content_content WHERE id = NEW.content_id);
    END
    """,
    """
    CREATE TRIGGER content_contentmedia_same_tenant_upd
    BEFORE UPDATE OF content_id, clinic_id ON content_contentmedia
    FOR EACH ROW
    BEGIN
      SELECT RAISE(ABORT, 'cross-tenant reference into content tree')
      WHERE NEW.clinic_id IS NOT
        (SELECT clinic_id FROM content_content WHERE id = NEW.content_id);
    END
    """,
    """
    CREATE TRIGGER content_content_tenant_immutable
    BEFORE UPDATE ON content_content
    FOR EACH ROW
    WHEN OLD.clinic_id != NEW.clinic_id
    BEGIN
      SELECT RAISE(ABORT, 'content tenant is immutable');
    END
    """,
)

_SQLITE_REVERSE = (
    "DROP TRIGGER IF EXISTS content_content_tenant_immutable",
    "DROP TRIGGER IF EXISTS content_contentmedia_same_tenant_upd",
    "DROP TRIGGER IF EXISTS content_contentmedia_same_tenant_ins",
    "DROP TRIGGER IF EXISTS content_contentversion_same_tenant_upd",
    "DROP TRIGGER IF EXISTS content_contentversion_same_tenant_ins",
)


def _vendor(connection) -> str:  # type: ignore[no-untyped-def]
    return str(connection.vendor)


def apply_invariants(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    connection = schema_editor.connection
    if _vendor(connection) == "postgresql":
        for statement in _PG_STATEMENTS:
            schema_editor.execute(statement)
        return
    if _vendor(connection) == "sqlite":
        for statement in _SQLITE_STATEMENTS:
            schema_editor.execute(statement)
        return
    raise NotImplementedError(
        f"Same-tenant invariant triggers unsupported on vendor {_vendor(connection)}"
    )


def drop_invariants(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    connection = schema_editor.connection
    if _vendor(connection) == "postgresql":
        for statement in _PG_REVERSE:
            schema_editor.execute(statement)
        return
    if _vendor(connection) == "sqlite":
        for statement in _SQLITE_REVERSE:
            schema_editor.execute(statement)
        return
    raise NotImplementedError(
        f"Same-tenant invariant drop unsupported on vendor {_vendor(connection)}"
    )



class Migration(migrations.Migration):
    dependencies = [
        ("content", "0008_managed_taxonomy"),
    ]

    operations = [
        migrations.RunPython(apply_invariants, drop_invariants),
    ]