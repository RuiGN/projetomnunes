# Termos e consentimentos versionados

## Escopo

O domínio `consents` mantém documentos publicados por clínica e manifestações explícitas de aceite ou recusa. Documentos contratuais obrigatórios, ciência de limites e autorizações opcionais permanecem separados por tipo, finalidade, público e versão.

## Invariantes

- Toda consulta comum exige `clinic_id` por `objects.for_clinic(...)`.
- Apenas associação ativa com papel `clinic_admin` publica documentos.
- Cada publicação preserva conteúdo, finalidade, vigência, público, consequência da recusa, alternativa e contato institucional em um hash SHA-256 canônico.
- Documento publicado não aceita alteração ou exclusão por `save()`, `delete()`, `QuerySet.update()` ou `QuerySet.delete()`; mudanças exigem nova versão.
- Manifestações são append-only, sequenciais por documento e titular, vinculadas ao hash exato da publicação e idempotentes por `request_id` dentro da clínica.
- Evidências técnicas são resumidas com HMAC; IP e identificação do cliente não são persistidos em texto claro no registro de consentimento.
- O serviço aceita somente manifestação do próprio titular. Representação permanece bloqueada até a entrega do vínculo validado prevista em 8.4.5; texto enviado pelo cliente nunca comprova representação.
- Recusa bloqueia somente a finalidade configurada. Direitos básicos, incluindo histórico de consentimento, solicitações de privacidade, exportação e eliminação, independem de consentimento opcional.
- Finalidades desconhecidas são negadas por padrão.

## Interface

A central `/consents/` apresenta separadamente aceites necessários e autorizações opcionais. Nenhuma decisão vem pré-selecionada. Cada documento mostra finalidade, consequência da recusa, alternativa e contato da clínica. A submissão usa CSRF, escolha explícita e chave idempotente oculta.

## Auditoria

Publicação registra `create` sobre `consent_document`. Decisões registram `consent_accept` ou `consent_refuse` sobre `consent_manifestation`, sempre com clínica, ator, recurso, resultado e correlação, sem copiar conteúdo do documento.

## Verificação

A suíte `tests/test_versioned_consents.py` cobre isolamento multi-tenant, autorização, integridade e imutabilidade, evidência minimizada, representação fail-closed, idempotência, sequência append-only, público, versão vigente, interface sem preseleção, recusa por finalidade e preservação de direitos básicos.
