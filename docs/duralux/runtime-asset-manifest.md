# Manifesto de assets e baseline de runtime

Documento de decisão da Sprint 0. Ele não copia assets nem altera o runtime; define o que existe, o que é referenciado hoje e o subconjunto que poderá ser promovido nas sprints seguintes.

## 1. Inventário da fonte Duralux

A varredura de arquivos regulares encontrou **1.174 arquivos** em `design_system_duralux/`, dos quais **1.059** estão em `design_system_duralux/assets/`. Os 115 restantes são 77 HTMLs e 38 recursos da documentação (a árvore `docs/` inteira possui 46 arquivos, incluindo seus 8 HTMLs).

| Área da fonte | Arquivos | Observação |
|---|---:|---|
| `assets/css/` | 4 | 2 CSS minificados e 2 sourcemaps |
| `assets/images/` | 125 | marcas obrigatórias e imagens demonstrativas |
| `assets/js/` | 37 | inicializadores globais e específicos de páginas demo |
| `assets/scss/` | 158 | fonte de desenvolvimento, proibida no `STATIC_ROOT` |
| `assets/vendors/` | 735 | vendors, fontes, bandeiras, uploads demo e sourcemaps |
| Total em `assets/` | **1.059** | não é o manifesto de runtime |
| Fora de `assets/` | 115 | 77 HTMLs + 38 recursos documentais |
| Total do pacote | **1.174** | fonte auditada, não conjunto publicável |

Distribuição por extensão dentro de `assets/`: 549 SVG, 160 PNG, 158 SCSS, 77 JS, 65 MAP, 25 CSS, 7 JPG, 5 WOFF2, 5 TTF, 2 WOFF, 2 WEBP, 1 MP4, 1 ICO, 1 GIF e 1 EOT. SCSS, MAP, MP4, imagens/avatares/uploads demonstrativos, flags, documentação e plugins sem consumidor estão fora do runtime por padrão.

## 2. Referências atuais da aplicação

### CSS

O `static/` atual tem 17 arquivos. Os três CSS antigos são:

| Arquivo | Referências de template | Dependências internas |
|---|---|---|
| `static/css/framework.css` | `layouts/base.html`, `visual_reference/reference.html`, `content/learning/certificate_verify.html` | bundle de framework atual |
| `static/css/tokens.css` | os mesmos três templates | Cerebri Sans (4 arquivos) e Remix Icon (3 arquivos) |
| `static/css/workspace.css` | `layouts/base.html`, `visual_reference/reference.html` | classes do shell e dos componentes atuais |

### JavaScript

| Arquivo | Referências de template | Papel atual |
|---|---|---|
| `static/js/theme.js` | `layouts/base.html`, `visual_reference/reference.html` | preferência claro/escuro |
| `static/js/workspace-navigation.js` | `layouts/base.html` | estado/foco da navegação |
| `static/js/form-behaviors.js` | `layouts/base.html`, `visual_reference/reference.html` | comportamentos de formulário |
| `static/js/lesson-player.js` | `layouts/base.html` | player de aula |
| `static/js/charts.js` | `layouts/base.html`, `visual_reference/reference.html` | inicialização acessível de ApexCharts |
| `static/vendor/alpine/alpine-3.14.1.min.js` | `layouts/base.html` | runtime Alpine carregado globalmente |
| `static/vendor/apexcharts/apexcharts.min.js` | `layouts/base.html`, `visual_reference/reference.html`; referência direta extra em `therapist_dashboard/home.html` | gráficos atuais |

### Fontes, imagens e favicon

- Fontes atuais: `cerebrisans-regular.woff`, `cerebrisans-medium.woff`, `cerebrisans-semibold.woff`, `cerebrisans-bold.woff`, `remixicon.ttf`, `remixicon.woff` e `remixicon.woff2`, todas declaradas por `static/css/tokens.css`.
- Imagens atuais em templates: somente URLs de upload white-label, em `layouts/vertical.html` (`active_clinic_branding.logo.url`) e `clinics/setup.html` (`clinic_configuration.logo.url`). Não existe imagem versionada em `static/`.
- Favicon atual: nenhum dos 95 templates contém `<link rel="icon">` ou referência a favicon. A lacuna será resolvida com `favicon.svg` em todas as bases completas.
- `content/learning/certificate_verify.html` é HTML completo e referencia apenas `framework.css` e `tokens.css`; portanto precisa de head/fonte/favicon Duralux próprios na Sprint 7.

