# Sprint 12 fix wave — plan (drafted before round-2 verdicts)

Prepared while the five round-2 independent reviews run. Working tree stays
read-only until verdicts arrive; only verdict-confirmed findings get fixed.

## Round-1 findings already fixed (verified in code, awaiting re-review)

- sanitizer: `html.parser`-based allowlist (`content/services.py:_SafeHTMLParser`),
  decoded-scheme checks in `_sanitize_url`.
- media: MIME allowlist + magic validation + fail-closed malware scan
  (`attach_media`, `core/uploads.py`, `require_clean_malware_scan`).
- `PRIVATE_MEDIA_ROOT` exported by development/production settings.
- signed tenant-bound media grants (`media_playback_grant`, `PrivateDownloadGrant`).
- Important 1/2: `valid_until` persisted; `scheduled_for` enforced at publish.

## Still-open round-1 Important findings (design for fix wave)

### I3 — DB-enforced same-tenant invariant (Content/ContentVersion/ContentMedia)

Django 6.1 has no `CompositeForeignKey`. Project pattern (skill references):
DB-enforced invariants via trigger/migration, validated on empty SQLite AND
PostgreSQL 17 (docs/migration-policy.md). Plan:

1. RED test (`tests/test_content_regressions.py`): direct
   `ContentVersion.infrastructure_objects.create(clinic_id=<other>, content=<A>)`
   must raise `IntegrityError` (not merely service-level denial). Same for
   `ContentMedia`.
2. Migration `0006_content_same_tenant_invariant`: trigger `BEFORE INSERT OR
   UPDATE` on content_contentversion / content_contentmedia asserting
   `clinic_id = (SELECT clinic_id FROM content_content WHERE id = NEW.content_id)`
   (and media equivalent); trigger function shared per table; PostgreSQL
   native + SQLite `CREATE TRIGGER` (SQLite supports triggers; keep logic in
   plain SQL so both dialects can express it).
3. Validate `migrate --plan`, catalog inspection (pg triggers) on disposable
   PG 17 + empty SQLite; rollback tested.
4. Keep service-level `PermissionDenied` checks (defense in depth).

### I4 — tenant-filtered HTTP editorial layer

Project convention = Django views (no DRF anywhere). Plan:

1. `content/urls.py` + `content/views.py`, wired in `config/urls.py` at
   `/conteudo/`. Views: list, detail, create, version-create, submit-review,
   approve, publish, rollback, archive, media-attach, media-grant playback.
   All through `authorized_active_clinic` + admin role check
   (mirroring clinics/views.py pattern).
2. Templates in `templates/content/` using Sliced cards/forms, PT-BR strings,
   dark/light + keyboard a11y (per design-system skill rules).
3. Version comparison rendered in detail view (side-by-side current vs chosen
   version, server-side diff); editorial comments as append-only
   `ContentVersionComment` (tenant FK required, audited create).
4. Preview page rendering sanitized body for the latest/selected version.
5. RED HTTP tests (`tests/test_content_http.py`): admin happy path; therapist
   forbidden on editorial actions; cross-tenant id denied; anonymous → login;
   duplicate POST idempotency where applicable.

### I5 — managed taxonomy records

1. Models `ContentCategory`, `ContentTag` (tenant-scoped, unique per clinic),
   M2M from `Content`; migration `0007_content_taxonomy` (after 0006).
2. Services: create/attach during `start_content`/update; filter params on
   search; migration backfills existing scalar values into records.
3. RED tests: duplicate category per tenant rejected; search by category/tag;
   cross-tenant attach denied.

### I6 — cache invalidation on publish/rollback

1. Receiver on `content_published`/`content_archived` + explicit call in
   `rollback_content`: delete `published-content-count:<tenant>` and
   `published-content-ids:<tenant>:<filters-hash>` keys; also bump a
   per-tenant generation counter instead of enumerating filter hashes.
2. RED tests: warm cache → publish new content → stale result must not be
   served; rollback/archival likewise.

## Sequencing

Fix order: I3 → I6 → I5 → I4 (smallest blast radius first; HTTP layer last).
After wave: focused RED/GREEN, full gate (pytest+ruff+mypy+checks+migrations),
both-DB migration validation, then re-dispatch round-3 review ONLY for tasks
whose round-2 verdict is changes_requested. 8.12.2-8.12.5 stay untouched unless
their reviews request changes.