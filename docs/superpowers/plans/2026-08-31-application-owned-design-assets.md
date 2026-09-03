# Application-Owned Design Assets Implementation Plan

> **For agentic workers:** Execute inline with strict RED-GREEN verification. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all project dependency on the legacy design prototype directories while preserving the active UI.

**Architecture:** Promote the compiled framework stylesheet to an application-owned path under `static/css`, retain semantic tokens/fonts/JavaScript under the existing static tree, update templates and documentation, and delete legacy source directories. A repository contract prevents the dependency from returning.

**Tech Stack:** Django 6.1 staticfiles, pytest, Ruff, mypy.

## Global Constraints

- Frontend content remains PT-BR; technical code and documentation remain en-US.
- Demo HTML, logos, avatars, backgrounds, and sample data are not promoted.
- Existing uncommitted work must be preserved.
- No commit, push, or deploy.

---

### Task 1: Add the autonomy contract

**Files:**
- Modify: `tests/test_design_system.py`

- [X] Add a test that requires `static/css/framework.css`, rejects `static/vendor/sliced/main.css`, rejects both legacy directories, and rejects legacy Ruff/mypy exclusions.
- [X] Run the focused test and confirm it fails because the migration has not happened.

### Task 2: Promote application-owned assets

**Files:**
- Move: `static/vendor/sliced/main.css` to `static/css/framework.css`
- Move: `templates/design_system/reference.html` to `templates/visual_reference/reference.html`
- Modify: `templates/layouts/base.html`
- Modify: `tests/test_design_system.py`
- Modify: `pyproject.toml`

- [X] Update every active template and asset allowlist to the application-owned stylesheet path.
- [X] Remove obsolete quality-tool exclusions.
- [X] Run the focused tests and confirm they pass.

### Task 3: Remove legacy sources and rewrite active documentation

**Files:**
- Delete: `design_system/`
- Delete any additional legacy prototype directory if present.
- Modify: `PRD.md`
- Modify: `docs/superpowers/specs/2026-08-31-sliced-tokens-assets-design.md`
- Modify: `docs/superpowers/plans/2026-08-31-sliced-tokens-assets.md`

- [X] Rewrite the visual source of truth around application-owned static assets.
- [X] Remove legacy source directories.
- [X] Re-run the autonomy contract.

### Task 4: Verify the repository

- [X] Run focused design/layout tests.
- [X] Run Ruff check and Ruff format check.
- [X] Run strict mypy.
- [X] Run Django checks, migration drift/plan, and collectstatic.
- [X] Run the full test suite with coverage.
- [X] Run `git diff --check` and inspect the final diff.
- [X] Update the PRD checklist only where fresh evidence supports completion.