### Classes estruturais atuais

A camada estrutural foi auditada por consumidor, não por similaridade visual:

| Local | Classes estruturais encontradas |
|---|---|
| `layouts/base.html` | `workspace-body`, `skip-link` |
| `layouts/vertical.html` | `layout-vertical`, `workspace-shell`, `desktop-sidebar`, `brand-mark`, `workspace-column`, `breadcrumbs`, `workspace-main`, `drawer-overlay`, `mobile-sidebar`, `mobile-sidebar-heading` |
| `layouts/detached.html` | `layout-detached`, `workspace-shell`, `detached-frame`, `detached-brand-row`, `brand-mark`, `breadcrumbs`, `workspace-main`, `detached-main`, `drawer-overlay`, `mobile-sidebar`, `mobile-sidebar-heading` |
| `layouts/partials/header.html` | `workspace-header`, `mobile-menu-button`, `clinic-context`, `context-label`, `clinic-switcher`, `user-identity`, `user-avatar`, `theme-toggle`, `sr-only`, `layout-preference` |
| `layouts/partials/navigation.html` | `workspace-navigation`, `navigation-alert`, `navigation-label`, `navigation-list`, `navigation-link`, `is-active`, `navigation-icon` |
| `layouts/partials/messages.html` | `workspace-messages`, `workspace-message`, `workspace-message--<level>` |
| componentes/páginas | `card`, `primary-action`, `page-title`, `workspace-eyebrow`, `form-stack`, `form-field`, `form-actions`, `content-card`, `content-state`, `summary-card`, `responsive-table`, `pagination`, `auth-page`, `auth-card` e variantes de diário/calendário |

A extração lexical encontrou 1.159 tokens em atributos `class` antes de normalizar expressões DTL; por isso esse total não é uma lista de CSS confiável. A lista acima registra as classes que definem shell/componentes e que precisam ser substituídas, mapeadas ou justificadas na migração.

### Alpine e ApexCharts

- Alpine: 19 atributos em 3 templates — `layouts/vertical.html`, `layouts/detached.html` e `layouts/partials/header.html` — usando `x-data`, `x-effect`, `x-cloak`, `x-show`, `x-transition`, `x-ref`, `@click`, `@keydown` e `:aria-expanded`. Como o bundle está em `layouts/base.html`, ele é carregado por todo descendente mesmo quando a página não usa Alpine.
- ApexCharts: bundle global em `layouts/base.html`, repetido no catálogo visual e referenciado diretamente em `therapist_dashboard/home.html`. `static/js/charts.js` procura `[data-apex-chart]`; o catálogo visual tem esse atributo. A migração deve carregar o vendor só nas páginas com gráfico e manter resumo/tabela textual.

## 3. Inline styles e scripts

O baseline observado é **62 templates com atributo `style` ou tag `script`**: 61 páginas quando a base compartilhada é excluída, mais `layouts/base.html`. Há **660 ocorrências literais de ` style=`** e 661 atributos `style` no total. A lista das 61 páginas é:

- `analytics/` (4): `clinic_panel.html`, `patient_dashboard.html`, `report_list.html`, `therapist_dashboard.html`.
- `clinics/` (2): `setup.html`, `whitelabel_domains.html`.
- `content/` (20): `detail.html`, `editorial_compare.html`, `editorial_create.html`, `editorial_detail.html`, `editorial_index.html`, `editorial_preview.html`, `library.html`, `notifications.html`, `recommendations.html`, `reports.html`, `learning/certificate.html`, `learning/certificate_verify.html`, `learning/cohort_detail.html`, `learning/course_detail.html`, `learning/index.html`, `learning/lesson_page.html`, `learning/module_detail.html`, `learning/quiz_detail.html`, `learning/quiz_feedback.html`, `learning/quiz_participate.html`.
- `finance/` (2): `charge_list.html`, `service_price_form.html`.
- `goals/` (11): `detail.html`, `exercise_assign.html`, `exercise_catalog.html`, `exercise_execute.html`, `exercise_execution_detail.html`, `exercise_form.html`, `form.html`, `list.html`, `low_energy.html`, `patient_exercises.html`, `placeholder.html`.
- `journal/` (7): `checkin_list.html`, `checkin_today.html`, `checkin_unavailable.html`, `detail.html`, `form.html`, `list.html`, `partials/calendar.html`.
- `scheduling/` (13): `appointment_calendar.html`, `appointment_list.html`, `appointment_request.html`, `appointment_reschedule.html`, `conversation_create.html`, `conversation_detail.html`, `conversation_list.html`, `reminder_preferences.html`, `room_form.html`, `unit_form.html`, `unit_list.html`, `waitlist_form.html`, `waitlist_list.html`.
- Outros (2): `therapist_dashboard/home.html`, `visual_reference/reference.html`.

