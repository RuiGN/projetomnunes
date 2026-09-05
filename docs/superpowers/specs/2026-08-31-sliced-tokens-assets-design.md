# Sliced Tokens and Assets Design

Date: 2026-08-31
Status: superseded by the Duralux migration; retained as historical context
Scope: PRD task 8.2.1 only

## Purpose

Maintain the selected Sliced-derived artifacts as a stable, application-owned,
accessible visual foundation without shipping the vendor demonstration page,
example identity, or user image.

## Approaches considered

1. Recommended — application-owned framework layer plus semantic tokens. Keep
   only the compiled stylesheet and required Cerebri Sans/Remix Icon font files
   in Django static storage. Add a small application-owned token stylesheet and
   a staff-only reference page. This preserves fidelity while creating a clear
   customization boundary.
2. Keep a prototype source tree. This duplicates assets and allows runtime and
   documentation to drift toward an obsolete source.
3. Rebuild the compiled stylesheet from reconstructed Tailwind sources. No
   authoritative upstream toolchain is available, so reconstruction would be
   lossy and would invent a second source of truth.

Approach 1 is selected.

## Visual direction

The interface remains recognizably Sliced: Cerebri Sans, compact administrative
rhythm, violet primary action, white/light surfaces, and restrained dark
surfaces. The therapeutic adaptation spends its visual emphasis on clarity of
state rather than decorative novelty.

Named application tokens:

- Brand violet: `#6A69F5`
- Success: `#50CD89`
- Warning: `#FFC700`
- Danger: `#F1416C`
- Information: `#009EF7`
- Text: `#151515`
- Muted text: `#94989A`
- Canvas: `#F9FBFD`
- Surface: `#FFFFFF`
- Dark canvas: `#151515`
- Dark surface: `#1F1F1F`
- Dark border: `#323A46`

Color is never the sole state carrier. Reference examples pair swatches with a
name, text description, and visible value.

## Typography and iconography

Cerebri Sans is local-only in 400, 500, 600, and 700 weights with `font-display:
swap` and a system sans-serif fallback. Remix Icon is local-only. The icon
catalog demonstrates decorative icons with `aria-hidden="true"` and meaningful
icons with a PT-BR accessible name. Ambiguous icon-only actions are prohibited.

## Architecture

- `static/css/framework.css`: application-owned compiled utility CSS.
- `static/fonts/`: only Cerebri Sans and Remix Icon font files required by CSS.
- `static/css/tokens.css`: application-owned semantic custom properties, dark
  variants, focus treatment, typography utilities, and reference-page helpers.
- `templates/visual_reference/reference.html`: staff-only PT-BR visual inventory.
- `config/views.py` and `config/urls.py`: tenant-scoped, staff-only reference
  endpoint; it receives no tenant exemption.

The compiled framework CSS changes only through an explicit migration. Future
clinic branding overrides semantic variables, never compiled utilities or
translated labels.

## Access and errors

The reference endpoint requires an authenticated staff user and the normal active
clinic resolution. Anonymous users are redirected to the admin login; staff
without a clinic context receive the existing safe tenant-selection response.
No demo identity, vendor logo, or sample patient information appears.

## Verification

Tests assert exact token values and variants, font files/weights, local icon
assets, staff-only access, tenant enforcement, PT-BR content, accessible icon
examples, contrast metadata, and absence of known vendor/demo labels. Existing
Ruff, mypy, Django, architecture, migration, and full-suite gates remain green.

## Self-review

No placeholders remain. Scope is limited to task 8.2.1; layouts, theme persistence,
forms, tables, Alpine interactions, and ApexCharts remain in later Sprint 2 tasks.
