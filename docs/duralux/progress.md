# Progresso da migração Duralux

Atualizado em 2026-09-05. Este ledger complementa `MUDANCALAYOUT.prd`; o PRD é a
fonte dos critérios e somente recebe `[X]` quando a evidência correspondente foi
verificada.

| Escopo | Estado | Evidência | Próximo gate |
|---|---|---|---|
| Sprint 0 — matrizes, inventário e baseline | complete | catálogo 77/77; baseline 95/95 reconciliada como 94 templates retidos, um órfão removido e três auxiliares Duralux; 97 HTML atuais; baseline visual registrada | nenhum |
| Sprint 1 — static foundation | complete | 13 assets locais no manifesto atual; hashes verificados; Staticfiles e `collectstatic` aprovados; sem CDN | nenhum |
| Sprint 2 — shell e componentes | complete | seis layouts/partials e cinco componentes migrados; ponte visual legada removida; menu móvel validado com Escape, foco e retorno ao acionador | leitor de tela permanece no gate transversal |
| Sprint 3 — autenticação, MFA e erros | implementation_complete / external_gate_pending | oito templates migrados; QR/URI locais; proteção de cache, replay, recovery codes e tracebacks revisada e aprovada | scan físico no Google Authenticator e leitor de tela |
| Sprint 4 — workspace e gestão | complete | 15 templates migrados; blocker OAuth superado pelo gate global atual; revisão visual e contratos aprovados | nenhum específico |
| Sprint 5 — agenda, comunicação e financeiro | implementation_complete | 15 templates migrados; autorização e comportamento preservados; gates focados/globais aprovados | validação manual específica do calendário por teclado |
| Sprint 6 — consentimentos, diário e metas | implementation_complete / external_gate_pending | baseline 24/24 reconciliada; 23 templates retidos e placeholder órfão removido; 130 testes clínicos, evidência visual corretiva e revisão independente aprovados | leitor de tela físico |
| Sprint 7 — conteúdo e aprendizagem | implementation_complete / external_gate_pending | 21 templates migrados; certificado público, sanitização, player e assets por página cobertos por testes e evidência visual | leitor de tela físico do player/questionários |
| Sprint 8 — catálogo, legado e documentação | complete | catálogo visual migrado; runtime legado removido; matrizes/documentos reconciliados; revisão independente 95/95 aprovada | nenhum |
| Sprint 9 — validação integrada | technical_complete / external_gates_pending | `final-verification.md`; gate completo, 168 verificações visuais acumuladas e revisões independentes aprovados | scan físico, leitor de tela e percurso exaustivo de rotas/perfis |

## Gate integrado de 2026-09-05

- `uv run pytest`: **1.150 passed, 1 skipped** em 182,56 s; cobertura total de **86%**.
- `uv run ruff check .`: aprovado.
- `uv run mypy .`: nenhum problema em 565 arquivos-fonte.
- `DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py check`:
  nenhum problema identificado.
- `DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py
  collectstatic --noinput --dry-run`: aprovado.
- `uv run python -m py_compile accounts/services.py accounts/views.py
  journal/forms.py`, `node --check` em todos os adaptadores Duralux e
  `git diff --check`: aprovados.
- Gate focado de legado/templates/staticfiles/formulários/layouts: **64 passed**.
- Suíte clínica da Sprint 6: **130 passed, 1 skipped**; suíte MFA: **40 passed**.
- O runtime publicável tem treze arquivos, não contém CSS, fontes, Alpine ou
  caminhos JavaScript legados e limita ApexCharts aos consumidores documentados.
- Evidência visual: 120 verificações integradas mais 48 corretivas, zero falhas;
  caminhos em `evidence/integrated-final/` e `evidence/final-rereview/`.
- Revisões independentes finais de segurança MFA, cobertura 95/95, remoção de
  legado e Sprint 6 foram aprovadas sem Critical/Important.
- Permanecem abertos somente os gates manuais/externos registrados em
  `final-verification.md`; eles não são substituídos pelos testes automatizados.

## Roteamento de modelos

- Baixa complexidade: modelo OpenAI leve, esforço mínimo/baixo, para inventários e
  alterações mecânicas.
- Complexidade média: modelo OpenAI `gpt-5.6-sol`, esforço médio, para implementação
  delimitada com testes.
- Segurança, arquitetura e revisão independente: modelo OpenAI `gpt-5.6-terra` ou
  outro modelo disponível adequado, esforço alto. Esforço máximo exige autorização
  explícita; alternância solicitada não implica autorização para esforço máximo.