Metodologia: `rg -o --glob '*.html' ' style=' templates | wc -l` reproduz 660. `clinics/setup.html` contém ainda um atributo condicional `{% if ... %}style="..."{% endif %}` sem o espaço literal antes de `style`; por isso uma busca sintática mais ampla encontra **661** atributos em 59 templates. `therapist_dashboard/home.html` e `visual_reference/reference.html` completam as 61 páginas porque possuem scripts sem atributo `style`; `layouts/base.html` é o 62º template da união. Há 13 tags `<script>`: 7 em `layouts/base.html`, 2 em `therapist_dashboard/home.html` e 4 em `visual_reference/reference.html`; a base contém ainda uma tag `<style>` para tokens white-label.

Prioridade de extração: primeiro shell/componentes compartilhados (Sprint 2), depois os maiores concentradores clínicos (`journal/list.html`, `journal/detail.html`, `goals/low_energy.html`, `goals/detail.html`, `goals/list.html`), seguindo a sprint responsável da matriz 95/95.

## 4. Referências quebradas conhecidas da demo

| Fonte | Referência quebrada | Evidência/causa | Tratamento obrigatório na adaptação |
|---|---|---|---|
| `help-knowledgebase.html` | `.assets/images/favicon.ico`, `.assets/css/bootstrap.min.css`, `.assets/vendors/css/vendors.min.css`, `.assets/css/theme.min.css` | prefixo `.assets` não existe | não copiar; usar `{% static %}` apenas para itens do manifesto |
| `help-knowledgebase.html` | `/docs/documentations` | não existe nesse pacote como caminho absoluto | substituir por rota Django real de ajuda, se houver consumidor |
| `leads.html` | `apps-mail.html` (10 ocorrências) | o arquivo existente chama-se `apps-email.html` | página tem decisão `não usar`; nenhuma referência migra |
| `leads.html` | `/docs/documentations` | caminho absoluto ausente no pacote | descartar com a página demo |
| `widgets-lists.html` | `../assets/images/avatar/{1,3,4,5}.png` e `../assets/images/payment/{mastercard,visa,discover,american-express,jcb}.svg` | o HTML está na raiz e `../assets` sobe um nível indevido | não copiar imagens demo; componentes usam dados/ícones autorizados |
| `widgets-lists.html` | `/docs/documentations` | caminho absoluto ausente no pacote | substituir somente se existir rota Django correspondente |
| `assets/vendors/css/feather.min.css` | `../fonts/feather.svg?...` | o CSS declara fallback SVG, mas o pacote contém apenas EOT/TTF/WOFF | remover o fallback ausente na cópia promovida e validar EOT/TTF/WOFF |

Essas quebras são toleradas apenas na fonte demonstrativa não servida. O teste de guarda das sprints seguintes deve rejeitá-las em templates e `static/duralux/`.

## 5. Créditos, atribuições e lacuna de licença

Extração literal de `design_system_duralux/docs/html/credit-resource.html`:

- Atribuição do documento: meta author “Bootstrap-ecommerce by Vosidiy”; rodapé “By: theme_ocean” e “Distributed by: ThemeWagon”. O próprio `theme.min.css` também identifica WRAPCODERS como autor/copyright, portanto a cadeia de autoria precisa ser preservada e conferida antes de redistribuir.
- Imagens/fontes visuais creditadas (9): Pexels, Unsplash, Freepik, Storyset, Flaticon, Icomoon, Iconscout, Undraw e DummyImage. O aviso diz que as imagens são somente de demonstração, permanecem sob copyright dos autores e que o comprador deve verificar os direitos antes do uso. Nenhuma imagem demo está no manifesto mínimo.
- Ícones creditados (8): Bootstrap Icons, Feather Icons, Flag Icons, FontAwesome, Material Design Icons, Themify Icons, Weather Icons e Simple Line Icons.
- Plugins creditados (46): Animate.css, Apex Charts, Bootstrap, Bootstrap colorpicker, Bootstrap datepicker, Bootstrap tag-input, Bootstrap Markdown, Bootstrap Treeview, TUI Calendar, Cleave.js, Chart.js, Chartist, CodeMirror, Cropper.js, Dragula, DataTables, Dropify, Dropzone, Flatpickr, FullCalendar, Flow, Formatter.js, FooTable, Google Chart, Growl, IdleTimer, Inputmask, jQuery, jQuery Steps, jQuery Toast, jQuery Validation, jqvmap, jsGrid, Ladda, Moment.js, Morris.js, Parsley, Popper, Pace, Swiper, Semantic UI, Select2, Smart Wizard, Summernote, Toastr e Typeahead.

O arquivo chama sua lista de “URL, License”, mas suas tabelas têm somente colunas **Name** e **Link**: ele não informa versão, identificador SPDX, texto da licença ou obrigação de notice para os 63 recursos listados. Também não há arquivo `LICENSE`, `COPYING` ou `NOTICE` no pacote. Consequência: crédito não equivale a licença validada. Antes de promover qualquer vendor, a Sprint 1 deve identificar a versão no arquivo, confirmar a licença na distribuição oficial, guardar o texto exigido e registrar a atribuição. O cabeçalho local de `bootstrap.min.css` é a única evidência explícita encontrada nessa seleção: Bootstrap, copyright 2011–2022, licença MIT.

## 6. Manifesto mínimo permitido

Allowlist inicial, deliberadamente pequena. Somente os itens abaixo podem ser promovidos na Sprint 1; qualquer ampliação exige consumidor na matriz, licença validada e atualização deste manifesto antes da cópia. Quando a versão embarcada no pacote é incompatível, a tabela registra explicitamente a distribuição oficial usada para normalizar o par local.

| Origem / proveniência | Destino previsto | Condição |
|---|---|---|
| distribuição oficial `bootstrap@5.3.3/dist/css/bootstrap.min.css` | `static/duralux/css/bootstrap.min.css` | versão alinhada ao JS 5.3.3 do pacote; preservar cabeçalho e `docs/duralux/licenses/bootstrap-5.3.3-MIT.txt`; cópia local sem CDN em runtime |
| `assets/css/theme.min.css` | `static/duralux/css/theme.min.css` | remover o único `@import` Google Fonts e o comentário final `sourceMappingURL=theme.min.css.map` na cópia; não editar a fonte original |
| `assets/vendors/css/feather.min.css` | `static/duralux/vendors/css/feather.min.css` | somente após licença Feather confirmada e remoção, na cópia, do fallback ausente `feather.svg` |
| `assets/vendors/fonts/feather.eot` | `static/duralux/vendors/fonts/feather.eot` | dependência de `feather.min.css` |
| `assets/vendors/fonts/feather.ttf` | `static/duralux/vendors/fonts/feather.ttf` | dependência de `feather.min.css` |
| `assets/vendors/fonts/feather.woff` | `static/duralux/vendors/fonts/feather.woff` | dependência de `feather.min.css` |
| `assets/vendors/js/jquery.min.js` | `static/duralux/vendors/js/jquery.min.js` | somente após versão/licença confirmadas |
| distribuição oficial `bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js` | `static/duralux/js/bootstrap.bundle.min.js` | bundle local com Popper 2.11.8 para dropdown/offcanvas; preservar cabeçalho Bootstrap e remover somente a referência ao sourcemap não publicado; avisos MIT em `docs/duralux/licenses/` |
| código próprio do produto | `static/duralux/js/product-shell.js` | tema, tokens white-label e navegação móvel acessível sem Alpine; nenhum dado ou dependência externa |
| código próprio do produto | `static/duralux/js/form-behaviors.js` | máscaras, prevenção de envio duplicado e avisos de formulário |
| código próprio do produto | `static/duralux/js/lesson-player.js` | controles acessíveis carregados somente na página de aula |
| código próprio do produto | `static/duralux/js/dashboard-charts.js` | adaptador do painel do terapeuta com tabela textual equivalente |
| código próprio do produto | `static/duralux/js/visual-reference-charts.js` | adaptador do catálogo visual com resumo e tabela textual equivalentes |
| ApexCharts 3.52.0, MIT | `static/duralux/vendors/apexcharts/apexcharts.min.js` | carregamento restrito às páginas com gráfico; aviso em `docs/duralux/licenses/apexcharts-3.52.0-MIT.txt` |
| `assets/vendors/js/perfect-scrollbar.min.js` | `static/duralux/vendors/js/perfect-scrollbar.min.js` | somente se o shell realmente o consumir e após licença confirmada |
| `assets/vendors/js/nxlNavigation.min.js` | `static/duralux/vendors/js/nxlNavigation.min.js` | apenas para navegação Duralux validada |
| `assets/js/common-init.min.js` | `static/duralux/js/common-init.min.js` | auditar seletores e remover inicialização de recursos ausentes na camada de integração |
| `assets/images/logo_login.webp` | `static/duralux/images/logo_login.webp` | marca obrigatória de autenticação |
| `assets/images/logo_header.webp` | `static/duralux/images/logo_header.webp` | fallback obrigatório do header/sidebar |
| `assets/images/favicon.svg` | `static/duralux/images/favicon.svg` | favicon obrigatório das bases completas |

