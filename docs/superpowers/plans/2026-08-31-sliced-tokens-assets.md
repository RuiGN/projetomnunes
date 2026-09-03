# Sliced Tokens and Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver PRD task 8.2.1 with local Sliced assets, application-owned semantic tokens, and an authorized PT-BR reference page.

**Architecture:** Keep the checked-in Sliced bundle as an immutable vendor layer and add a small semantic CSS layer owned by the application. Expose the inventory through a Django template protected by authentication, staff authorization, and normal tenant resolution.

**Tech Stack:** Django 6.1, Python 3.14, compiled Sliced/Tailwind CSS, local Cerebri Sans, local Remix Icon, pytest.

## Global Constraints

- Frontend text is PT-BR; backend identifiers and technical documentation are en-US.
- Do not serve vendor demo HTML, logos, backgrounds, avatars, or demonstration data.
- Preserve light/dark variants, visible AA focus, non-color state labels, and keyboard-readable markup.
- Use TDD and mark `PRD.md` only after the full verification gate passes.

---

### Task 1: Contract tests for visual assets

**Files:**
- Create: `tests/test_design_system.py`
- Test: `tests/test_design_system.py`

**Interfaces:**
- Consumes: Django static finders and test client.
- Produces: executable contracts for token names, local assets, access control, tenant scope, and PT-BR markup.

- [ ] **Step 1: Write failing tests**

Assert semantic token values and dark variants, four Cerebri Sans weights with `font-display: swap`, local Remix Icon files, authenticated staff access with active clinic context, and absence of Sliced demo identity.

- [ ] **Step 2: Verify RED**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test python -m pytest tests/test_design_system.py -q`
Expected: FAIL because static assets, route, and template do not exist.

### Task 2: Vendor asset boundary and semantic tokens

**Files:**
- Create: `static/css/framework.css`
- Create: `static/css/tokens.css`
- Create: `static/fonts/cerebrisans-{regular,medium,semibold,bold}.woff`
- Create: `static/fonts/remixicon.{woff,woff2,ttf}`

**Interfaces:**
- Consumes: the approved, application-owned visual asset inventory.
- Produces: local static URLs and stable `--color-*` application variables.

- [ ] **Step 1: Copy only allowlisted vendor assets**

Copy compiled CSS and font files; do not copy vendor HTML, logos, images, or avatars.

- [ ] **Step 2: Add semantic CSS**

Define `@font-face`, light/dark variables, typography, visible focus, swatches, and accessible reference helpers.

- [ ] **Step 3: Run static contract tests**

Run the focused pytest file and expect only endpoint/template tests to remain failing.

### Task 3: Authorized reference page

**Files:**
- Modify: `config/views.py`
- Modify: `config/urls.py`
- Create: `templates/visual_reference/reference.html`

**Interfaces:**
- Consumes: authenticated request, `request.clinic`, Django static tags.
- Produces: `design_system_reference(request) -> HttpResponse` at `/design-system/`.

- [ ] **Step 1: Implement access policy**

Require login, staff status, and normal active tenant middleware. Return 403 for authenticated non-staff users without revealing additional information.

- [ ] **Step 2: Build PT-BR semantic inventory**

Render colors, typography, icon accessibility patterns, light/dark surfaces, and contrast/state guidance without vendor demo text.

- [ ] **Step 3: Verify GREEN**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test python -m pytest tests/test_design_system.py -q`
Expected: all focused tests pass.

### Task 4: Full verification and backlog update

**Files:**
- Create: `.superpowers/sdd/task-8.2.1-report.md`
- Modify: `PRD.md`
- Modify: `.superpowers/sdd/progress.md`

**Interfaces:**
- Consumes: verified code and test results.
- Produces: evidence and accurate checklist state.

- [ ] **Step 1: Run full gates**

Run Ruff check/format, mypy, full pytest with coverage >=90%, Django check, migration drift/plan, static discovery, and `git diff --check`.

- [ ] **Step 2: Review scope and security**

Confirm no unauthorized route access, no vendor demo assets in static output, no external font/icon dependency, and no untranslated user-facing copy.

- [ ] **Step 3: Update evidence and PRD**

Record RED/GREEN/gate evidence, mark 8.2.1.1–8.2.1.4 and parent 8.2.1 only if every check passes.

## Self-review

The plan covers every 8.2.1 subtask, contains no placeholder implementation, keeps later Sprint 2 layout/form/chart work out of scope, and names the exact interfaces and verification commands used by later steps.