- Em 2026-09-05, o acesso do Codex CLI voltou a funcionar: uma auditoria mecânica
  da Sprint 3 foi executada em `gpt-5.4-mini` com esforço baixo. Implementação de
  segurança permaneceu no modelo contextual com raciocínio alto.

## Sprint 3 current slice

- `build_totp_key_uri` normaliza o Key URI Format com issuer e conta codificados;
  `build_totp_qr_data_uri` gera SVG local com Segno, sem serviço externo.
- `mfa_enroll` usa template dedicado, expõe QR somente para fator pendente, mantém
  chave manual selecionável, cópia com fallback acessível e reinício por POST/CSRF.
- Cadastro, desafio confirmado e recuperação recebem `Cache-Control: no-store`,
  `Pragma: no-cache` e `X-Robots-Tag: noindex, nofollow, noarchive` sem registrar
  segredo, URI ou imagem em logs/auditoria.
- `auth_form`, `auth_message`, recuperação, sessões e quatro erros usam a fundação
  Duralux local. O card público foi limitado a 36 rem após revisão em 1280 px.
- Evidência automatizada corrente: 51 testes focados passaram. O gate final
  sequencial retornou **1109 passed, 1 skipped**, Ruff sem erros, Mypy sem erros em
  561 arquivos, Django check e collectstatic dry-run aprovados, além de
  `git diff --check`. A revisão visual cobriu MFA em 1280 e
  375 px, login em 1280 e 375 px, sessões em 375 px e 404 de produção em 1280 e
  375 px, todos sem overflow horizontal. O clipboard bloqueado pelo navegador
  exibiu a orientação de seleção manual.
- A primeira revisão independente de alto esforço pediu correção de títulos da
  recuperação/erros e ampliação dos testes de cabeçalhos sensíveis. Os reparos
  passaram em sete testes corretivos; a re-revisão retornou **APPROVED**, sem
  Critical ou Important. O 404 final exibiu o título acessível correto e card de
  576 px em desktop.
- Permanecem pendentes as jornadas visuais não percorridas nesta fatia e o scan
  exigido em Google Authenticator físico. Nenhum checkbox da Sprint 3 foi marcado
  apenas com esta evidência parcial.

## Sprint 1 manifest-storage resolution

- O namespace `fonts/` permanece adiado sob `static/duralux/` porque o produto
  usa a pilha de fontes do sistema. `vendors/` contém exclusivamente ApexCharts
  3.52.0, carregado apenas nos dois consumidores com gráfico, alternativa
  textual acessível e aviso MIT em `docs/duralux/licenses/`. Diretórios vazios
  não recebem `.gitkeep` publicável.
- A deterministic scan found nine missing local URLs in `static/css/framework.css`:
  three Fancybox images, two obsolete Remix Icon fallbacks, and three unused
  background utilities (the EOT URL occurs twice). Repository-wide searches found
  no matching files or template consumers.
- The legacy CSS now preserves its available WOFF/WOFF2/TTF icon fonts while
  replacing only the already-broken, unconsumed image declarations with `none`.
  No demo asset was added to the runtime or to the Duralux allowlist.
- A RED regression test reproduced WhiteNoise's `MissingFileError` for
  `images/fancybox_loading.gif`. After the cleanup, the focused manifest test
  passed and the real production-settings manifest storage probe passed:
  154 files copied and 446 post-processed.
- Production now uses `CompressedManifestStaticFilesStorage`. Sprint 1 remains
  `in_progress` until independent review and browser/visual verification are
  complete; no PRD checkbox was changed from automated evidence alone.

## Latest continuation checkpoint

- Revalidated the inherited working tree without changing application code:
  `uv run pytest` returned **1095 passed, 1 skipped** in 202.77 seconds;
  `uv run ruff check .` passed; `uv run mypy .` reported no issues in 561 files.
  Focused static foundation tests: **11 passed**.
- Attempted OpenAI routing through Codex CLI 0.151.0:
  `gpt-5.4-mini` with `model_reasoning_effort="low"`, followed by
  `gpt-5.6-sol` with `model_reasoning_effort="medium"`. Both exited with code 1:
  `Your workspace is out of credits. Add credits to continue.`
  The second invocation used `--ignore-user-config` and still failed, separating
  the credit blocker from unrelated MCP/hook configuration errors in the first.
- No delegated task or independent review completed. No new PRD checkbox was
  marked, and no template, production code, commit, push or deployment changed.
- Continuation with alternating OpenAI models is blocked pending restored access
  or user authorization to proceed without that routing requirement.
