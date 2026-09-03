# Progresso do projeto

## Estado atual

- Sprint 8 — Agenda, consultas, lembretes e comunicação: TECNICAMENTE CONCLUÍDA (8.8.1–8.8.5, todos [X]).
  Liberação regulada aguarda 8.3.6.3 (aceite clínico e jurídico/regulatório da matriz normativa).
- Sprint 7 — Metas, baixa energia e exercícios terapêuticos: TECNICAMENTE CONCLUÍDA (8.7.1–8.7.5).
- Sprint 6 — Diário emocional e check-in: TECNICAMENTE CONCLUÍDA (8.6.1–8.6.5).
- Sprints 1–5 concluídas.
- Próximo item do backlog: Sprint 9 — Dashboards e relatórios MVP (8.9.1).

## Evidências por item da Sprint 8

- Domínio `scheduling` criado (services/selectors/policies/events/forms/views/urls + storage,
  delivery_templates, operating_hours), registrado em INSTALLED_APPS, config/urls (`/agenda/`),
  guarda arquitetural AST e pyproject (coverage + mypy). Dependências permitidas: audit, clinics,
  core, goals, people.
- 8.8.1: `Service`, `Unit`, `Room`, `AvailabilityPattern`, `AvailabilityOverride`, `ScheduleBlock`
  com constraints; `free_slots()` com aritmética UTC (DST-safe); view semanal `/agenda/semana/`
  com grade responsiva + lista textual equivalente.
- 8.8.2: máquina de estados de consulta, `AppointmentEvent` append-only, idempotência, reserva
  atômica (`select_for_update` + checagem de sobreposição), remarcação/cancelamento preservando
  histórico e liberando horário.
- 8.8.3: `ReminderPreference` (silêncio/antecedência/máximo diário), `Reminder` idempotente +
  cancelamento, `schedule_reminder` genérico com supressão de não-essenciais em modo baixa
  energia (via `goals.selectors.patient_profile_low_energy_active`), `snooze_reminder`,
  `delivery_templates` neutros, `NotificationEvent` sem payload sensível.
- 8.8.4: `Conversation` (clinical/administrative) com vínculo ativo obrigatório, `Message`
  imutável, `MessageReadReceipt` idempotente, paginação do histórico, aviso de não emergência e
  resposta fora do expediente (`operating_hours` + `clinics.selectors.clinic_operating_hours`).
- 8.8.5: `MessageAttachment` com validação de tipo real e quarentena, armazenamento privado
  (`PrivateAttachmentStorage` em `PRIVATE_MEDIA_ROOT`), download por view autorizada com
  scan-gate, exclusão restrita ao uploader/admin e auditoria de upload/acesso/exclusão via
  `audit.services.record_audit_event`.
- Novos seletores públicos: `people.selectors.linked_therapists_for_patient`,
  `goals.selectors.patient_profile_low_energy_active`, `clinics.selectors.clinic_operating_hours`.

## Evidências atuais

- Suíte completa: 583 testes aprovados, 1 ignorado (concorrência só no PostgreSQL).
  - tests/test_scheduling.py: 30 testes (disponibilidade/DST/bloqueio, máquina de estados,
    idempotência, autorização, lembretes + adiamento/canal/consentimento/fuso/baixa energia,
    mensagens + paginação, anexos + auditoria, calendário semanal, fluxos HTTP).
- Ruff (check + format) aprovados; mypy aprovado em 249 arquivos-fonte.
- Django system check aprovado; `makemigrations --check --dry-run` sem alterações pendentes.
- Verificação arquitetural AST aprovada com `scheduling` registrado.

## Pendências externas

- 8.3.1 permanece aberto até aprovação documentada do controlador e jurídico/regulatório.
- 8.3.6.3 permanece aberto até aceite clínico e jurídico/regulatório da matriz normativa.
- Liberação regulada das Sprints 6, 7 e 8 depende de 8.3.6.3.
