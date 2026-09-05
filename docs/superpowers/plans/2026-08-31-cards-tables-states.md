# Cards, Tables, and Content States Implementation Plan

Status: superseded by the Duralux migration; retained as historical context

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver PRD task 8.2.3 with reusable, accessible, server-rendered cards, responsive tables, pagination, and content states.

**Architecture:** Add explicit-context Django partials under `templates/components/` and keep authorization, ordering, filtering, pagination, masking, and formatting in views. Demonstrate all variants in the staff-only tenant-scoped visual reference and exercise representative components in both authenticated workspace layouts.

**Tech Stack:** Django 6.1 templates and paginator, Python 3.14, application-owned Sliced CSS tokens, pytest, PostgreSQL 17.

## Global Constraints

- User-facing copy is PT-BR; backend code, identifiers, and contracts are en-US.
- Components receive presentation primitives, not unrestricted model instances or clinical free text.
- Every workspace/reference request remains authenticated and tenant-scoped.
- User content remains escaped; no `safe`, dynamic template path, or raw HTML input.
- Sorting and filtering are server-side and allowlisted; pagination preserves only recognized query parameters.
- Mobile tables have equivalent row cards and no horizontal-scroll dependency.
- TDD precedes implementation; `PRD.md` is marked only after full verification.
- No commit, push, or deploy without explicit user instruction.

---

### Task 1: Define component rendering contracts

**Files:**
- Create: `tests/test_content_components.py`
- Create: `templates/components/summary_card.html`
- Create: `templates/components/content_state.html`

**Interfaces:**
- Summary card consumes `card` with `title`, `description`, `value`, `trend_label`, `tone`, and optional `action` (`label`, `url`).
- Content state consumes `state` with `kind`, `title`, `message`, optional `action`, and `announce` boolean.
- Both partials render escaped primitives and use only allowlisted CSS classes selected through template conditionals.

- [ ] **Step 1: Write failing card tests**

Add tests that render `components/summary_card.html` through `django.template.loader.render_to_string` and assert:

```python
assert '<article class="summary-card tone-info"' in content
assert '<h2 id="summary-active-title">Cadastros ativos</h2>' in content
assert '<data value="12">12</data>' in content
assert 'aria-label="Tendência: 2 novos no período"' in content
assert '&lt;script&gt;' in escaped_content
assert '<script>' not in escaped_content
```

Run: `python -m pytest tests/test_content_components.py -k summary_card -q`
Expected: FAIL because the template does not exist.

- [ ] **Step 2: Implement the summary card partial**

Create semantic article markup with a deterministic title ID supplied in `card.id`, a `data` element for `card.raw_value`, optional description/trend/action, and conditional tone classes for `neutral|info|success|warning|danger`.

Run: `python -m pytest tests/test_content_components.py -k summary_card -q`
Expected: PASS.

- [ ] **Step 3: Write failing state tests**

Parametrize `loading|empty|no_results|unavailable|error|restricted` and assert the PT-BR title/message, `aria-live="polite"` only when `announce=True`, decorative icon `aria-hidden="true"`, and restricted copy that does not name or confirm a resource.

Run: `python -m pytest tests/test_content_components.py -k content_state -q`
Expected: FAIL because the state partial does not exist.

- [ ] **Step 4: Implement the content state partial**

Render a `<section class="content-state state-...">` with allowlisted kind classes, optional `role="status" aria-live="polite"`, escaped title/message, and an ordinary safe action link.

Run: `python -m pytest tests/test_content_components.py -k content_state -q`
Expected: PASS.

### Task 2: Build responsive table and server pagination

**Files:**
- Modify: `tests/test_content_components.py`
- Create: `templates/components/responsive_table.html`
- Create: `templates/components/pagination.html`
- Create: `core/presentation.py`
- Modify: `tests/test_domain_architecture.py` only if import boundaries require explicit allowance.

**Interfaces:**
- `build_query_url(query: Mapping[str, str], *, overrides: Mapping[str, str], allowed_keys: Collection[str]) -> str` returns an encoded local query string containing only allowlisted keys.
- Table consumes `table.id`, `caption`, `columns`, and `rows`. A column has `key`, `label`, optional `order_url`, and `aria_sort`. A row has `id`, `cells` in stable column order, and optional actions.
- Pagination consumes `pagination.current_label`, `page_count`, and precomputed destinations (`first`, `previous`, `pages`, `next`, `last`).

- [ ] **Step 1: Write failing query URL tests**

```python
result = build_query_url(
    {"q": "Horizonte", "order": "name", "token": "secret"},
    overrides={"page": "2"},
    allowed_keys={"q", "order", "page"},
)
assert result == "?order=name&page=2&q=Horizonte"
assert "token" not in result
```

Also cover blank values, Unicode, replacement of an existing key, and deterministic ordering.

Run: `python -m pytest tests/test_content_components.py -k query_url -q`
Expected: FAIL because `core.presentation` does not exist.

- [ ] **Step 2: Implement `build_query_url`**

Use `urllib.parse.urlencode`, copy only allowlisted nonblank scalar values, apply only allowlisted overrides, sort keys, and return an empty string when no parameters remain.

Run: `python -m pytest tests/test_content_components.py -k query_url -q`
Expected: PASS.

- [ ] **Step 3: Write failing responsive table tests**

Assert native `table`, nonempty `caption`, `scope="col"`, first-cell `scope="row"`, active `aria-sort`, escaped cell values, text-equivalent row actions, and a mobile card list hidden with CSS while the desktop table is visible. Assert the responsive CSS exposes exactly one representation at each breakpoint without static `aria-hidden` attributes that would incorrectly hide the active mobile representation.

Run: `python -m pytest tests/test_content_components.py -k responsive_table -q`
Expected: FAIL because the template does not exist.

