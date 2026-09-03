# Domain architecture

## Purpose

The application is a modular Django monolith. Each top-level domain package owns its
language, future persistence, use cases, reads, authorization decisions, and events.
HTTP delivery and infrastructure must call these public boundaries rather than placing
domain rules in views, models, tasks, or signal receivers.

## Module ownership

| Module | Ownership |
| --- | --- |
| `core` | Dependency-free service, selector, policy, event, and persistence primitives. It owns no feature data. |
| `tenancy` | Tenant identity, tenant lifecycle, and tenant isolation contracts. |
| `accounts` | Authentication identities, membership, and invitation contracts. |
| `clinics` | Clinic identity and clinic lifecycle contracts. |
| `people` | Professional, patient, and professional-patient relationship contracts. |
| `consents` | Consent lifecycle and consent authorization contracts. |
| `audit` | Append-only audit events, integrity chains, authorized queries, and minimized exports. |
| `privacy` | Data-subject requests, reauthenticated exports, lifecycle execution, and operator confirmations. |
| `therapist_dashboard` | Read-only therapist dashboard composition; it owns no source-of-truth domain state. |

The current sprint intentionally provides interfaces and typed events only. Models,
workflows, persistence adapters, event transports, and user-facing features belong to
later tasks.

## Allowed dependency direction

Imports point from a consumer to an owner lower in the following policy. An omitted
edge is forbidden.

- `core` imports no domain module.
- `tenancy` may import `core`.
- `accounts` may import `core`, `tenancy`, and the public `clinics` selectors,
  policies, and services required to select an authorized tenant and create a
  membership from a consumed invitation. It may call the public `audit.services`
  append boundary, but never import audit or clinic models.
- `clinics` may import only `core` and `tenancy`. Current actor verification is a
  framework-neutral policy owned by `core`, so clinic authorization does not create
  a reverse dependency on `accounts`.
- `people` may import `core`, `tenancy`, `accounts`, and `clinics`.
- `consents` may import `core`, `tenancy`, `accounts`, `clinics`, `people`, and the
  public `audit.services` boundary for transactional consent evidence.
- `audit` may import public contracts from `core` and `clinics` to persist
  tenant-bound actor context and authorize audit access. It depends on actor UUIDs,
  not private account models. Producers call its public append service and never
  import audit models directly.
- `privacy` may import public selectors from `accounts`, plus public service, selector,
  and policy contracts from `audit`, `clinics`, and `core`. It stores actor and subject
  UUIDs rather than importing private account models, and coordinates export/lifecycle
  registries without importing another domain's persistence.
- `therapist_dashboard` may import every source domain because it is a read-only
  composition boundary. Source domains must never import it.

Cross-domain calls use public services, selectors, policies, or domain events. Direct
imports of another module's models or private implementation modules are not allowed.
The one persistence exception is target-specific: concrete domain models may import
`UUIDTimestampedModel` with
`from core.persistence import UUIDTimestampedModel`. `core.models`, every domain's
`models` module, and every other symbol under `core.persistence` remain private. The base
contains only UUID identity and lifecycle timestamps; tenant and actor attribution belong
only on concrete models that can enforce those relationships.
`tests/test_domain_architecture.py` parses imports with Python's AST, rejects edges not
listed above, detects cycles, and proves the guard with intentionally invalid fixtures.
The parser also checks
literal string targets passed positionally or as `name=` to imported `import_module`,
`importlib.import_module`, or `__import__`. When `import_module` receives both a literal
relative name and literal positional or keyword `package`, the parser resolves the target
with Python's relative-import semantics without importing the module. It also recognizes
one direct simple-name assignment of those callables, such as
`loader = importlib.import_module` or `loader = __import__`. This is deliberately
syntactic rather than general data-flow analysis: chained aliases, reassignments,
container storage, returned callables, and calculated module or package strings are
outside the deterministic static contract.

## Service, selector, policy, and event contracts

- A **service** executes one explicit state-changing command.
- A **selector** performs a side-effect-free query.
- An **authorization policy** returns an explicit decision for a subject and resource.
- A **domain event** is immutable, typed, past-tense, and transport-neutral.

Feature packages expose these categories even when no business implementation exists.
This keeps future work explicit without inventing later-sprint behavior.

## Signals policy

Django signals are not a domain workflow mechanism. Services orchestrate state changes,
selectors own reads, policies own authorization, and services publish domain events only
after successful changes. A signal is acceptable only for a genuinely decoupled,
idempotent side effect that cannot be invoked explicitly at the transaction boundary.
Every future signal requires a documented owner, idempotency strategy, transaction timing,
and focused test.

No signal exists in this task: there is no real side effect to justify one. App
configuration must therefore remain side-effect free and must not import `signals` in
`AppConfig.ready()`.
