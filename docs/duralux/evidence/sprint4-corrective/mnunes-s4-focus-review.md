# Independent review — keyboard-focus specificity fix only

## Verdict: APPROVED (scoped)

No blocking finding in the focus-selector fix. This is not Sprint 4 approval, a full accessibility audit, or clearance of the full integration gate.

## Findings and source inspection

- `static/duralux/css/product-integration.css:22-26` correctly adds `.product-workspace-body :is(a, button, input, select, textarea, [tabindex]):focus-visible` to the existing rule, preserving its `3px solid var(--product-focus-ring)` outline and `2px` offset. The original low-specificity fallback remains intact.
- The added body class and specificity-bearing `:is()` make this selector stronger than `.form-check-input:focus`. The inspected Bootstrap rule in `static/duralux/css/bootstrap.min.css` explicitly sets `outline:0` without `!important`; the new selector overrides that reset. Retaining `:focus-visible` avoids indiscriminately forcing outlines for every pointer focus. No vendor file modification or `!important` escalation is needed.
- `templates/layouts/base.html:15-17,21` loads the integration CSS after vendor styles and applies `product-workspace-body` to the body, so workspace controls are within the selector's scope.
- The focus-color variable remains theme-aware (`product-integration.css:356-367`). The supplied recorded outline matches the dark-theme token.

## Verification

Independently executed, from the repository:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_sprint4_duralux_templates.py::test_keyboard_focus_outweighs_vendor_control_resets \
  -o addopts='' -p no:cacheprovider -q
```

Actual result: **1 passed in 0.11s**, exit 0.

Read `/tmp/mnunes-s4-evidence/focus.json`: `focused` is `id_enabled_modules_1`, `focusVisible` is `true`, and `outline` is `rgb(147, 197, 253) solid 3px`. This supports the corrected computed outline for the recorded checkbox. This is parent-supplied browser evidence, not a keyboard/browser session independently reproduced by this reviewer. The parent's reported RED run was not repeated.

Nonblocking coverage limitation: `tests/test_sprint4_duralux_templates.py:95-103` checks the selector's presence, not cascade behavior or outline declarations. It is a source-contract regression, complemented here by the supplied computed-style evidence; it should not be presented as a browser test. The evidence file does not establish every control, route, viewport, theme, or clipping condition.

## Boundaries

- Consulted `/tmp/mnunes-s4-final-review.md` only as prior context; no broader contrast or sprint claims are renewed here.
- No repository files edited, no full tests run, and no OAuth changes made. Only this requested report was created; the narrow test disabled bytecode and pytest-cache output.
- Full gates remain blocked by the unrelated known OAuth token parsing defect reported by the parent. That defect was neither investigated nor reproduced in this review.
