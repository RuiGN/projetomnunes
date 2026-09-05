# Sprint 4 corrective-wave independent re-review

## Verdict: CHANGES REQUESTED — one Important issue, no Critical issues

The checkbox-group, raw patient/onboarding-control, and shell-grid corrections pass this review. One remaining in-scope dark-mode contrast issue prevents approval.

Repository: `/mnt/2c8d19a3-3bbb-4f90-b09f-9e17c780ce6a/Projects/projetomnunes`
Branch: `feat/duralux-mfa-migration`
HEAD: `237dbd26bf82028249b955fbf66c93b835076e50` (review concerns the dirty working tree, not just HEAD).

## Important finding

### I1 — Migrated patient/onboarding labels retain the light-theme body color in dark mode

**Locations:** `templates/components/duralux_field.html:7`; `static/duralux/css/product-integration.css:364-408`; `static/duralux/css/theme.min.css` (minified `body` rule).

The new shared field component emits a bare `<label>` rather than `.form-label`. The vendor theme explicitly sets `body { color: #6b7885; font-size: .84rem; }`. The product dark-mode rules set `--bs-body-color` on the theme root, but do not override that explicit body color. Their label correction at lines 379-381 only matches `.form-label`, so it misses these newly migrated labels. The paragraph correction at lines 406-408 likewise does not apply to labels. Django-generated checkbox/radio option labels also lack `.form-label` and should be included in the repair/verification scope.

**Observed evidence:** The parent supplied fresh browser computed colors for the dark patient form: label `rgb(107,120,133)` on card `rgb(33,37,41)`. Independent source inspection confirms the inheritance path above. Independent Python sRGB relative-luminance calculation returned **3.4161429778504315:1**, below the WCAG AA **4.5:1** requirement for ordinary small text. These are field labels, not disabled or decorative content.

**Impact:** Patients and staff with reduced vision cannot reliably read required field identification in the supported dark theme. This violates the PRD's WCAG 2.2 AA requirement in a migrated core form.

**Requested correction:** Apply a product-owned dark-mode foreground to the relevant body/form label inheritance chain, or explicitly style both standalone labels and Django option labels. Merely adding `.form-label` to the shared standalone label is not sufficient to cover generated option labels. Keep vendor assets untouched. Add a regression check that covers the actual migrated field markup, and verify computed label/background contrast in dark mode for patient creation and onboarding preferences. Retest light mode as well.

**Reproduction:** Enable dark mode; open the patient creation page; inspect the computed foreground of the `label[for="id_full_name"]` and background of its `.product-form-card`. Repeat with checkbox option labels in onboarding preferences. The parent browser evidence is attributed here; this reviewer did not independently open a browser.

## Corrections verified

- `core/templatetags/accessible_forms.py:15-28,58-65`: wrapper class replacement occurs after Django constructs option contexts. Options retain `form-check-input`; the outer group gets `d-grid gap-2`.
- Runtime MRO is `_DuraluxCheckboxGroup -> _DuraluxRadioGroup -> CheckboxSelectMultiple -> RadioSelect -> ChoiceWidget -> Widget -> object`. Consequently checkbox type, multiple selection, `getlist`, missing-value behavior, and omission of HTML `required` on each individual checkbox are preserved.
- An independent database-free rendering probe exercised unbound, multi-selected, and invalid forms with a prefix. It asserted checkbox/radio input types, selected-option counts, wrapper/input classes, prefixed IDs, error-summary destinations, existing help/error ARIA references, required semantics, and preservation of the original widget object. All assertions passed.
- `templates/components/duralux_field.html:2-12`, `templates/people/patient_form.html:11`, and `templates/onboarding/patient_onboarding.html:21,28`: migrated controls use the helper; fieldsets/legends and deterministic help/error IDs are present.
- `static/duralux/css/product-integration.css:102-105`: `.product-shell { display: block; }` overrides the equally specific earlier `.layout-vertical` grid rule in `static/css/workspace.css:38-40`. `templates/layouts/base.html:12-17` confirms the correct stylesheet order; `templates/layouts/vertical.html:5` carries both classes.
- Sprint 4 child templates no longer add nested main landmarks. `clinics/confirm_switch.html` correctly retains its own main because it directly extends the base rather than the workspace shell.
- Parent supplied fresh browser geometry evidence: desktop main width 995px at viewport 1280px, and no overflow at 320/375/768/1024/1280/1440 after waiting 700ms for inherited transitions. This is parent evidence, not an independently repeated visual audit.

## Executed verification

From the repository:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_duralux_form_regressions.py \
  tests/test_sprint4_duralux_templates.py \
  -o addopts='' -p no:cacheprovider -q
```

Actual result: `7 passed in 0.34s`, exit 0. Coverage and pytest cache writes were disabled to avoid interfering with the parent's full-suite run.

The separate in-memory Django rendering/MRO probe returned:

```text
MRO: _DuraluxCheckboxGroup -> _DuraluxRadioGroup -> CheckboxSelectMultiple -> RadioSelect -> ChoiceWidget -> Widget -> object
PASS: checkbox/radio types, multi-selection, wrapper/input classes, prefixed IDs, error-summary targets, help/error references, required semantics, original widget identity
PASS: getlist, missing-value, browser-required semantics
```

The contrast probe returned:

```text
CONTRAST 3.4161429778504315
```

## Scope and limitations

Reviewed Sprint 4 template changes, the corrective helper/component, CSS integration, chart initializer, relevant form definitions, and shell stylesheet/landmark integration. The existing global legacy bridge was treated as intentional transitional scope, not a new blocker. No repository files were edited, no full test suite was run, and no production services or secrets were accessed. Full-suite, lint/type gates, exhaustive tenant authorization checks, and browser/screen-reader acceptance remain the parent's responsibility. Passing these focused tests does not close every Sprint 4 PRD acceptance checkbox.

One search wrapper returned a JSON decoding error; its source search was successfully repeated using the direct search tool. No verification blocker remains other than finding I1.

## Reviewed corrective-file SHA-256 snapshot

```text
ca07e499eca1217bcf6632711d412cdcd1bc085ff950a59b782189e53ce9c59c  core/templatetags/accessible_forms.py
887bf87a662c6010fc89bcc024c36f7474c4ebe6392a624ee3a94a19823f3ff3  templates/components/duralux_field.html
b8f8c49a894d490b419b4c38d24c53c373bd39af0bf9cabdf51f2e74527f1eb2  templates/people/patient_form.html
93d4767724ca963de6d07c88e89dbc809774d3cde292a7f08754a617ca821fbb  templates/onboarding/patient_onboarding.html
744c30cc57cfd51f544436a0d55e31e1cf66ff9e2ac6884d04a5cf5af8de20a3  static/duralux/css/product-integration.css
07168b54a635fdbb6011b1dad6893ba6432d1b1461c02233196a3d89e97ceda6  tests/test_duralux_form_regressions.py
e9a2ac305c11f4ff33be928e18992385bdd1e1c2ab37826d1b2335d2651335f6  tests/test_sprint4_duralux_templates.py
```
