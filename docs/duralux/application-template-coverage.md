# Cobertura dos templates Django

Baseline da Sprint 0. A rota é exibida sem parâmetros repetitivos quando o próprio nome da view elimina ambiguidade. “Membro ativo” significa identidade autenticada com vínculo vigente na clínica; a autorização fina continua nos serviços/policies e não deve ser substituída pelo template. Partials e layouts não têm rota própria: seu consumidor real é registrado na mesma coluna.

| Template Django | Rota / view consumidora | Perfil autorizado | Layout pai | Referência Duralux | Sprint |
|---|---|---|---|---|---|
| `accounts/auth_form.html` | `/accounts/login/` `account_login`; convite, recuperação/reset e `mfa_verify` | anônimo nos fluxos públicos; membro autenticado no desafio MFA | `accounts/auth_base.html` | `auth-login-minimal`, `auth-register-minimal`, `auth-reset-minimal`, `auth-resetting-minimal`, `auth-verify-minimal` | 3 |
| `accounts/auth_message.html` | `invitation_issue`, `invitation_accept`, `password_recovery`, `password_reset`, `password_reset_complete` | anônimo, convidado ou clinic_admin conforme a ação | `accounts/auth_base.html` | `auth-register-minimal`, `auth-reset-minimal` | 3 |
| `accounts/mfa_recovery_codes.html` | pós-confirmação de `/accounts/mfa/enroll/` `mfa_enroll` | membro autenticado em cadastro/reinício MFA | `accounts/auth_base.html` | `auth-verify-minimal` | 3 |
| `accounts/sessions.html` | `/accounts/sessions/` `account_sessions` | membro autenticado | `layouts/vertical.html` | `settings-general` | 3 |
| `analytics/clinic_panel.html` | `/analytics/clinica/` `clinic_panel` | clinic_admin | `layouts/vertical.html` via `layout_template` | `analytics`, `reports-sales`, `widgets-charts` | 4 |
| `analytics/patient_dashboard.html` | `/analytics/` `patient_dashboard` | patient | `layouts/vertical.html` via `layout_template` | `analytics`, `widgets-statistics` | 4 |
| `analytics/report_list.html` | `/analytics/relatorios/` `report_list` | patient e clinic_admin, conforme relatório | `layouts/vertical.html` via `layout_template` | `reports-leads`, `widgets-tables` | 4 |
| `analytics/therapist_dashboard.html` | `/analytics/profissional/` `therapist_dashboard` | therapist | `layouts/vertical.html` via `layout_template` | `analytics`, `reports-project` | 4 |
| `clinics/confirm_switch.html` | `/clinics/switch/review/` `review_clinic_switch` | membro autenticado com acesso às duas clínicas | `layouts/base.html` | `settings-general` | 4 |
| `clinics/setup.html` | `/clinics/setup/` `clinic_setup` | clinic_admin | `layouts/vertical.html` via `layout_template` | `settings-general`, `settings-localization`, `customers-create` | 4 |
| `clinics/whitelabel_domains.html` | `/clinics/white-label/dominios/` `whitelabel_domains` | clinic_admin | `layouts/vertical.html` via `layout_template` | `settings-general` | 4 |
| `components/content_state.html` | includes em `workspace/home.html` e catálogo visual | herda o perfil do consumidor | partial, sem layout próprio | `widgets-miscellaneous`, `help-knowledgebase` | 2 |
| `components/form.html` | include no catálogo visual e formulários reutilizáveis | herda o perfil do consumidor | partial, sem layout próprio | `settings-general`, `customers-create` | 2 |
| `components/pagination.html` | includes em `workspace/home.html` e catálogo visual | herda o perfil do consumidor | partial, sem layout próprio | `customers`, `widgets-tables` | 2 |
| `components/responsive_table.html` | includes em `workspace/home.html` e catálogo visual | herda o perfil do consumidor | partial, sem layout próprio | `widgets-tables` | 2 |
| `components/summary_card.html` | includes em `workspace/home.html` e catálogo visual | herda o perfil do consumidor | partial, sem layout próprio | `widgets-statistics` | 2 |
| `consents/center.html` | `/consents/` `consent_center` | membro ativo, documentos filtrados por audiência | `layouts/vertical.html` | `projects`, `projects-view` | 6 |
| `consents/decision_error.html` | resposta de `consent_decide` | membro ativo sem decisão válida/autorizada | `layouts/vertical.html` | `projects-view`, `auth-verify-minimal` | 6 |
| `consents/partials/document_decision.html` | include em `consents/center.html` | herda audiência autorizada do centro | partial, sem layout próprio | `projects-view`, `widgets-lists` | 6 |
| `consents/revocation_error.html` | resposta de `consent_revoke` | membro ativo sem revogação válida/autorizada | `layouts/vertical.html` | `projects-view`, `auth-verify-minimal` | 6 |
| `consents/revocation_work_error.html` | resposta de `acknowledge_revocation_work` | clinic_admin | `layouts/vertical.html` | `projects-view`, `auth-verify-minimal` | 6 |
| `consents/revocation_work_queue.html` | `/consents/operations/revocations/` `revocation_work_queue` | clinic_admin | `layouts/vertical.html` | `projects`, `apps-tasks` | 6 |
| `content/detail.html` | `/conteudos/<slug>/` `content_detail` | membro ativo dentro da audiência | `layouts/vertical.html` via `layout_template` | `help-knowledgebase`, `proposal-view` | 7 |
| `content/editorial_compare.html` | `/conteudos/editorial/<id>/comparar/` `editorial_compare` | clinic_admin/editor autorizado | `layouts/vertical.html` via `layout_template` | `proposal-view`, `proposal-edit` | 7 |
| `content/editorial_create.html` | `/conteudos/editorial/novo/` `editorial_create` | clinic_admin/editor autorizado | `layouts/vertical.html` via `layout_template` | `proposal-create`, `proposal-edit` | 7 |
| `content/editorial_detail.html` | `/conteudos/editorial/<id>/` `editorial_detail` | clinic_admin/editor autorizado | `layouts/vertical.html` via `layout_template` | `proposal-view` | 7 |
| `content/editorial_index.html` | `/conteudos/editorial/` `editorial_index` | clinic_admin/editor autorizado | `layouts/vertical.html` via `layout_template` | `proposal`, `widgets-tables` | 7 |
| `content/editorial_preview.html` | `editorial_preview` por conteúdo/versão | clinic_admin/editor autorizado | `layouts/vertical.html` via `layout_template` | `proposal-view` | 7 |
| `content/learning/certificate.html` | `/conteudos/cursos/<course>/certificado/` `content_course_certificate` | participante matriculado e autorizado | `layouts/vertical.html` via `layout_template` | `proposal-view`, `invoice-view` | 7 |
| `content/learning/certificate_verify.html` | `/conteudos/cursos/certificados/<code>/` `content_certificate_verify` | público por código válido | HTML completo, sem pai | `auth-verify-minimal`, `proposal-view` | 7 |
| `content/learning/cohort_detail.html` | `/conteudos/cursos/coortes/<id>/` `content_cohort_detail` | clinic_admin/editor autorizado | `layouts/vertical.html` via `layout_template` | `customers-view`, `projects-view` | 7 |
| `content/learning/course_detail.html` | `/conteudos/cursos/<course>/` `content_course_authoring_detail` | clinic_admin/editor autorizado | `layouts/vertical.html` via `layout_template` | `projects-view`, `proposal-view` | 7 |
| `content/learning/index.html` | `/conteudos/cursos/` `content_learning_authoring_index` | clinic_admin/editor autorizado | `layouts/vertical.html` via `layout_template` | `apps-storage`, `projects` | 7 |
| `content/learning/lesson_page.html` | `/conteudos/cursos/<course>/aulas/<lesson>/` `content_lesson_player` | participante matriculado e autorizado | `layouts/vertical.html` via `layout_template` | `help-knowledgebase`, `apps-notes` | 7 |
| `content/learning/module_detail.html` | `content_course_module_detail` | clinic_admin/editor autorizado | `layouts/vertical.html` via `layout_template` | `projects-view`, `apps-tasks` | 7 |
| `content/learning/quiz_detail.html` | `/conteudos/cursos/questionarios/<id>/` `content_quiz_detail` | clinic_admin/editor autorizado | `layouts/vertical.html` via `layout_template` | `projects-view`, `widgets-lists` | 7 |
| `content/learning/quiz_feedback.html` | `content_quiz_feedback` por tentativa | participante matriculado dono da tentativa | `layouts/vertical.html` via `layout_template` | `widgets-statistics`, `projects-view` | 7 |
| `content/learning/quiz_participate.html` | `content_quiz_participate` | participante matriculado e autorizado | `layouts/vertical.html` via `layout_template` | `apps-tasks`, `auth-verify-minimal` | 7 |
| `content/lesson_player.html` | include em `content/learning/lesson_page.html` | herda participante autorizado | partial, sem layout próprio | `help-knowledgebase`, `apps-storage` | 7 |
| `content/library.html` | `/conteudos/` `library_home` | membro ativo dentro da audiência | `layouts/vertical.html` via `layout_template` | `help-knowledgebase`, `apps-storage` | 7 |
| `content/notifications.html` | `/conteudos/notificacoes/` `notification_list` | membro ativo, somente próprias notificações | `layouts/vertical.html` via `layout_template` | `apps-email`, `widgets-lists` | 7 |
| `content/recommendations.html` | `/conteudos/minhas-recomendacoes/` `recommendation_list` | membro ativo, recomendações autorizadas | `layouts/vertical.html` via `layout_template` | `apps-notes`, `widgets-lists` | 7 |
| `content/reports.html` | `/conteudos/denuncias/` `content_reports` | clinic_admin/editor autorizado | `layouts/vertical.html` via `layout_template` | `settings-support`, `widgets-tables` | 7 |
| `errors/400.html` | handler `bad_request` | público afetado pela requisição inválida | `accounts/auth_base.html` | `auth-404-minimal` | 3 |
| `errors/403.html` | handler `permission_denied` | público ou autenticado sem autorização | `accounts/auth_base.html` | `auth-404-minimal` | 3 |
| `errors/404.html` | handler `page_not_found` | público ou autenticado | `accounts/auth_base.html` | `auth-404-minimal` | 3 |
| `errors/500.html` | handler `server_error` | público ou autenticado | `accounts/auth_base.html` | `auth-404-minimal` | 3 |
| `finance/charge_list.html` | `/financeiro/` `charge_list` | clinic_admin e administrative_staff | `layouts/vertical.html` via `layout_template` | `payment`, `invoice-view`, `widgets-tables` | 5 |
| `finance/service_price_form.html` | `/financeiro/precos/novo/` `service_price_create` | clinic_admin | `layouts/vertical.html` via `layout_template` | `invoice-create`, `settings-finance` | 5 |
| `goals/detail.html` | `/goals/<goal>/` `goal_detail` | patient dono da meta | `layouts/vertical.html` via `layout_template` | `projects-view`, `apps-tasks` | 6 |
| `goals/exercise_assign.html` | `/goals/exercicios/catalogo/<exercise>/atribuir/` `exercise_assign_view` | therapist/clinic_admin autorizado | `layouts/vertical.html` via `layout_template` | `apps-tasks`, `customers-view` | 6 |
| `goals/exercise_catalog.html` | `/goals/exercicios/catalogo/` `exercise_catalog` | therapist/clinic_admin autorizado | `layouts/vertical.html` via `layout_template` | `apps-tasks`, `projects` | 6 |
| `goals/exercise_execute.html` | `/goals/exercicios/atribuicoes/<id>/executar/` `patient_exercise_execute_view` | patient destinatário | `layouts/vertical.html` via `layout_template` | `apps-tasks`, `apps-notes` | 6 |
| `goals/exercise_execution_detail.html` | `/goals/exercicios/execucoes/<id>/` `exercise_execution_detail_view` | patient dono; therapist conforme semáforo | `layouts/vertical.html` via `layout_template` | `projects-view`, `apps-chat` | 6 |
| `goals/exercise_form.html` | `exercise_form` em criar/editar | therapist/clinic_admin autorizado | `layouts/vertical.html` via `layout_template` | `apps-tasks`, `settings-tasks` | 6 |
| `goals/form.html` | `/goals/nova/` `goal_create`; `goal_edit` | patient dono da meta | `layouts/vertical.html` via `layout_template` | `projects-create`, `apps-tasks` | 6 |
| `goals/list.html` | `/goals/` `goal_list` | patient | `layouts/vertical.html` via `layout_template` | `projects`, `apps-tasks` | 6 |
| `goals/low_energy.html` | `/goals/baixa-energia/` `low_energy_home` | patient | `layouts/vertical.html` via `layout_template` | `apps-tasks`, `apps-notes` | 6 |
| `goals/patient_exercises.html` | `/goals/exercicios/meus/` `patient_exercise_list` | patient | `layouts/vertical.html` via `layout_template` | `apps-tasks`, `projects` | 6 |
| `goals/placeholder.html` | removido após busca provar ausência de consumidor | nenhum; arquivo removido | não aplicável | descarte justificado: duplicava `goals/list.html` | 6 |
| `journal/checkin_list.html` | `/journal/checkin/historico/` `checkin_list` | patient | `layouts/vertical.html` via `layout_template` | `apps-notes`, `widgets-lists` | 6 |
| `journal/checkin_today.html` | `/journal/checkin/` `checkin_today` | patient | `layouts/vertical.html` via `layout_template` | `apps-notes`, `apps-tasks` | 6 |
| `journal/checkin_unavailable.html` | resposta de `checkin_today` quando indisponível | patient | `layouts/vertical.html` via `layout_template` | `apps-notes`, `widgets-miscellaneous` | 6 |
| `journal/detail.html` | `/journal/<entry>/` `journal_detail` | patient dono; profissional conforme consentimento | `layouts/vertical.html` via `layout_template` | `apps-notes`, `projects-view` | 6 |
| `journal/form.html` | `/journal/novo/` `journal_create`; `journal_edit` | patient dono | `layouts/vertical.html` via `layout_template` | `apps-notes`, `proposal-edit` | 6 |
| `journal/list.html` | `/journal/` `journal_list` | patient; solicitações autorizadas por relação | `layouts/vertical.html` via `layout_template` | `apps-notes`, `widgets-lists` | 6 |
| `journal/partials/calendar.html` | include em `journal/list.html` | herda o patient autorizado | partial, sem layout próprio | `apps-calendar`, `widgets-statistics` | 6 |
| `layouts/base.html` | pai de autenticação, erros/shells e certificado por contexto | público ou autenticado conforme filho | HTML base completo | head/base dos HTMLs Duralux e auth minimal | 2 |
| `layouts/detached.html` | `/workspace/detached/` e filhos quando preferência `detached` | membro autenticado autorizado | `layouts/base.html` | layout documentado em `docs/html/layouts` | 2 |
| `layouts/partials/header.html` | include em `layouts/vertical.html` e `layouts/detached.html` | herda membro autenticado | partial, sem layout próprio | header comum das demos Duralux | 2 |
| `layouts/partials/messages.html` | include em `layouts/vertical.html` e `layouts/detached.html` | herda consumidor | partial, sem layout próprio | alertas/toasts do núcleo Duralux | 2 |
| `layouts/partials/navigation.html` | include desktop/mobile nos dois shells | herda membro autenticado e flags de perfil | partial, sem layout próprio | `nxl-navigation` do núcleo Duralux | 2 |
| `layouts/vertical.html` | pai padrão das páginas autenticadas | membro autenticado autorizado | `layouts/base.html` | shell de `index.html` e `docs/html/layouts.html` | 2 |
| `onboarding/clinic_checklist.html` | `/onboarding/clinic/` `clinic_onboarding` | clinic_admin | `layouts/vertical.html` via `layout_template` | `projects`, `apps-tasks` | 4 |
| `onboarding/patient_onboarding.html` | `/onboarding/patient/` `patient_onboarding` | patient | `layouts/vertical.html` via `layout_template` | `projects-create`, `auth-register-minimal` | 4 |
| `people/patient_detail.html` | `/people/patients/<id>/` `patient_detail` | clinic_admin/therapist conforme policy | `layouts/vertical.html` via `layout_template` | `customers-view` | 4 |
| `people/patient_form.html` | `/people/patients/new/` `patient_create` | clinic_admin | `layouts/vertical.html` via `layout_template` | `customers-create` | 4 |
| `people/patient_list.html` | `/people/patients/` `patient_list` | clinic_admin | `layouts/vertical.html` via `layout_template` | `customers`, `widgets-tables` | 4 |
| `people/professional_list.html` | `/people/professionals/` `professional_list` | clinic_admin | `layouts/vertical.html` via `layout_template` | `customers`, `widgets-tables` | 4 |
| `scheduling/appointment_calendar.html` | `/agenda/semana/` `appointment_calendar` | membro ativo, agenda filtrada por papel | `layouts/vertical.html` via `layout_template` | `apps-calendar` | 5 |
| `scheduling/appointment_list.html` | `/agenda/` `appointment_list` | membro ativo, consultas autorizadas | `layouts/vertical.html` via `layout_template` | `apps-calendar`, `widgets-tables` | 5 |
| `scheduling/appointment_request.html` | `/agenda/consultas/nova/` `appointment_request` | patient ou equipe autorizada | `layouts/vertical.html` via `layout_template` | `apps-calendar`, `projects-create` | 5 |
| `scheduling/appointment_reschedule.html` | `appointment_reschedule` | participante/equipe autorizada à consulta | `layouts/vertical.html` via `layout_template` | `apps-calendar`, `projects-create` | 5 |
| `scheduling/conversation_create.html` | `/agenda/mensagens/nova/` `conversation_create` | membro ativo com participantes permitidos | `layouts/vertical.html` via `layout_template` | `apps-chat`, `apps-email` | 5 |
| `scheduling/conversation_detail.html` | `/agenda/mensagens/<id>/` `conversation_detail` | participante ativo da conversa | `layouts/vertical.html` via `layout_template` | `apps-chat` | 5 |
| `scheduling/conversation_list.html` | `/agenda/mensagens/` `conversation_list` | membro ativo, somente conversas próprias | `layouts/vertical.html` via `layout_template` | `apps-chat`, `apps-email` | 5 |
| `scheduling/reminder_preferences.html` | `/agenda/lembretes/` `reminder_preferences` | membro autenticado | `layouts/vertical.html` via `layout_template` | `settings-email` | 5 |
| `scheduling/room_form.html` | `/agenda/salas/nova/` `room_create` | clinic_admin | `layouts/vertical.html` via `layout_template` | `settings-general`, `projects-create` | 5 |
| `scheduling/unit_form.html` | `/agenda/unidades/nova/` `unit_create`; `unit_update` | clinic_admin | `layouts/vertical.html` via `layout_template` | `settings-general`, `projects-create` | 5 |
| `scheduling/unit_list.html` | `/agenda/unidades/` `unit_list` | clinic_admin/administrative_staff autorizado | `layouts/vertical.html` via `layout_template` | `customers`, `widgets-tables` | 5 |
| `scheduling/waitlist_form.html` | `/agenda/espera/nova/` `waitlist_add` | clinic_admin/administrative_staff autorizado | `layouts/vertical.html` via `layout_template` | `projects-create`, `customers-create` | 5 |
| `scheduling/waitlist_list.html` | `/agenda/espera/` `waitlist_list` | clinic_admin/administrative_staff autorizado | `layouts/vertical.html` via `layout_template` | `widgets-tables`, `apps-calendar` | 5 |
| `therapist_dashboard/home.html` | `/dashboard/` `therapist_dashboard` | therapist | `layouts/vertical.html` via `layout_template` | `analytics`, `widgets-charts`, `widgets-statistics` | 4 |
| `visual_reference/reference.html` | `/design-system/` `design_system_reference` | staff Django | HTML completo, sem pai | catálogo `widgets-*`, `settings-*` e shell Duralux | 8 |
| `workspace/home.html` | `/workspace/` `workspace_vertical`; `/workspace/detached/` `workspace_detached` | membro autenticado permitido pelo middleware | `layouts/vertical.html` ou `layouts/detached.html` via contexto | `index`, `widgets-statistics`, `widgets-tables` | 4 |

