# Cards, Tables, and Content States Design

Date: 2026-08-31
Status: superseded by the Duralux migration; retained as historical context

## Scope

Deliver reusable, server-rendered Django components for summary cards, responsive data tables, pagination, and content states. Demonstrate the complete component set in the internal visual reference and use representative components in the authenticated workspace. All examples use synthetic operational content without patient, clinical, or personally identifying data.

## Architecture

Components are Django partial templates under `templates/components/`. Callers pass explicit presentation data with `{% include ... only %}` so components do not depend on hidden view context or perform authorization decisions. Views remain responsible for tenant authorization, filtering, ordering, pagination, date conversion, and masking before rendering.

The component layer contains no clinical interpretation and does not calculate trends. It renders factual labels and values already authorized by the backend.

## Components

### Summary card

The base card accepts an accessible title, optional description, primary value, optional factual trend, contextual action, and semantic tone. Trends always include text and never depend on color or icon alone. The component supports compact and standard density without accepting arbitrary template names or untrusted HTML.

### Responsive table

The table uses native `table`, `caption`, `thead`, `tbody`, `th`, and `scope` semantics on desktop. At mobile widths, each row has an equivalent card representation with the same fields and actions in the same reading order. The server supplies stable column definitions and preformatted cell values; user content remains escaped by Django.

Sortable headers are links generated from allowlisted server ordering keys. Active ordering uses `aria-sort`. Filters use GET forms and preserve compatible query parameters. Row actions are ordinary links or forms conditioned by backend authorization.

### Pagination

Pagination is server-driven and exposes first, previous, numbered, next, and last destinations when applicable. It announces the current page and total page count, preserves allowlisted filters and ordering, and does not create links for unavailable destinations.

### Content states

A single state component supports:

- loading;
- empty collection;
- no filter results;
- temporarily unavailable;
- recoverable error;
- restricted access.

Each state has a concise PT-BR title, explanation, optional safe action, icon hidden from assistive technology, and an appropriate live-region contract only when the state can change dynamically. Restricted access never confirms whether a protected resource exists.

## Visual direction

The components extend the existing Sliced-derived token layer and Cerebri Sans typography. Surfaces remain quiet and operational: subtle borders, consistent 14 px radii, clear hierarchy, and the existing purple brand color reserved for primary actions and focus. Status colors supplement text rather than carrying meaning alone.

Cards use a restrained top-edge accent only when a semantic tone is present. Tables prioritize legibility over decoration, with a sticky-capable header, generous row targets, and reduced density only on wide screens. The mobile card alternative avoids horizontal scrolling.

## Formatting and privacy

- Dates are formatted in PT-BR and include the effective timezone in surrounding context when ambiguity is possible.
- Long values use visual truncation only when the full escaped value remains available through an accessible title or dedicated detail route.
- Personal identifiers are masked by backend formatters before reaching components.
- Components do not receive raw clinical notes, secrets, tokens, or unrestricted model instances.
- Empty totals, missing data, and unavailable data are distinct states and never silently converted to zero.

## Accessibility

- Native landmarks and table semantics remain the primary contract.
- Captions identify each table purpose.
- Header relationships use `scope="col"`; row headers use `scope="row"` where applicable.
- Active sorting uses `aria-sort` and a textual action label.
- Focus remains visible, targets meet the 44 px baseline, and actions have unambiguous names.
- Mobile row cards preserve source order and do not duplicate accessible content at the same viewport.
- Loading announcements avoid repeated or aggressive live-region output.
- Components support light/dark themes, reduced motion, keyboard navigation, and 320/360/768/1280/1536 px widths.

## Demonstration

The internal visual reference shows every card variation, the table in populated and empty forms, pagination boundaries, all content states, and formatting guidance. The workspace uses a small set of synthetic operational summaries and a demonstration list so integration is exercised without introducing Sprint 5 domain behavior.

## Testing

TDD covers:

- explicit component context and escaped output;
- card semantics and text equivalents for tone/trend;
- native table relationships, caption, allowlisted ordering, filters, and row actions;
- mobile equivalent content without inaccessible duplication;
- pagination boundaries and query preservation;
- every content state and safe restricted-access language;
- PT-BR copy, date/timezone guidance, masking guidance, and demo-data restrictions;
- rendering in vertical and detached layouts;
- responsive CSS contracts and theme token usage.

Full verification includes Ruff, mypy, JavaScript syntax, pytest with coverage at least 90%, Django checks, migration drift/plan, PostgreSQL tests, and `git diff --check`.

## Out of scope

- Domain-specific patient lists or clinical metrics.
- Client-side sorting, filtering, or pagination.
- Persistent user density preferences, which remain in task 8.2.5.
- Form components and validation behavior, which remain in task 8.2.4.
- Chart components, which remain in task 8.2.5.
