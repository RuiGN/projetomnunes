# Vertical and Detached Layouts Design

Date: 2026-08-31
Status: approved by PRD task 8.2.2

## Scope

Deliver reusable Django layout shells for authenticated clinic workspaces:
vertical navigation as the default and detached navigation as an alternative.
Both shells share the same semantic landmarks, routes, active item logic, clinic
context, and user identity.

## Server-first architecture

Essential navigation is ordinary HTML links and forms. Alpine.js 3.14.1 adds
progressive mobile-sidebar behavior only: open/close, Escape, overlay click,
focus return, and scroll locking. If JavaScript fails, the desktop navigation
and all destination links remain usable.

Templates:

- `layouts/base.html`: document, static assets, skip link, message/content blocks.
- `layouts/vertical.html`: fixed desktop sidebar and mobile drawer.
- `layouts/detached.html`: top-level detached surface with the same links.
- `layouts/partials/navigation.html`: one route list reused by both shells.
- `layouts/partials/header.html`: clinic context, user identity, mobile trigger.

The demonstration workspace routes render factual placeholder navigation only;
they do not introduce clinical metrics or patient data.

## Clinic selection

A selector returns only active clinics with a current membership for the actor.
Changing context uses a two-step server flow:

1. GET review page validates the requested clinic membership and names the
   source and destination clinics.
2. POST confirmation revalidates membership, updates `active_clinic_id` in the
   session, cycles the session key, and redirects to an allowlisted local path.

Malformed, inactive, cross-tenant, stale-actor, and stale-membership targets are
denied without confirming whether the clinic exists.

## Accessibility

- `header`, `nav`, `main`, breadcrumbs, skip link, and a single page `h1`.
- Mobile drawer has accessible name and state, closes with Escape and overlay,
  moves focus to its close button, and returns focus to the trigger.
- Body scroll is locked only while the drawer is open.
- Active links use `aria-current="page"`.
- 44 px minimum targets and visible focus are inherited or defined by semantic
  tokens.
- Both layouts remain usable at 360, 768, 1280, and 1536 px.

## Assets and privacy

Alpine.js 3.14.1 is vendored locally from its exact package distribution; no
CDN, analytics, identity, tenant ID, or sensitive preference is placed in local
storage. Clinic selection remains server-side in the session.

## Verification

TDD covers route/template reuse, access control, active navigation,
authorized clinic lists, two-step switching, session rotation, invalid targets,
semantic markup, Alpine behavior hooks, and demo-content absence. Browser checks
cover drawer interaction, Escape/focus behavior, no horizontal overflow, and
both layout widths.