## Fechamento da cobertura

- Baseline contabilizada: **95 templates**; 94 permanecem migrados e `goals/placeholder.html` foi removido com guarda de ausência de referência.
- Templates atuais no disco: **97** = 94 templates retidos da baseline + 3 auxiliares criados pela migração.
- Distribuição de sprint: Sprint 2 = 11; Sprint 3 = 8; Sprint 4 = 15; Sprint 5 = 15; Sprint 6 = 24; Sprint 7 = 21; Sprint 8 = 1.
- Layouts/partials/components herdam a autorização do consumidor; a matriz não atribui permissão nova a nenhum template.

### Auxiliares criados pela migração (fora da baseline 95)

| Template Django | Rota / view consumidora | Perfil autorizado | Layout pai | Referência Duralux | Sprint |
|---|---|---|---|---|---|
| `accounts/auth_base.html` | base de autenticação, MFA e erros | herda o consumidor público/autenticado | HTML completo | família `auth-*-minimal` | 3 |
| `accounts/mfa_enroll.html` | `/accounts/mfa/enroll/` `mfa_enroll` | membro autenticado em cadastro/reinício MFA | `accounts/auth_base.html` | `auth-verify-minimal` | 3 |
| `components/duralux_field.html` | formulários migrados de contas, clínica, agenda, diário e metas | herda o consumidor | partial, sem layout próprio | formulários `settings-*` e `customers-create` | 4–7 |

