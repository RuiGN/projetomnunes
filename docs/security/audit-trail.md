# Trilha de auditoria

Versão: 1.0
Responsável: Security Engineering

## Escopo

A trilha registra operações sensíveis realizadas ou tentadas sem copiar conteúdo clínico. A taxonomia técnica cobre login, troca de clínica, leitura, criação, alteração, exportação, consentimento, revogação, permissão, exclusão e consulta da própria auditoria.

## Integridade e segregação

Cada evento recebe sequência monotônica por clínica, HMAC do evento e HMAC anterior. A gravação bloqueia a clínica durante o append para serializar a cadeia. O serviço também atualiza um checkpoint terminal autenticado, contendo a última sequência e o último HMAC. Managers comuns exigem `clinic_id`; atualização e exclusão por instância ou queryset são negadas. A verificação de integridade detecta lacuna, ligação quebrada, alteração fora das interfaces comuns e exclusão da cauda ou da cadeia completa.

A chave `AUDIT_INTEGRITY_KEY` é obrigatória em desenvolvimento e produção, deve ser independente do banco e do `DJANGO_SECRET_KEY` e deve permanecer em cofre ou KMS. A cadeia autenticada evidencia adulteração por um agente com acesso somente ao banco, mas não substitui controles de infraestrutura. A identidade de runtime deve ter apenas `INSERT` e `SELECT` nas tabelas de auditoria; `UPDATE` do checkpoint deve ficar restrito ao procedimento de append. A identidade de migração permanece separada e seu uso é auditado.

## Minimização

São persistidos data UTC, clínica, ator quando disponível, ação, tipo e identificador técnico do recurso, resultado, correlação da requisição e digest HMAC da origem de rede. Texto clínico, payload, credencial, token e endereço IP em claro são proibidos.

## Consulta e exportação

A consulta exige membership vigente com papel `clinic_admin`, sempre aplica escopo de clínica e permite filtros por período, ator, recurso, ação e resultado. Tentativas negadas, consultas autorizadas e exportações geram novos eventos. O CSV contém somente campos técnicos minimizados.

## Retenção

`AUDIT_RETENTION_DAYS` define a retenção própria e usa 2.190 dias como baseline até aprovação jurídica. O evento grava `retention_until` no append. Expurgo futuro deve ser executado por processo privilegiado, segregado e comprovado; o aplicativo comum permanece append-only. Legal hold e prazos regulatórios prevalecem sobre o baseline quando formalmente aprovados.