Os CSS/JS de integração em `static/duralux/` são autoria do projeto, não cópias do pacote, e permanecem testados. A base global carrega somente Bootstrap e `product-shell`; `form-behaviors`, `lesson-player` e ApexCharts são declarados pelos seus consumidores. Estão expressamente fora da allowlist: `vendors.min.css/js`, `theme-customizer-init.min.js`, inicializadores de páginas demo, sourcemaps, SCSS, flags, uploads, avatares/banners, `logo-full.png`, `logo-abbr.png`, `favicon.ico`, documentação e plugins sem consumidor. ApexCharts foi readmitido na Sprint 8 após confirmar versão/licença, consumidores restritos e alternativas textuais.

### Runtime selection installed in Sprint 1

The current local runtime contains exactly thirteen files: official Bootstrap CSS 5.3.3, the official Bootstrap 5.3.3 bundle with `@popperjs/core@2.11.8`, the sanitized Duralux theme CSS, product integration CSS, three required brand assets, four product-owned JavaScript adapters, product-shell, and ApexCharts 3.52.0. The original Duralux CSS is Bootstrap 5.2.0-beta1 while `assets/js/bootstrap.min.js` is 5.3.3 and lacks Popper; both Bootstrap files therefore come from the compatible official 5.3.3 distribution. jQuery, Perfect Scrollbar, Feather and Duralux demo initializers remain unpromoted because no production consumer requires them.

Recorded SHA-256 values:

| Runtime file | SHA-256 |
|---|---|
| `css/bootstrap.min.css` | `26db49828d6701fcfce37a96da6ec3f0ed481abae49c8c9969a575b064413cad` |
| `css/theme.min.css` | `71257c55b10217bf94a0f71c3fda141545ad500a6bebec5bbeb29ee65c5d0be9` |
| `css/product-integration.css` | `26766b92714ab9c1306d4c7c9c325ced6ed6ab34bc864acfeb67713723d17c47` |
| `js/bootstrap.bundle.min.js` | `073254afbfc06331b8b548b7fc0532b4ffe2cfdd588368dcc338e7abd50810e1` |
| `js/dashboard-charts.js` | `773ba64d6e553379af0f422633bd76fc3e3727a6ec5e770bdf41bb9601135fd2` |
| `js/form-behaviors.js` | `2aa3ea86ef5e59ba1b0091e3fc2a30d6e942a5a301eca4a63e0323a98336665f` |
| `js/lesson-player.js` | `ea7ec89f8b738db3d7cb467466c2a5803cdad380f7656855bd2d514ddc6169a7` |
| `js/product-shell.js` | `803b3465b5ae7c6641508e6b23433aadc8ff5308891b41dff7f29af66aa2f5d3` |
| `js/visual-reference-charts.js` | `784d21260be824e0b58ebe000983ede4dbec762a68e4ec2bc87a3bc39d53c5ca` |
| `vendors/apexcharts/apexcharts.min.js` | `dacc69f7eb21440e4b331ce1831f9fa5e40f218d995a005db789a9e55d989fe1` |
| `images/favicon.svg` | `d63db9ca2250589dd76fafc71d4029d8e5096ae80b8501f97903d5afa738c6f3` |
| `images/logo_header.webp` | `79e97f09938fecb76293b31c33e991c374e2f71a07ad4fa56be9318f6851042b` |
| `images/logo_login.webp` | `4e0c19623a22cca4705144a4763543dd344c14a3ecfc182838b418a2596fd386` |