- The manifest-storage blocker has been resolved. Browser probes loaded all seven
  Duralux assets with HTTP 200 and correct MIME types. Isolated desktop (1440 px)
  and mobile (375 px) renders showed no horizontal overflow; both brand logos were
  legible and uncropped, and the favicon remained recognizable at browser scale.
  The next Sprint 1 gate is independent re-review; fresh automated tests alone do
  not constitute acceptance of later route/template migrations.
- Fresh full gate after the storage fix: `uv run pytest` returned **1096 passed,
  1 skipped**; `uv run ruff check .` passed; `uv run mypy .` reported no issues in
  561 source files. The strengthened focused suite returned **12 passed** and now
  verifies that `staticfiles.json` maps every Duralux runtime asset plus the legacy
  framework CSS to an existing hashed output.
- Independent re-review verdict: **approved**, with no Critical or Important
  findings. Its focused static/security/theme gate returned **35 passed**.

## Sprint 2 current slice

- The vertical and detached shells use the Duralux `nxl-navigation`, `nxl-header`
  and `nxl-container` structure with local brand fallback and explicit dimensions.
- Header, navigation, messages, forms, pagination, responsive tables, summary cards
  and content states were converted to Bootstrap/Duralux markup. Mobile navigation
  uses vanilla JavaScript with Escape, focus trap/restoration, overlay close and
  scroll lock. Theme state persists without Alpine and synchronizes
  `data-bs-theme` with legacy `data-theme` while the transition remains active.
- Browser validation covered 320, 375, 768, 1024, 1280 and 1440 px without
  horizontal overflow. The 1024 px missing-menu regression, an 80 px mobile gap,
  and light/dark contrast defects in header, labels, links and breadcrumbs were
  corrected. Drawer open/close, Escape and focus restoration were exercised.
- Independent review initially returned `changes_requested`: removing the old
  global assets broke 147 active legacy-class references and nine guarded forms;
  a white-label-derived link color could also fail on a light background.
- The corrected implementation deliberately keeps a documented compatibility
  bridge for `framework.css`, `tokens.css`, `workspace.css`, form behaviors,
  lesson behavior, Alpine and ApexCharts until the domain templates in Sprints
  4–7 are migrated. Link colors and focus indicators are now fixed per theme:
  light mode uses `#1d4ed8` at 6.70:1 against white, while dark mode uses
  `#93c5fd` at 8.11:1 against the shell background. The secondary-button states
  use dark text so light tenant colors such as `#93C5FD` remain legible.
- Final independent re-review verdict: **approved**, with no Critical or Important
  findings. Its focused layouts/themes/charts/forms/components/static-foundation
  suite returned **82 passed**; Ruff and `git diff --check` also passed. A
  subsequent RED/GREEN regression check for the theme-specific focus ring and
  desktop drawer transition returned **2 passed**.
- Latest full gate before these final CSS regression patches: **1101 passed, 1
  skipped**; Ruff, Mypy and Django check passed; `collectstatic --dry-run` copied
  2 changed files and found 153 unchanged files. A fresh full gate remains
  required before Sprint closure. Sprint 2 remains `in_progress`, and no Sprint
  2 PRD checkbox is marked because the compatibility bridge means Duralux is not
  yet the only active runtime system.

## Sprint 4 verification checkpoint

- Migrated all 15 assigned templates across workspace, analytics, therapist
  dashboard, clinics, people and onboarding to local Duralux/Bootstrap product
  patterns.
- Added `static/duralux/js/dashboard-charts.js` as page-scoped progressive
  enhancement. The accessible registration table remains available without
  JavaScript or chart rendering.
- Added `tests/test_sprint4_duralux_templates.py`, which rejects inline styles,
  inline scripts and the known legacy visual class tokens in the 15-template
  scope. It also requires explicit page titles and the accessible chart table.
- Focused verification: 71 tests passed across Sprint 4 contracts, analytics,
  therapist dashboard, patient management, onboarding, clinic setup and the
  Duralux static foundation. Ruff and `git diff --check` passed.
- Visual review: 1280 × 720 and 375 × 812 for workspace, clinic analytics,
  reports, patient list, clinic setup, clinic onboarding and therapist
  dashboard. No horizontal overflow or legacy class token was observed; the
  therapist dashboard showed both chart target and textual table.
- During visual review, blank document titles were reproduced and fixed by
  exposing the `title` block in `layouts/base.html` and defining it in every
  Sprint 4 template. Browser recheck confirmed the corrected titles.
- Current state: `review_pending`. No Sprint 4 checkbox is complete until an
  independent review and fresh global gates approve this exact state.
