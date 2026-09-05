# Application-Owned Design Assets

Date: 2026-08-31
Status: superseded by the Duralux migration; retained as historical context

## Goal

Make the Django repository self-contained so runtime, tests, quality tools, and product documentation do not require legacy prototype directories.

## Architecture

The application-owned static tree is the only runtime source of visual assets. The compiled utility stylesheet lives at `static/css/framework.css`; semantic tokens and font declarations live at `static/css/tokens.css`; behavior lives at `static/js/`; and local fonts live at `static/fonts/`. Templates resolve every asset through Django staticfiles.

The internal `/design-system/` reference page remains because it documents the product's active visual language; it is not a dependency on a prototype directory.

## Migration rules

- Preserve the already promoted CSS and font bytes; do not rebuild them from a missing upstream toolchain.
- Remove vendor/prototype path names from active runtime paths and quality-tool configuration.
- Remove both legacy prototype directories after tests prove the application-owned copies exist.
- Rewrite the PRD so application-owned assets are the visual source of truth.
- Keep historical provenance in technical documentation without instructing developers to read a removed path.
- Do not copy demo HTML, logos, avatars, backgrounds, or sample data into application static storage.
- Do not commit, push, or deploy.

## Verification

Automated contracts must assert that legacy prototype directories are absent, the application-owned framework stylesheet is present and discoverable, active templates use it, and Ruff/mypy no longer exclude a legacy source tree. Focused tests, the full test suite with coverage, Ruff, Ruff format, strict mypy, Django checks, migration checks, static collection, and `git diff --check` must pass before the PRD records completion.