## 7. Baseline técnico registrado

Resultados medidos antes da migração, sem converter falhas conhecidas em sucesso:

| Gate | Comando | Resultado registrado | Proveniência nesta execução documental |
|---|---|---|---|
| Runtime | `uv run python --version` | Python 3.14.7 | reconfirmado; foi necessário `UV_CACHE_DIR=/tmp/projetomnunes-uv-cache` no sandbox |
| Sintaxe Python 3.14 | `uv run python -m py_compile accounts/services.py accounts/views.py` | código 0 | reconfirmado com o mesmo cache temporário |
| MFA focado | `uv run pytest tests/test_account_session_mfa.py -q` | **25 passed** | reconfirmado: 25 passed em 112,46 s |
| Django | `uv run python manage.py check` | passou | baseline previamente medido, não reclassificado |
| Staticfiles | `uv run python manage.py collectstatic --noinput --dry-run` | passou | baseline previamente medido, sem cópia nesta sprint |
| Ruff | `uv run ruff check .` | passou | reconfirmado: `All checks passed!` |
| Pytest completo | `uv run pytest` | **1080 passed, 1 skipped, 4 failed** | baseline previamente medido; gate completo está vermelho |
| Mypy | `uv run mypy .` | **95 erros em 19 arquivos** | baseline previamente medido; gate está vermelho |

“Passou” acima registra o resultado fornecido/medido, não muda checkbox do PRD. A Sprint 0 documenta um baseline com falhas aprovadas conhecidas; regressões futuras devem ser comparadas separadamente contra os 4 testes falhos e os 95 erros de tipagem, e a definição global de pronto continua exigindo gate completo aprovado.

### Verificação corrente após correções preexistentes

Em 2026-09-04, uma execução fresca no mesmo working tree registrou o estado
corrente, sem reescrever a fotografia histórica acima:

| Gate | Comando | Resultado corrente |
|---|---|---|
| Fundação estática | `uv run pytest tests/test_duralux_static_foundation.py -q --no-cov` | **11 passed** |
| Pytest completo | `uv run pytest` | **1089 passed, 1 skipped** em 149,57 s |
| Ruff | `uv run ruff check .` | `All checks passed!` |
| Mypy | `uv run mypy .` | `Success: no issues found in 561 source files` |
| Django | `DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py check` | nenhum problema identificado |
| Staticfiles | `DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py collectstatic --noinput --dry-run` | código 0, sem conflito de caminhos |

As duas variáveis `DJANGO_SETTINGS_MODULE` acima são explícitas porque o settings
de desenvolvimento exige `DJANGO_SECRET_KEY`; a configuração de teste não usa
segredos de produção. Os 21 arquivos modificados que tornaram o gate corrente
verde já estavam no working tree antes desta reconciliação e não são atribuídos à
migração Duralux sem revisão própria.

## 8. Comandos reproduzíveis de inventário

```sh
find design_system_duralux -type f | wc -l
find design_system_duralux/assets -type f | wc -l
find design_system_duralux -type f -name '*.html' | wc -l
find templates -type f -name '*.html' | wc -l
rg -o --glob '*.html' ' style=' templates | wc -l
rg -n --glob '*.html' '<script\b' templates
rg -n --glob '*.html' "\{% static '[^']+' %\}|/static/" templates
rg -n --glob '*.html' 'x-data|x-effect|x-cloak|x-show|x-transition|x-ref|@click|@keydown|:aria-expanded' templates
rg -n --glob '*.html' --glob '*.js' 'ApexCharts|apexcharts|data-apex' templates static/js
```