## Registro de evidência de migração

### Sprint 4 — implementada, correções revisadas, gate global bloqueado

Checkpoint vigente: `sprint4-corrective-verification.md`. Corrigidos shell comprimido, landmarks duplicados, wrappers de checkbox, widgets de paciente/onboarding, contraste e foco. A revisão corretiva foi aprovada por escopo; o gate completo falhou por defeito OAuth preexistente. A evidência abaixo é histórica e não representa aceite integral. O novo partial `components/duralux_field.html` é auxiliar criado pela migração, fora da baseline de 95 templates.

Os 15 templates abaixo usam a fundação Duralux/Bootstrap local, possuem título
explícito, não contêm estilo ou script inline e não usam os identificadores
visuais legados guardados por `tests/test_sprint4_duralux_templates.py`:

- `workspace/home.html`;
- `analytics/clinic_panel.html`;
- `analytics/patient_dashboard.html`;
- `analytics/report_list.html`;
- `analytics/therapist_dashboard.html`;
- `therapist_dashboard/home.html`;
- `clinics/confirm_switch.html`;
- `clinics/setup.html`;
- `clinics/whitelabel_domains.html`;
- `people/patient_detail.html`;
- `people/patient_form.html`;
- `people/patient_list.html`;
- `people/professional_list.html`;
- `onboarding/clinic_checklist.html`;
- `onboarding/patient_onboarding.html`.

Evidência atual: 71 testes focados passaram nas suítes de contrato Duralux,
analytics, dashboard terapêutico, pessoas, onboarding, clínica e staticfiles.
Revisão visual executada em 1280 × 720 e 375 × 812 para rotas representativas
de todos os grupos, sem overflow horizontal; o dashboard terapêutico preserva
gráfico progressivo e tabela textual equivalente. O estado só muda para
`migrado` após revisão independente e gate global frescos.
