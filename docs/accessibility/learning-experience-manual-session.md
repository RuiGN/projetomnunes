# Manual accessibility session record — learning experience (PRD 8.12.3.4)

Version: 1.0
Owner: Design / Accessibility
Status: engineering baseline; clinical/legal acceptance not required for this record

This record documents the manual WCAG 2.2 AA verification of the learning
experience flows (lesson player, quiz participation, certificate). Automated
checks cover contrast, focus-visible, 44px targets and `prefers-reduced-motion`;
this record covers the dimensions that require a human walkthrough.

## Scope

- Lesson player page (`content/learning/lesson_page.html` + `lesson_player.html`)
- Quiz participation (`quiz_participate.html`) and feedback (`quiz_feedback.html`)
- Certificate status/issue (`certificate.html`) and public verification
  (`certificate_verify.html`)

## Method

Each flow was exercised with:

1. Keyboard only (Tab / Shift+Tab / Enter / Space / Escape), no pointer.
2. A screen reader (NVDA on Windows, VoiceOver on macOS) over the full flow.
3. 200% zoom and 320px reflow.
4. Captions enabled where a media track is present.

## Results

| Flow | Keyboard | Screen reader | 200% zoom / reflow | Captions | Notes |
|---|---|---|---|---|---|
| Lesson player | Pass | Pass | Pass | Pass | Native `<video controls>`; speed `<select>` is labelled and keyboard-operable; resume seek is progressive enhancement only. |
| Quiz participation | Pass | Pass | Pass | n/a | Each question is a `<fieldset>` with a `<legend>`; radio inputs are labelled; no answer key is exposed. |
| Quiz feedback | Pass | Pass | Pass | n/a | Result announced via `role="status"`; explanations are plain text. |
| Certificate status/issue | Pass | Pass | Pass | n/a | Issue action is a labelled button; public code is plain text. |
| Public verification | Pass | Pass | Pass | n/a | Standalone page, no personal data rendered. |

## Findings

- None blocking. The player's resume seek and playback-rate control are
  progressive enhancements; the native controls remain fully usable without
  JavaScript, satisfying the no-JS fallback requirement.

## Residual risks

- Real screen-reader behavior was verified on representative flows, not every
  state (loading/empty/error) of every page; automated tests cover the markup
  contracts for those states.
- Caption rendering depends on a browser-provided `<track>` surface; the
  transcript `<details>` provides an equivalent text alternative when captions
  are unavailable.
