# Sprint 4 final independent re-review — I1 only

## Scoped verdict: APPROVED — I1 closed

No remaining blocking finding in the reviewed inherited-label contrast fix. **This is not approval of all Sprint 4 acceptance criteria or the full integration gate.** Previous corrections remain recorded in `/tmp/mnunes-s4-rereview.md`; they were not exhaustively re-audited here.

## Source review

- `static/duralux/css/product-integration.css:107-110` now sets `color: var(--bs-body-color)` on `.product-workspace-body`. This overrides the vendor body's explicit light-theme foreground and repairs the inheritance chain for both bare component labels and Django-generated option labels, rather than covering only `.form-label`.
- `templates/layouts/base.html:15-17,21` loads product CSS after Bootstrap/vendor CSS and applies this class to the body. The existing dark-theme variable at `product-integration.css:365-368` supplies `#e2e8f0`; light mode continues to use Bootstrap's theme foreground.
- `tests/test_sprint4_duralux_templates.py:95-101` adds a source-contract regression for the inherited foreground declaration. It is not a browser/computed-style test; the supplied browser evidence complements it. The parent's reported RED run was not independently repeated or reproduced by modifying files.

## Independently executed verification

Repository: `/mnt/2c8d19a3-3bbb-4f90-b09f-9e17c780ce6a/Projects/projetomnunes`.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_duralux_form_regressions.py \
  tests/test_sprint4_duralux_templates.py \
  -o addopts='' -p no:cacheprovider -q
```

Actual result: **8 passed in 0.81s**, exit 0. No full suite was run.

Independently parsed `/tmp/mnunes-s4-evidence/contrast.json`, verified 12 unique entries exactly cover the three evidence targets × two themes × widths 375/1280, and calculated WCAG sRGB contrast from the recorded foreground/background values:

| Theme | Label | Background | Contrast |
|---|---|---|---|
| Dark | `rgb(226, 232, 240)` | `rgb(33, 37, 41)` | 12.513398012633212:1 |
| Light | `rgb(33, 37, 41)` | `rgb(255, 255, 255)` | 15.426285095510266:1 |

Every recorded pairing exceeds ordinary-text AA's 4.5:1 threshold; every recorded overflow flag is false.

**Evidence provenance:** These are parent-supplied browser measurements, not a fresh browser session performed by this reviewer. `patient-form` is identified by the parent as a real route snapshot. `onboarding-preferences-widget-fixture` and `clinic-modules-widget-fixture` are explicitly widget-only fixtures, not proof of their complete authenticated routes. The evidence supports closure of the specific inherited-label defect, not exhaustive route acceptance.

## Open gates and limitations

- Exhaustive route/browser checks and screen-reader acceptance remain pending.
- The full gate remains blocked: the parent reports an unrelated existing OAuth token parsing defect in `integrations/calendars.py:68`, where `rsplit` on a separator inside a raw digest rejected 12/100 fresh tokens. That finding was not independently reproduced here, is outside this layout review, and was not fixed.
- No production access, repository edits, staging, commits, or full-suite execution occurred. Focused tests disabled bytecode and pytest-cache output. Only this requested report was created.
- The reviewed CSS/test files are untracked in the current working tree, so ordinary and cached Git diffs were empty for them; review used their actual on-disk contents. An ambiguous skill lookup was resolved by using its categorized path; it did not block verification.
