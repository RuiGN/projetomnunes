# Pre-migration visual baseline

This directory records the legacy visual state before the Duralux migration. The screenshots are comparison evidence, not approved target designs.

## Coverage

| Journey | Desktop evidence | Mobile evidence |
|---|---|---|
| Login | `desktop/login.png` | `mobile/login.png` |
| MFA enrollment | `desktop/mfa-enroll.png` | `mobile/mfa-enroll.png` |
| Workspace and dashboards | `desktop/workspace.png`, `desktop/admin-workspace.png`, `desktop/analytics*.png` | `mobile/workspace.png`, `mobile/admin-workspace.png`, `mobile/analytics*.png` |
| Patient experience | `desktop/analytics-patient.png`, `desktop/onboarding-patient.png` | `mobile/analytics-patient.png`, `mobile/onboarding-patient.png` |
| Scheduling | `desktop/scheduling.png` | `mobile/scheduling.png` |
| Journal | `desktop/journal.png`, `desktop/journal-admin.png`, `desktop/journal-patient-denied.png` | `mobile/journal.png`, `mobile/journal-admin.png` |
| Goals | `desktop/goals.png` | `mobile/goals.png` |
| Content | `desktop/content.png` | `mobile/content.png` |
| Finance | `desktop/finance.png`, `desktop/finance-admin.png` | `mobile/finance-admin.png`, `mobile/finance-patient-denied.png` |
| Errors | `desktop/error-{400,403,404,500}.png` | `mobile/error-{400,403,404,500}.png` |

The error captures use the current error-template markup with deterministic baseline request references. No exception details or protected data are present.

## Review notes

- Login, MFA enrollment, workspace, and scheduling samples were visually inspected in both desktop and mobile evidence.
- The legacy mobile scheduling capture exposes a navigation overlay that obscures and clips the page content. This is a recorded legacy defect, not a Duralux behavior to preserve.
- The current error pages are unstyled browser-default documents. Their sparse appearance is intentional baseline evidence for Sprint 3 migration.
- Screenshots may contain synthetic local-development records only. They must not be promoted as Duralux demo data or production fixtures.