- [ ] **Step 4: Implement the responsive table partial**

Loop over stable columns and each row's ordered cells. Render desktop native table and mobile `<article>` rows with `<dl>` label/value pairs. Keep actions as escaped labels and precomputed local URLs.

Run: `python -m pytest tests/test_content_components.py -k responsive_table -q`
Expected: PASS.

- [ ] **Step 5: Write failing pagination tests**

Cover single page, first page, middle page, last page, numbered links, `aria-current="page"`, unavailable destination suppression, and preservation of allowed query parameters through precomputed URLs.

Run: `python -m pytest tests/test_content_components.py -k pagination -q`
Expected: FAIL because the partial does not exist.

- [ ] **Step 6: Implement pagination partial**

Render `<nav aria-label="Paginação">`, status text “Página X de Y”, available boundary links, and numbered links. Current page is text with `aria-current="page"`, not a self-link.

Run: `python -m pytest tests/test_content_components.py -k pagination -q`
Expected: PASS.

### Task 3: Integrate synthetic examples into authorized views

**Files:**
- Modify: `config/views.py`
- Modify: `templates/visual_reference/reference.html`
- Modify: `templates/workspace/home.html`
- Modify: `tests/test_content_components.py`
- Modify: `tests/test_layouts.py`

**Interfaces:**
- Add private `config.views._component_examples(request: HttpRequest) -> dict[str, object]` returning only synthetic presentation dictionaries and paginator URLs.
- Existing `design_system_reference`, `workspace_vertical`, and `workspace_detached` route signatures remain unchanged.

- [ ] **Step 1: Write failing integration tests**

Assert the staff reference renders every card tone, every state kind, populated/empty tables, and pagination boundaries. Assert both workspace routes render representative operational cards/table, current clinic name, no patient names, no clinical copy, no forbidden demo-template names, and escaped query input.

Run: `python -m pytest tests/test_content_components.py tests/test_layouts.py -q`
Expected: FAIL because example context and includes are absent.

- [ ] **Step 2: Implement synthetic presentation context**

Use fixed PT-BR operational labels such as “Módulos disponíveis”, “Configurações pendentes”, and “Atividades da plataforma”. Accept `q`, `order`, and `page`; allowlist `order` to `name|-name|status|-status`; filter only the fixed synthetic rows; paginate with Django `Paginator`; and generate links through `build_query_url`.

- [ ] **Step 3: Include components with explicit context**

Use `{% include "components/..." with ... only %}` in the visual reference and workspace. Do not pass `request`, model objects, or unrestricted context to component partials.

Run: `python -m pytest tests/test_content_components.py tests/test_layouts.py -q`
Expected: PASS.

### Task 4: Add component CSS, responsive alternatives, and guidance

**Files:**
- Modify: `static/css/workspace.css`
- Modify: `static/css/tokens.css` only if an existing semantic token is insufficient.
- Modify: `tests/test_content_components.py`
- Modify: `templates/visual_reference/reference.html`

**Interfaces:**
- Produces `.summary-card`, `.content-state`, `.responsive-table`, `.mobile-row-list`, and `.pagination` styling contracts.
- At widths above 700 px, native table is accessible and mobile cards are `display:none`.
- At widths at or below 700 px, table wrapper is `display:none` and mobile cards are displayed; content is not duplicated in the accessibility tree because CSS `display:none` removes the inactive representation.

- [ ] **Step 1: Write failing CSS contract tests**

Assert 44 px action targets, visible focus inherited from tokens, semantic tone classes with text/icon support, mobile breakpoint behavior, no forced table horizontal overflow, reduced-motion handling, and dark-theme token usage rather than fixed light-only backgrounds.

Run: `python -m pytest tests/test_content_components.py -k css -q`
Expected: FAIL because component CSS is absent.

- [ ] **Step 2: Implement component styles**

Add grid layouts, subtle borders, 14 px surfaces, restrained tone accents, readable table spacing, focus-safe links, mobile row cards, state layouts, and pagination wrapping. Use semantic CSS variables and preserve 320 px minimum support.

- [ ] **Step 3: Add formatting and privacy guidance**

Document in the reference page that dates show effective timezone, truncation retains a full accessible value or detail route, personal identifiers are masked before rendering, and missing/unavailable/zero are distinct.

Run: `python -m pytest tests/test_content_components.py -q`
Expected: PASS.

### Task 5: Full verification and PRD update

**Files:**
- Modify: `PRD.md` only after every gate passes.

**Interfaces:**
- No new runtime interface; produces verification evidence for 8.2.3.1–8.2.3.4.

- [ ] **Step 1: Run focused and full gates**

Run with PostgreSQL 17 test settings:

```bash
ruff format --check .
ruff check .
mypy .
node --check static/js/workspace-navigation.js
python -m pytest --cov-fail-under=90
python manage.py check --database default
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
git diff --check
```

Expected: all commands exit 0, all tests pass, coverage is at least 90%, and no migration drift exists.

- [ ] **Step 2: Review requirements and mark PRD**

Confirm each 8.2.3 criterion against tests and rendered contracts. Change only 8.2.3 and 8.2.3.1–8.2.3.4 from `[ ]` to `[X]` after proof.

- [ ] **Step 3: Re-run final gates after PRD update**

Repeat the complete gate command and inspect `git status --short`. Do not commit, push, or deploy.

## Self-review

- Spec coverage: cards, tables, pagination, all states, density/truncation/date/timezone/masking guidance, internal catalog, workspace integration, accessibility, themes, and responsive widths are assigned to concrete tasks.
- Placeholder scan: no deferred implementation markers or undefined follow-up work remain.
- Type consistency: `build_query_url`, component dictionaries, private context builder, CSS class names, and template paths are defined before their consumers.
