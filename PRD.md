# PRD — Plataforma Modular de Acompanhamento Terapêutico e Gestão de Clínicas

**Versão:** 1.0  
**Data:** 31/08/2026  
**Fonte funcional:** `PROMPT.prd`  
**Referência visual obrigatória:** ativos próprios em `static/` e inventário interno em `/design-system/`  
**Estado:** em desenvolvimento — Sprints 1–13 concluídas tecnicamente (6, 7, 8 e 9 com liberação regulada pendente do aceite clínico/jurídico em 8.3.6.3); Sprint 14 é o próximo incremento  

---

## 1. Visão do produto

### 1.1 Propósito

Construir uma plataforma modular de cuidado contínuo que conecte pacientes, profissionais, clínicas e, quando autorizado, rede de apoio. O produto deve apoiar acompanhamento terapêutico, organização da rotina, adesão ao plano de cuidado, agenda, comunicação e operação clínica sem substituir avaliação profissional, atendimento de emergência ou decisão clínica humana.

### 1.2 Problema

O acompanhamento entre consultas costuma ficar disperso em mensagens, planilhas, anotações e aplicativos sem contexto clínico. Pacientes têm dificuldade para registrar evolução e executar pequenas ações; profissionais perdem visibilidade longitudinal; clínicas operam agenda, cobrança, documentos e comunicação em ferramentas desconectadas.

### 1.3 Proposta de valor

1. Oferecer ao paciente uma jornada simples, personalizada e controlada por consentimento.
2. Dar ao profissional visão longitudinal apenas dos dados autorizados.
3. Centralizar a operação da clínica com segregação de dados por organização.
4. Permitir ativação comercial de módulos sem expor recursos irrelevantes.
5. Aplicar IA somente como assistência organizacional, sempre com limites explícitos e revisão humana nos fluxos profissionais.

### 1.4 Princípios do produto

1. **Privacidade por padrão:** registros privados permanecem invisíveis a profissionais e administradores clínicos sem base legal e autorização aplicável.
2. **Cuidado sem coerção:** lembretes, gamificação e recaídas usam linguagem não punitiva.
3. **Humano no controle:** o sistema não diagnostica, prescreve, muda medicação, interpreta testes psicológicos nem decide condutas clínicas.
4. **Modularidade:** cada clínica habilita módulos por plano e por jornada do paciente.
5. **Acessibilidade desde a base:** fluxos essenciais devem atender WCAG 2.2 nível AA.
6. **Rastreabilidade:** ações sensíveis devem registrar autoria, momento, contexto e organização.
7. **Emergência fora do aplicativo:** comunicação e alertas devem informar claramente horários de monitoramento e canais de emergência.

---

## 2. Objetivos, métricas e critérios de sucesso

### 2.1 Objetivos de negócio

1. Validar o acompanhamento entre consultas com pacientes e profissionais reais.
2. Converter clínicas para planos modulares recorrentes.
3. Reduzir trabalho operacional em agenda, lembretes, cobrança e relatórios.
4. Sustentar expansão para especialidades sem duplicar a plataforma-base.

### 2.2 Objetivos do usuário

1. Paciente registra um check-in em até 60 segundos.
2. Paciente controla, por registro, o que é privado ou compartilhado.
3. Profissional identifica pendências e evolução semanal sem navegar por telas desconectadas.
4. Administrador configura unidade, equipe, módulos, marca e cobrança em um único painel.

### 2.3 Indicadores-alvo para validação

1. Pelo menos 60% dos pacientes convidados concluem o onboarding.
2. Pelo menos 50% dos pacientes ativos realizam três ou mais check-ins por semana.
3. Pelo menos 70% das consultas são confirmadas ou canceladas antes do horário configurado pela clínica.
4. Pelo menos 70% dos profissionais-piloto consultam o resumo semanal antes da sessão.
5. Taxa de erro inferior a 1% nos fluxos de check-in, agenda e aceite de consentimento.
6. Zero vazamento conhecido entre clínicas e zero exibição de registro marcado como privado a usuário não autorizado.

### 2.4 Critérios para encerramento do MVP

1. Paciente, profissional e administrador concluem seus fluxos críticos em desktop e mobile.
2. Consentimento, autorização, auditoria e isolamento por clínica possuem testes automatizados.
3. Diário, check-in, metas, atividades, agenda, comunicação e painel de evolução funcionam de ponta a ponta.
4. Avisos de não emergência e limites clínicos aparecem nos pontos de risco.
5. Monitoramento, backup e procedimento de resposta a incidentes estão operacionais.

---

## 3. Perfis e jornadas

### 3.1 Paciente

Pessoa que registra informações, executa atividades, acompanha metas, agenda consultas e escolhe o compartilhamento. Pode possuir responsável legal e recursos simplificados de acessibilidade.

### 3.2 Psicólogo ou terapeuta

Profissional que acompanha pacientes vinculados, configura atividades e questionários, consulta informações autorizadas, registra evolução e gerencia agenda. As permissões devem respeitar profissão, vínculo e unidade.

### 3.3 Administrador da clínica

Responsável por unidades, profissionais, módulos, identidade visual, licenças, agenda central, financeiro e auditoria administrativa. Não recebe acesso automático a conteúdo clínico.

### 3.4 Familiar, responsável ou rede de apoio

Usuário convidado para visualizar somente categorias e itens explicitamente autorizados, sujeito a regras especiais para menores e responsáveis legais.

### 3.5 Supervisor clínico

Profissional com acesso temporário ou permanente, restrito a pacientes e categorias definidos pela clínica, com finalidade, prazo e auditoria.

### 3.6 Operador financeiro ou recepção

Usuário administrativo com acesso a agenda, cadastro operacional e cobrança, sem acesso a diário, anotações clínicas ou prontuário salvo permissão regulatoriamente válida.

---

## 4. Escopo e priorização

### 4.1 Fase 1 — MVP

1. Pacientes, profissionais, clínicas e controle de acesso.
2. Consentimentos e preferências de compartilhamento.
3. Onboarding e avaliação inicial configurável.
4. Diário emocional e check-in diário.
5. Metas, etapas e atividades terapêuticas.
6. Agenda, consultas e lembretes.
7. Comunicação assíncrona com limites de disponibilidade.
8. Painel de evolução e resumo para a próxima consulta.

### 4.2 Fase 2 — Comercial

1. Administração de unidades, equipes, licenças e módulos.
2. Financeiro, pagamentos, repasses e inadimplência.
3. Conteúdo, cursos e trilhas.
4. White label e domínio personalizado.
5. Relatórios operacionais avançados.
6. WhatsApp, calendários e videoconferência.

### 4.3 Fase 3 — Especializações

1. Hábitos, rotina e modo dia difícil.
2. Medicamentos como lembrete e registro, nunca prescrição.
3. Sono, atividade física e bem-estar.
4. Sobriedade e prevenção de recaídas.
5. Rede de apoio, espiritualidade opcional e grupos moderados.
6. Prontuário e documentos condicionados à validação normativa.

### 4.4 Fase 4 — Inteligência e integrações

1. IA assistiva com revisão humana e rastreabilidade.
2. Relatórios correlacionais sem causalidade clínica automática.
3. API pública, webhooks, CSV e integrações com dispositivos.
4. PWA, sincronização offline e preparação para aplicativos móveis.
5. White label avançado para grandes redes.

### 4.5 Fora de escopo sem aprovação clínica, jurídica e regulatória

1. Diagnóstico automático ou atuação como terapeuta virtual.
2. Prescrição, alteração de dose ou recomendação de interrupção de medicamento.
3. Interpretação automática de testes psicológicos.
4. Predição autônoma de suicídio ou recaída.
5. Alerta clínico enviado pela IA sem regra aprovada e validação humana.
6. Ranking público de saúde mental, sobriedade, humor ou adesão.
7. Mensagens privadas não moderadas entre pacientes quando a política do grupo as proibir.

---

## 5. Requisitos funcionais consolidados

### 5.1 Identidade, cadastro e consentimento

1. Cadastro individual ou por convite com expiração e uso único.
2. Perfil de paciente, profissional, responsável e equipe administrativa.
3. Vínculos entre clínica, unidade, profissional, paciente e rede de apoio.
4. Consentimento versionado, granular, revogável e exportável.
5. Exportação e exclusão de conta conforme base legal e retenção obrigatória.

### 5.2 Acompanhamento terapêutico

1. Diário multimodal com humor, emoções, contexto, gatilhos, pensamentos, reações e estratégias.
2. Check-in configurável com escalas e observações.
3. Metas de diferentes prazos, etapas mínimas, revisão e histórico.
4. Atividades e questionários criados pelo profissional, com versionamento.
5. Semáforo de compartilhamento verde, amarelo e vermelho aplicado por registro.
6. Preparação e encerramento de consulta.

### 5.3 Agenda e comunicação

1. Agenda por paciente, profissional, sala e unidade.
2. Marcação, confirmação, remarcação, cancelamento, recorrência e lista de espera.
3. Lembretes com horário de silêncio, frequência e adiamento.
4. Mensagens clínicas e administrativas separadas.
5. Aviso persistente de que o canal não atende emergências.

### 5.4 Clínica, documentos e financeiro

1. Unidades, equipe, permissões, especialidades, salas, convênios e módulos.
2. Prontuário, evolução, anexos, modelos, assinatura, autoria, bloqueio e retenção.
3. Preços, sessões, pacotes, recorrência, Pix, cartão, boleto e link de pagamento.
4. Inadimplência, estorno, repasse, comissão, recibo, nota fiscal por integração e relatórios.

### 5.5 Especializações e diferenciais

1. Hábitos, rotina adaptativa e modo baixa energia.
2. Registro de medicação, horários, adesão, estoque e efeitos percebidos.
3. Sono, bem-estar, atividade física e correlações descritivas.
4. Sobriedade, fissura, estratégias, plano de prevenção e registro não punitivo de recaída.
5. Rede de apoio, plano de segurança, cartões de enfrentamento e cápsula de motivação.
6. Conteúdo, espiritualidade opcional, comunidades moderadas e gamificação responsável.

---

## 6. Requisitos não funcionais

### 6.1 Segurança e LGPD

1. TLS em trânsito e criptografia de campos ou volumes sensíveis em repouso.
2. Isolamento multi-tenant obrigatório em consultas, jobs, cache, arquivos e relatórios.
3. RBAC com escopo por clínica, unidade, vínculo profissional e categoria de dado.
4. MFA para profissionais e administradores; biometria apenas como recurso do dispositivo cliente.
5. Auditoria imutável de leitura e alteração de dados sensíveis.
6. Sessões e dispositivos gerenciáveis com encerramento remoto.
7. Backups criptografados, restauração testada e política formal de retenção.
8. Dados de teste sintéticos ou anonimizados; dados reais são proibidos fora de ambientes autorizados.
9. O projeto deve manter uma matriz normativa versionada, como fonte de verdade no repositório, contemplando as normas, resoluções, notas técnicas e orientações vigentes do Sistema Conselhos de Psicologia aplicáveis ao produto, incluindo o Conselho Federal de Psicologia e o Conselho Regional de Psicologia da 2ª Região — Pernambuco. Para cada obrigação, a matriz deve registrar ato normativo, artigo ou dispositivo, vigência, histórico de revogação ou substituição, escopo e jurisdição, aplicabilidade ao produto, requisito funcional ou técnico derivado, evidência de conformidade, teste ou procedimento de verificação, risco de descumprimento, tarefa do backlog relacionada, responsável pelo aceite e data da última revisão. A matriz deve ser revisada a cada versão do produto, antes da liberação de funcionalidade regulada e sempre que houver publicação, alteração ou revogação de norma aplicável; funcionalidades reguladas não podem ser liberadas sem aceite documentado dos responsáveis clínico e jurídico/regulatório.

### 6.2 Desempenho e disponibilidade

1. Percentil 95 inferior a 500 ms para leituras comuns, excluindo integrações externas e geração pesada de relatórios.
2. Fluxos críticos devem manter mensagem de erro recuperável e impedir duplicidade por reenvio.
3. Jobs externos devem usar idempotência, retentativa com atraso e fila de falhas.
4. Meta inicial de disponibilidade mensal de 99,5%, evoluindo conforme contratos comerciais.

### 6.3 Acessibilidade e experiência

1. WCAG 2.2 AA para navegação, contraste, foco, teclado, leitor de tela e mensagens de erro.
2. Alvos de toque com tamanho adequado e formulários com rótulos programáticos.
3. Suporte a redução de movimento, alto contraste e tamanho de texto ampliado.
4. Ícones relevantes sempre acompanhados de texto ou nome acessível.
5. Conteúdo clínico em linguagem simples, sem infantilização ou tom punitivo.

### 6.4 Qualidade e operação

1. Testes unitários, integração, autorização, acessibilidade e jornadas críticas.
2. Logs estruturados sem conteúdo clínico, tokens, documentos ou segredos.
3. Métricas técnicas e de produto com anonimização e minimização.
4. Implantação gradual, feature flags, rollback e registro de versão.

### 6.5 Idioma, nomenclatura e padrões do backend

1. Todo o frontend, incluindo navegação, formulários, validações, notificações, e-mails, mensagens e conteúdo exibido ao usuário, deve usar português do Brasil (`pt-BR`).
2. Todo o backend deve usar inglês americano (`en-US`) em nomes de módulos, classes, funções, variáveis, campos, tabelas, constraints, índices, enums, eventos, filas, endpoints, payloads, logs técnicos, testes e documentação técnica.
3. O código Python deve seguir PEP 8, com formatação e lint automatizados no pipeline; nomes públicos devem ser claros, descritivos e consistentes com o domínio em inglês.
4. Textos do frontend devem permanecer em catálogos de tradução; regras de negócio não devem comparar ou persistir rótulos traduzidos.
5. Valores persistidos e contratos de API devem usar identificadores estáveis em inglês; a interface traduz esses valores para PT-BR.
6. Django signals podem ser usados quando necessários para efeitos colaterais desacoplados, como auditoria, invalidação de cache ou publicação de eventos. Regras centrais, autorização e transações de negócio devem permanecer em serviços explícitos.
7. Todo signal deve ter responsabilidade única, execução idempotente, registro explícito no carregamento da aplicação, prevenção de recursão e testes que cubram disparo, falha e repetição.

---

## 7. Design system

### 7.1 Fonte de verdade

A referência visual auditada está em `design_system_duralux/`; somente o subconjunto aprovado e mantido pelo aplicativo pode ser publicado em `static/duralux/` e apresentado no inventário interno `/design-system/`. A base usa Duralux com Bootstrap 5, tokens do produto e comportamento progressivo em JavaScript próprio. Novos componentes devem adaptar essa base ao contexto terapêutico sem depender de protótipos externos nem copiar textos, dados de demonstração ou identidade do fornecedor.

### 7.2 Tecnologias e ativos identificados

1. **Camada de utilitários:** responsividade, temas e estados visuais consolidados em `static/duralux/css/product-integration.css`.
2. **JavaScript próprio:** sidebar, dropdowns, modais, configurações de layout, direção e tema.
3. **ApexCharts:** gráficos dos painéis e relatórios.
4. **Fontes:** pilha nativa do sistema operacional, sem download externo e sem deslocamento causado por webfont.
5. **Iconografia:** símbolos decorativos ficam ocultos de tecnologias assistivas; ações ambíguas sempre possuem texto visível ou nome acessível.
6. **Logotipos e imagens:** ativos de marca devem pertencer ao aplicativo, ser substituíveis por clínica e nunca reutilizar logos, fundos ou avatares de demonstração.

### 7.3 Tokens visuais extraídos

1. **Primária roxa:** `rgb(106 105 245)` / `#6A69F5` — ações principais, foco e destaques.
2. **Sucesso:** `rgb(80 205 137)` / `#50CD89` — conclusão confirmada e estado positivo; não usar como julgamento clínico.
3. **Perigo:** `rgb(241 65 108)` / `#F1416C` — erro, exclusão e alerta operacional; evitar alarmismo em conteúdo emocional.
4. **Aviso:** `rgb(255 199 0)` / `#FFC700` — atenção e estado pendente.
5. **Informação:** `rgb(0 158 247)` / `#009EF7` — orientação e informação neutra.
6. **Texto escuro:** `rgb(21 21 21)` / `#151515`.
7. **Texto secundário:** `rgb(148 152 154)` / `#94989A`.
8. **Fundo claro principal:** `#F9FBFD`; superfícies em branco com bordas de preto a 10%.
9. **Tema escuro:** reutilizar `dark`, `darklight`, `darkborder` e `darkmuted` do CSS compilado, preservando contraste AA.

### 7.4 Tipografia

1. Família principal: fontes do sistema com fallback `sans-serif`.
2. Corpo padrão: 14–16 px, peso 400 e altura de linha mínima de 1,5 em textos longos.
3. Rótulos e ações: peso 500 ou 600.
4. Títulos: pesos 600 ou 700, com hierarquia sem depender apenas do tamanho.
5. Escalas de humor e instruções clínicas não devem usar texto inferior a 14 px.

### 7.5 Layout e componentes

1. Estrutura administrativa com sidebar vertical recolhível, topbar de 60 px e conteúdo rolável.
2. Layout `detached` disponível para painéis amplos; layout vertical como padrão.
3. Cards com borda discreta, cantos arredondados, espaçamento interno consistente e versão escura.
4. Formulários, checkbox, radio, switches, validação, tabelas, paginação, badges, alertas, tabs, accordions, dropdowns, tooltips e progress bars devem partir dos exemplos do kit.
5. Modais ficam restritos a decisões focadas; fluxos longos usam página ou painel lateral para permitir recuperação, acessibilidade e navegação mobile.
6. ApexCharts deve ter rótulos textuais, resumo alternativo e tabela acessível quando comunicar evolução.
7. Estados obrigatórios: carregando, vazio, erro recuperável, sucesso, sem permissão, offline e conteúdo privado.

### 7.6 Regras específicas do domínio

1. **Semáforo de compartilhamento:** verde significa compartilhável, amarelo exige confirmação antes de compartilhar e vermelho permanece privado. Cor deve vir acompanhada de ícone e texto.
2. **Modo baixa energia:** reduz densidade, mostra uma ação principal por vez e não remove acesso a ajuda.
3. **Modo crise:** interface simplificada, contatos em primeiro plano, confirmação antes de localização e aviso de não emergência.
4. **Gamificação:** celebrar progresso sem punição visual, perda humilhante, ranking público ou sequência irreversível.
5. **Gráficos clínicos:** comunicar tendência descritiva, período, dados ausentes e origem; não apresentar diagnóstico ou causalidade.

### 7.7 Critérios de aceite do design system

1. Componentes novos têm variantes claro/escuro, mobile/desktop, teclado e leitor de tela.
2. Cores semânticas não são o único meio de comunicar estado.
3. Foco visível usa contraste AA e não é removido por CSS.
4. Textos e dados de demonstração do template Duralux não chegam à produção.
5. Toda tela possui ação principal clara e estados de carregamento, vazio e erro.
6. Testes visuais cobrem larguras de 360 px, 768 px, 1280 px e 1536 px.

---

## 8. Lista de tarefas por sprints

### 8.0 Convenções do backlog

1. Cada sprint representa um incremento demonstrável e potencialmente implantável.
2. A tarefa-pai só recebe `[X]` quando todas as suas subtarefas e critérios de aceite estiverem concluídos.
3. Itens marcados **Regulado** exigem aceite clínico/jurídico antes da liberação.
4. Todo incremento inclui testes automatizados, autorização multi-tenant, acessibilidade e documentação proporcional ao risco.
5. A duração sugerida é de duas semanas por sprint, ajustável após estimativa técnica.



## 8. Backlog de desenvolvimento — Sprints 1 a 5

### 8.1 Sprint 1 — Fundação Django 6.1 e arquitetura multi-tenant

**Objetivo:** estabelecer uma base técnica executável, modular e testável em Django 6.1, preparada para separar os dados de cada clínica e sustentar a evolução incremental do produto sem acoplamento entre domínios.

**Critérios de saída:**

- Aplicação Django 6.1 executa nos ambientes local e de testes com configuração externa e verificações automatizadas aprovadas.
- Módulos de negócio possuem fronteiras, responsabilidades e dependências documentadas.
- Toda requisição autenticada resolve uma clínica ativa e aplica isolamento de dados por `tenant_id`.
- Migrações iniciais, dados de referência e estratégia de testes estão reproduzíveis.
- Logs estruturados e tratamento de erros não expõem dados pessoais ou informações clínicas.

- [X] **8.1.1 — Inicializar a fundação do projeto Django 6.1.**
  **Escopo:** criar a estrutura-base do produto, com configurações por ambiente, dependências fixadas e convenções comuns para aplicações, templates, arquivos estáticos e testes. **Implementação:** adotar Django 6.1, Python compatível e PostgreSQL como banco transacional, separar configurações de base, desenvolvimento, teste e produção e carregar segredos exclusivamente por variáveis de ambiente ou cofre de segredos.
  - [X] **8.1.1.1** Definir a matriz de versões de Python, Django 6.1, PostgreSQL e dependências essenciais, com política de atualização e arquivo de bloqueio reproduzível; configurar formatação e lint automatizados para impor PEP 8 no pipeline.
  - [X] **8.1.1.2** Estruturar `settings` por ambiente, incluindo banco, cache, e-mail, idioma padrão do frontend `pt-BR`, fuso horário e armazenamento de arquivos; manter código e configuração técnica em inglês americano.
  - [X] **8.1.1.3** Configurar comandos de inicialização, verificações de saúde e validação obrigatória de variáveis de ambiente, com falha explícita para configuração ausente.
  - [X] **8.1.1.4** Criar testes de fumaça para inicialização, conexão com banco, carregamento de URLs e execução das verificações nativas do Django.

- [X] **8.1.2 — Definir a arquitetura modular orientada a domínios.**
  **Escopo:** separar capacidades de plataforma, identidade, clínicas, pessoas, consentimentos, auditoria e painel profissional, evitando regras clínicas em camadas genéricas. **Implementação:** organizar aplicações Django com contratos explícitos entre serviços, seletores de consulta, formulários, políticas de autorização e eventos de domínio, sem acesso cruzado informal a modelos internos.
  - [X] **8.1.2.1** Delimitar os módulos `core`, `tenancy`, `accounts`, `clinics`, `people`, `consents`, `audit` e `therapist_dashboard`, com responsabilidade e proprietário técnico definidos.
  - [X] **8.1.2.2** Estabelecer convenções PEP 8 para models, transactional services, selectors, forms, views, URLs, templates e asynchronous tasks; usar Django signals apenas para efeitos colaterais desacoplados, idempotentes e testados.
  - [X] **8.1.2.3** Documentar dependências permitidas entre módulos e impedir ciclos por verificação arquitetural na integração contínua.
  - [X] **8.1.2.4** Definir eventos de domínio mínimos para criação de clínica, convite, vínculo profissional-paciente, consentimento e revogação.

- [X] **8.1.3 — Implementar o núcleo multi-tenant por clínica.**
  **Escopo:** garantir que clínicas compartilhem a infraestrutura sem compartilhar registros, permissões, arquivos ou contexto de navegação. **Implementação:** representar a clínica como tenant, associar registros sensíveis por chave obrigatória, resolver o tenant no início da requisição e exigir consultas delimitadas ao contexto ativo.
  - [X] **8.1.3.1** Modelar `Clinic` e `ClinicMembership` com identificador estável, status, slug único, datas de vigência e regras de ativação.
  - [X] **8.1.3.2** Criar middleware de resolução do tenant por associação autenticada e seleção explícita, rejeitando tenant ausente, inativo ou não autorizado.
  - [X] **8.1.3.3** Implementar managers e seletores tenant-aware que exijam `clinic_id` e bloqueiem consultas globais em fluxos comuns da aplicação.
  - [X] **8.1.3.4** Cobrir com testes tentativas de leitura, alteração, enumeração e associação de objetos pertencentes a outra clínica.

- [X] **8.1.4 — Preparar persistência, migrações e dados de referência.**
  **Escopo:** tornar a evolução do esquema previsível e segura desde o primeiro ciclo, incluindo chaves, índices, integridade e dados mínimos de desenvolvimento. **Implementação:** criar migrações pequenas e reversíveis, restrições no banco para invariantes multi-tenant e fábricas de dados sintéticos sem informações reais de pacientes.
  - [X] **8.1.4.1** Definir modelo abstrato de identificação e temporalidade com UUID, `created_at`, `updated_at` e autoria quando aplicável.
  - [X] **8.1.4.2** Criar restrições compostas por clínica para unicidade de slugs, documentos normalizados, vínculos e demais identificadores locais ao tenant.
  - [X] **8.1.4.3** Estabelecer revisão obrigatória de migrações destrutivas, plano de reversão e validação automatizada de migrações pendentes.
  - [X] **8.1.4.4** Disponibilizar fábricas e comando de carga de dados fictícios para clínica, profissionais e pacientes, identificados visualmente como demonstração.

- [X] **8.1.5 — Instituir qualidade, testes e observabilidade da base.**
  **Escopo:** criar mecanismos mínimos para detectar regressões técnicas, falhas operacionais e violações de isolamento antes da expansão funcional. **Implementação:** automatizar lint, tipos, testes, cobertura de caminhos críticos, logs estruturados, correlação de requisições e monitoramento de saúde sem registrar conteúdo clínico.
  - [X] **8.1.5.1** Configurar pipeline com formatação, análise estática, verificação de tipos, testes, migrações e checagens de segurança do Django.
  - [X] **8.1.5.2** Definir pirâmide de testes com unidades, integração de banco e fluxos HTTP, incluindo suíte dedicada ao isolamento multi-tenant.
  - [X] **8.1.5.3** Padronizar logs JSON com `request_id`, `tenant_id`, ator pseudonimizado, evento, resultado e latência, vedando payloads clínicos e credenciais.
  - [X] **8.1.5.4** Implementar páginas de erro e endpoints de saúde para aplicação e dependências, com respostas seguras e rastreáveis.

### 8.2 Sprint 2 — Design system Duralux e experiência-base

**Objetivo:** transformar os ativos Duralux em um sistema visual reutilizável, responsivo e acessível para as jornadas profissionais, usando Bootstrap 5, JavaScript próprio e ApexCharts sem duplicar componentes ou incorporar lógica clínica à apresentação.

**Critérios de saída:**

- Tokens e componentes-base reproduzem a identidade Duralux com fontes do sistema e iconografia textual.
- Layouts vertical e detached funcionam em telas suportadas, nos modos claro e escuro.
- Cards, tabelas e formulários possuem estados completos, navegação por teclado e mensagens acessíveis.
- JavaScript próprio cobre somente interações progressivas, mantendo ações essenciais utilizáveis no servidor.
- ApexCharts apresenta dados agregados com alternativa textual e não sugere diagnóstico ou decisão clínica automatizada.

- [X] **8.2.1 — Consolidar tokens e ativos do design system Duralux.**
  **Escopo:** inventariar e normalizar cores, tipografia, espaçamento, elevação, bordas, ícones e estados visuais mantidos pelo aplicativo. **Implementação:** consolidar a camada de utilitários em `static/duralux/css/product-integration.css`, mapear tokens semânticos em `static/duralux/css/product-integration.css` e encapsular fontes e ícones locais, preservando consistência entre claro, escuro e personalizações futuras por clínica.
  - [X] **8.2.1.1** Registrar paleta semântica para fundo, superfície, texto, borda, marca, sucesso, atenção, erro e informação nos modos claro e escuro.
  - [X] **8.2.1.2** Configurar fontes do sistema nos pesos 400, 500, 600 e 700, com fallback legível e estratégia de carregamento sem deslocamento excessivo.
  - [X] **8.2.1.3** Integrar iconografia textual com catálogo de usos, tamanho mínimo, rótulo acessível e proibição de ícones isolados em ações ambíguas.
  - [X] **8.2.1.4** Criar página interna de referência com tokens, tipografia, ícones e exemplos de contraste aprovados.

- [X] **8.2.2 — Construir os layouts vertical e detached.**
  **Escopo:** disponibilizar estruturas de navegação reutilizáveis para desktop, tablet e celular, com cabeçalho, menu lateral, conteúdo e contexto da clínica ativa. **Implementação:** criar templates Django compostos por blocos e componentes, usar JavaScript próprio para abertura e recolhimento do menu e persistir preferências visuais sem expor dados sensíveis.
  - [X] **8.2.2.1** Implementar layout vertical com menu lateral responsivo, item ativo, breadcrumbs e área principal dimensionada para tabelas e formulários.
  - [X] **8.2.2.2** Implementar layout detached com fundo e superfícies Duralux, mantendo a mesma hierarquia semântica e rotas do layout vertical.
  - [X] **8.2.2.3** Criar seletor de clínica e identificação do usuário no cabeçalho, exibindo somente associações autorizadas e confirmação ao trocar de contexto.
  - [X] **8.2.2.4** Validar foco, escape, bloqueio de rolagem e leitura por tecnologia assistiva no menu móvel e nos elementos expansíveis.

- [X] **8.2.3 — Padronizar cards, tabelas e estados de conteúdo.**
  **Escopo:** fornecer componentes para resumos, listagens e indicadores administrativos sem transformar sinais de uso em conclusões clínicas. **Implementação:** criar partials parametrizados para cards e tabelas, com estados de carregamento, vazio, erro, sem permissão e paginação processada no servidor.
  - [X] **8.2.3.1** Criar card-base com título, descrição, valor, tendência opcional, ação contextual e semântica neutra para indicadores.
  - [X] **8.2.3.2** Criar tabela responsiva com cabeçalhos associados, ordenação indicada, filtros, paginação, ações por linha e alternativa em cartões no celular.
  - [X] **8.2.3.3** Definir componentes de estado vazio, ausência de resultados, indisponibilidade, erro e acesso restrito com orientações acionáveis.
  - [X] **8.2.3.4** Documentar limites de densidade, truncamento, datas, fuso horário e mascaramento de identificadores pessoais nas listagens.

- [X] **8.2.4 — Padronizar formulários e validação acessível.**
  **Escopo:** uniformizar entrada e revisão de dados cadastrais e administrativos, reduzindo erros e exposição acidental de informações pessoais. **Implementação:** renderizar formulários Django com componentes Duralux/Bootstrap, validação no servidor como fonte de verdade e JavaScript próprio apenas para revelação progressiva e feedback imediato não autoritativo.
  - [X] **8.2.4.1** Criar componentes para texto, seleção, data, telefone, documento, textarea, checkbox, radio, switch e upload com rótulos e ajuda persistentes.
  - [X] **8.2.4.2** Vincular erros aos campos por `aria-describedby`, produzir resumo de erros no topo e direcionar foco ao primeiro problema após envio.
  - [X] **8.2.4.3** Definir máscaras como auxílio visual sem alterar o valor canônico, aceitando colagem e entrada por tecnologias assistivas.
  - [X] **8.2.4.4** Implementar prevenção de envio duplicado, aviso de alterações não salvas e confirmação específica para ações destrutivas.

- [X] **8.2.5 — Integrar tema, interações JavaScript próprio e gráficos ApexCharts.**
  **Escopo:** disponibilizar modo claro/escuro, preferências de layout e visualizações gráficas consistentes, responsivas e compreensíveis. **Implementação:** manter estado visual em store JavaScript próprio, respeitar preferências do sistema e criar adaptador ApexCharts que receba séries agregadas já autorizadas pelo backend.
  - [X] **8.2.5.1** Implementar alternância claro/escuro com detecção inicial do sistema, persistência local e prevenção de flash de tema incorreto.
  - [X] **8.2.5.2** Persistir preferência entre vertical e detached por usuário, com valor padrão administrável e restauração segura quando o layout não estiver disponível.
  - [X] **8.2.5.3** Criar configuração ApexCharts para cores semânticas, contraste, tooltips, datas, responsividade e atualização coerente ao trocar de tema.
  - [X] **8.2.5.4** Fornecer resumo textual e tabela equivalente para cada gráfico, rotulando métricas como registros ou engajamento, nunca como diagnóstico automatizado.

### 8.3 Sprint 3 — Segurança, LGPD e auditoria

**Objetivo:** incorporar privacidade, segurança e conformidade profissional desde a arquitetura, definindo controles verificáveis para dados pessoais e dados pessoais sensíveis, rastreabilidade de acessos, resposta a incidentes compatível com a LGPD e governança das normas aplicáveis do CFP e do CRP-02/PE.

**Critérios de saída:**

- Inventário de dados, finalidades, bases legais, responsáveis e prazos de retenção está aprovado para o escopo inicial.
- Matriz normativa CFP/CRP-02 está versionada, vinculada ao backlog e aprovada pelos responsáveis clínico e jurídico/regulatório para o escopo inicial.
- Controles de aplicação, infraestrutura e arquivos reduzem acesso indevido e exposição de segredos.
- Eventos relevantes geram trilha de auditoria íntegra, consultável por escopo e sem conteúdo clínico desnecessário.
- Fluxos operacionais atendem solicitações de acesso, correção, portabilidade, revogação e eliminação conforme regras aplicáveis.
- Plano de incidentes, restauração e continuidade foi exercitado com dados sintéticos.

- [X] **8.3.1 — Mapear dados e requisitos de privacidade pela LGPD.**
  **Escopo:** classificar os dados tratados pela plataforma e ligar cada coleta a finalidade, base legal, acesso permitido, retenção e descarte. **Implementação:** manter registro estruturado das operações de tratamento e aplicar minimização como requisito de aceite de modelos, formulários, logs, relatórios e integrações.
  - [X] **8.3.1.1** Revisar e aprovar o inventário de dados cadastrais, profissionais, regulatórios, de contato, consentimento, uso e informações clínicas declaradas, identificando dados pessoais sensíveis e evidências exigidas pelo CFP e pelo CRP competente.
  - [X] **8.3.1.2** Confirmar finalidade, necessidade, base legal, controlador, operador, destinatários e prazo de retenção para cada categoria do MVP, com aceite jurídico/regulatório e do controlador aplicável.
  - [X] **8.3.1.3** Revisar os fluxos de entrada, armazenamento, consulta, exportação, compartilhamento e descarte, incluindo fornecedores, fiscalização profissional, prontuário, registro documental e materiais de acesso restrito.
  - [X] **8.3.1.4** Atualizar e aprovar o checklist de privacidade para novas funcionalidades, vedando coleta genérica, uso secundário implícito e campos sensíveis sem justificativa e bloqueando incrementos regulados sem evidência e aceite exigidos.

- [X] **8.3.2 — Aplicar controles técnicos de proteção.**
  **Escopo:** proteger dados em trânsito, em repouso, em sessão, em arquivos e em operações administrativas. **Implementação:** exigir HTTPS, cookies seguros, proteção CSRF, cabeçalhos de segurança, criptografia gerenciada, rotação de segredos e acesso mínimo aos serviços e bancos.
  - [X] **8.3.2.1** Configurar TLS obrigatório, HSTS, cookies `Secure`, `HttpOnly` e `SameSite`, CSP, proteção contra framing e política restritiva de referrer.
  - [X] **8.3.2.2** Separar credenciais por ambiente, impedir segredos no repositório, definir rotação e limitar permissões de contas de serviço.
  - [X] **8.3.2.3** Proteger armazenamento de anexos com chaves privadas, URLs temporárias, validação de tipo e tamanho e varredura antes da disponibilização.
  - [X] **8.3.2.4** Definir criptografia de banco, backups e campos de risco elevado, com gerenciamento de chaves independente dos dados protegidos.

- [X] **8.3.3 — Implementar trilha de auditoria imutável.**
  **Escopo:** registrar quem realizou ou tentou operações relevantes, em qual clínica, sobre qual recurso e com qual resultado, sem copiar conteúdo clínico para o log. **Implementação:** emitir eventos de auditoria a partir dos serviços de domínio, armazená-los de forma append-only e restringir consulta e exportação por autorização específica.
  - [X] **8.3.3.1** Definir taxonomia para login, troca de clínica, visualização, criação, alteração, exportação, consentimento, revogação, permissão e exclusão.
  - [X] **8.3.3.2** Registrar data UTC, tenant, ator, ação, tipo e identificador do recurso, resultado, origem de rede tratada e correlação da requisição.
  - [X] **8.3.3.3** Impedir atualização e exclusão por interfaces comuns, detectar lacunas ou adulteração e aplicar retenção própria aos eventos.
  - [X] **8.3.3.4** Criar consulta por período, ator, recurso, ação e resultado, com exportação controlada e auditoria da própria consulta.

- [X] **8.3.4 — Implementar direitos do titular e ciclo de vida dos dados.**
  **Escopo:** operacionalizar solicitações relacionadas a confirmação, acesso, correção, portabilidade, revogação e eliminação, respeitando obrigações legais e registros que devam ser preservados. **Implementação:** criar fluxo rastreável com validação de identidade, análise de escopo, prazo, aprovação e evidência de execução por clínica.
  - [X] **8.3.4.1** Criar registro de solicitação com tipo, titular, canal, datas, responsável, decisões, pendências e comprovante de conclusão.
  - [X] **8.3.4.2** Gerar exportação estruturada e legível somente após reautenticação, com arquivo criptografado, expiração e evento de auditoria.
  - [X] **8.3.4.3** Aplicar anonimização ou exclusão segura conforme política, preservando apenas dados exigidos e documentando a justificativa de retenção.
  - [X] **8.3.4.4** Propagar correções, revogações e exclusões aplicáveis a cópias, arquivos e operadores integrados, registrando confirmação de cada destino.

- [X] **8.3.5 — Preparar resposta a incidentes, backup e continuidade.**
  **Escopo:** definir ações coordenadas para suspeita ou confirmação de acesso indevido, indisponibilidade, perda de dados e comprometimento de credenciais. **Implementação:** manter runbook com classificação, contenção, preservação de evidências, comunicação, recuperação e revisão, além de backups criptografados testados.
  - [X] **8.3.5.1** Definir níveis de severidade, responsáveis, canais seguros, critérios de escalonamento e acionamento jurídico e de proteção de dados.
  - [X] **8.3.5.2** Documentar contenção de conta, sessão, integração, chave e tenant, preservando evidências e cadeia de custódia.
  - [X] **8.3.5.3** Estabelecer critérios e conteúdo para comunicação a clínicas, titulares e autoridade competente quando aplicável.
  - [X] **8.3.5.4** Executar teste de restauração isolada com dados sintéticos e simulação de incidente, registrando tempos, falhas e ações corretivas.

- [X] **8.3.6 — Instituir governança de conformidade profissional CFP/CRP-PE.** **Regulado**
  **Escopo:** transformar as obrigações profissionais aplicáveis em requisitos verificáveis e impedir que funcionalidades reguladas avancem sem fundamento normativo, evidência e aceite. **Implementação:** manter uma matriz normativa versionada no repositório, relacionar cada dispositivo a riscos, requisitos, testes e tarefas do backlog e estabelecer revisão contínua com responsáveis clínico e jurídico/regulatório.
  - [X] **8.3.6.1** Criar a matriz normativa versionada e registrar, para o escopo inicial, atos vigentes, dispositivos aplicáveis, jurisdição, vigência e histórico de alteração, revogação ou substituição do CFP e do CRP-02/PE.
  - [X] **8.3.6.2** Mapear cada obrigação para requisito funcional ou técnico, risco de descumprimento, evidência de conformidade, teste ou procedimento de verificação e tarefa correspondente do backlog.
  - [X] **8.3.6.3** Obter e registrar o aceite dos responsáveis clínico e jurídico/regulatório para a matriz inicial, incluindo pendências, exceções, prazo de revisão e decisão explícita de liberação ou bloqueio.
  - [X] **8.3.6.4** Automatizar a verificação de completude e revisão da matriz no pipeline, bloqueando funcionalidades marcadas como reguladas quando faltarem norma aplicável, evidência, teste, responsável ou aceite vigente.

### 8.4 Sprint 4 — Autenticação, papéis e consentimentos

**Objetivo:** entregar acesso seguro e rastreável para profissionais e administradores, com papéis limitados ao contexto de cada clínica e gestão versionada de consentimentos, sem presumir autorização para dados clínicos.

**Critérios de saída:**

- Cadastro por convite, login, recuperação e encerramento de sessões funcionam com proteções contra abuso.
- Papéis e permissões são avaliados no backend por clínica e por vínculo com o recurso.
- Acesso privilegiado exige autenticação multifator e permite revogação de sessões.
- Consentimentos exibem finalidade e versão, registram manifestação inequívoca e aceitam revogação prospectiva.
- Matriz de autorização e testes negativos cobrem acessos entre clínicas, papéis e pacientes sem vínculo.

- [X] **8.4.1 — Implementar identidade, convite e autenticação.**
  **Escopo:** permitir entrada controlada de usuários profissionais e administrativos, evitando cadastro aberto em nome de uma clínica. **Implementação:** usar modelo de usuário customizado desde a primeira migração, convite de uso único e autenticação por e-mail normalizado, com mensagens que não permitam enumerar contas.
  - [X] **8.4.1.1** Modelar usuário customizado com UUID, e-mail canônico, nome, status, datas de segurança e ausência de papel global implícito.
  - [X] **8.4.1.2** Criar convite associado à clínica, papel inicial, emissor, destinatário, validade, uso único e revogação auditável.
  - [X] **8.4.1.3** Implementar login e logout com limitação de tentativas, mensagens genéricas, rotação de sessão e redirecionamento ao tenant autorizado.
  - [X] **8.4.1.4** Implementar recuperação de acesso por token curto e descartável, invalidando sessões existentes quando a credencial for redefinida.

- [X] **8.4.2 — Proteger sessões, dispositivos e autenticação multifator.**
  **Escopo:** reduzir risco de sequestro de sessão e exigir proteção adicional para funções com acesso a dados sensíveis ou administração. **Implementação:** manter sessões com duração e ociosidade configuráveis, registrar dispositivos de forma minimizada e oferecer TOTP com códigos de recuperação protegidos.
  - [X] **8.4.2.1** Definir expiração absoluta e por inatividade, renovação segura, invalidação após eventos críticos e reautenticação para ações de alto impacto.
  - [X] **8.4.2.2** Exibir sessões ativas com data, cliente e localização aproximada opcional, permitindo encerramento individual ou global.
  - [X] **8.4.2.3** Implementar ativação TOTP com confirmação, códigos de recuperação de uso único e fluxo administrativo de recuperação auditado.
  - [X] **8.4.2.4** Exigir multifator para administradores e acessos privilegiados, com período de implantação explícito e sem bypass silencioso.

- [X] **8.4.3 — Definir papéis e matriz de permissões por clínica.**
  **Escopo:** representar responsabilidades de administrador da clínica, terapeuta e equipe administrativa sem conceder acesso clínico por conveniência operacional. **Implementação:** combinar associação à clínica, papel, permissão granular e vínculo ao recurso; toda decisão autoritativa deve ocorrer no backend.
  - [X] **8.4.3.1** Definir matriz de ações para administrar clínica, gerenciar profissionais, cadastrar pacientes, visualizar dados cadastrais, acessar informações clínicas e consultar auditoria.
  - [X] **8.4.3.2** Implementar papéis iniciais `clinic_admin`, `therapist` e `administrative_staff`, com menor privilégio e permissões explícitas.
  - [X] **8.4.3.3** Criar políticas reutilizáveis para tenant ativo, membership vigente, papel, vínculo profissional-paciente e estado do registro.
  - [X] **8.4.3.4** Testar negação por ausência de cada condição, alteração manual de URL, identificador de outro tenant e tentativa de elevar o próprio papel.

- [X] **8.4.4 — Implementar termos e consentimentos versionados.**
  **Escopo:** registrar aceite ou recusa de termos e consentimentos específicos, diferenciando obrigações contratuais, ciência de limites e autorizações opcionais. **Implementação:** versionar documentos publicados, apresentar finalidade e consequências de modo separado e armazenar evidência da manifestação vinculada ao usuário, clínica e versão.
  - [X] **8.4.4.1** Modelar documento com tipo, título, versão, conteúdo íntegro, vigência, público, obrigatoriedade e hash de publicação.
  - [X] **8.4.4.2** Modelar manifestação com decisão, data, versão, finalidade, ator, titular representado quando aplicável e evidência técnica minimizada.
  - [X] **8.4.4.3** Criar interface que proíba caixas opcionais pré-marcadas e separe aceite obrigatório de autorização de comunicação ou compartilhamento.
  - [X] **8.4.4.4** Bloquear apenas a finalidade dependente quando houver recusa, apresentando alternativa e contato da clínica sem impedir acesso indevido a direitos básicos.

- [X] **8.4.5 — Implementar revogação, representação e revisão de acesso.**
  **Escopo:** permitir retirar consentimentos opcionais, tratar representação legal e revisar periodicamente privilégios e vínculos. **Implementação:** aplicar revogação prospectiva, preservar histórico, encerrar compartilhamentos afetados e submeter exceções de representação a validação administrativa documentada.
  - [X] **8.4.5.1** Criar fluxo de revogação com confirmação de escopo, data de efeito, impacto explicado e evento de auditoria.
  - [X] **8.4.5.2** Invalidar autorizações e acessos derivados, notificando sistemas integrados e responsáveis operacionais quando necessário.
  - [X] **8.4.5.3** Registrar responsável legal com tipo de vínculo, evidência, vigência, poderes concedidos e revisão, sem inferir capacidade civil automaticamente.
  - [X] **8.4.5.4** Disponibilizar revisão de memberships, papéis, vínculos e consentimentos vencidos, com suspensão segura e relatório de exceções.

### 8.5 Sprint 5 — Cadastros, onboarding e área inicial do terapeuta

**Objetivo:** permitir que a clínica configure sua operação inicial, cadastre profissionais e pacientes com dados mínimos, conclua um onboarding orientado e ofereça ao terapeuta uma visão inicial de sua carteira e pendências, sem classificação ou diagnóstico automatizado.

**Critérios de saída:**

- Administrador autorizado configura clínica e profissionais respeitando isolamento e minimização de dados.
- Paciente pode ser cadastrado com vínculo, contato e preferências essenciais, inclusive nome social e acessibilidade.
- Onboarding registra progresso, consentimentos e limites do aplicativo, com retomada segura.
- Terapeuta visualiza somente pacientes vinculados e indicadores operacionais baseados em fatos registrados.
- Painel e listagens funcionam nos layouts Duralux, em claro/escuro, com estados acessíveis e gráficos acompanhados de alternativa textual.

- [X] **8.5.1 — Implementar cadastro e configuração inicial da clínica.**
  **Escopo:** coletar dados institucionais e preferências indispensáveis para operar o tenant, sem antecipar módulos comerciais fora do escopo. **Implementação:** oferecer formulário em etapas para identificação, contatos, endereço, fuso, identidade visual básica e módulos habilitados, com validação, auditoria e pré-visualização.
  - [X] **8.5.1.1** Cadastrar razão social ou nome institucional, nome de exibição, documento aplicável, contatos administrativos e endereço estruturado.
  - [X] **8.5.1.2** Configurar fuso horário, idioma, canais institucionais, horários de atendimento e mensagem de orientação fora do expediente.
  - [X] **8.5.1.3** Aplicar logotipo e cores permitidas sobre os tokens Duralux, validando contraste nos modos claro e escuro.
  - [X] **8.5.1.4** Selecionar módulos disponíveis no tenant com padrão mínimo seguro, registrar autoria da mudança e impedir ativação sem requisitos prévios.

- [X] **8.5.2 — Implementar cadastro de profissionais e vínculos.**
  **Escopo:** manter perfis profissionais e associações com clínicas sem misturar identidade de acesso, dados públicos e credenciais profissionais. **Implementação:** criar perfil profissional ligado ao usuário, especialidades declaradas, registro profissional quando aplicável e membership com papel e vigência.
  - [X] **8.5.2.1** Cadastrar nome, nome social, contatos profissionais, foto opcional, apresentação e preferências de acessibilidade.
  - [X] **8.5.2.2** Registrar categoria, especialidades declaradas e conselho, número e jurisdição quando aplicáveis, sem afirmar validação inexistente.
  - [X] **8.5.2.3** Associar profissional à clínica com papel, unidade, datas de início e término, status e responsável pela autorização.
  - [X] **8.5.2.4** Implementar listagem por status, papel e especialidade, com ações de convite, suspensão e reativação sujeitas a permissão.

- [X] **8.5.3 — Implementar cadastro mínimo de pacientes e vínculo terapêutico.**
  **Escopo:** permitir cadastro manual e por convite, coletando apenas dados necessários à identificação, contato, cuidado e acessibilidade no estágio inicial. **Implementação:** criar perfil tenant-aware separado da conta de acesso, normalizar identificadores, detectar possíveis duplicidades dentro da clínica e exigir vínculo explícito com profissional.
  - [X] **8.5.3.1** Cadastrar nome, nome social, data de nascimento, gênero opcional, contatos, idioma, fuso e preferências de acessibilidade.
  - [X] **8.5.3.2** Registrar endereço, contato de emergência e responsável legal apenas quando necessários, com finalidade e visibilidade indicadas no formulário.
  - [X] **8.5.3.3** Criar convite por link ou e-mail com validade, uso único e associação segura ao perfil preexistente, sem expor sua existência.
  - [X] **8.5.3.4** Vincular paciente a um ou mais profissionais com função, período, status e autorização, auditando criação, transferência e encerramento.

- [X] **8.5.4 — Entregar onboarding orientado da clínica e do paciente.**
  **Escopo:** guiar a preparação operacional e a entrada do paciente, incluindo objetivos declarados, preferências e ciência sobre os limites da plataforma. **Implementação:** usar fluxo em etapas com salvamento no servidor, retomada segura, progresso explícito e campos condicionais, sem questionário que produza diagnóstico ou estratificação clínica automatizada.
  - [X] **8.5.4.1** Criar checklist da clínica para completar perfil, convidar profissionais, publicar termos, configurar permissões e cadastrar ou convidar o primeiro paciente.
  - [X] **8.5.4.2** Coletar do paciente objetivos pessoais declarados, preferências de contato, acessibilidade e melhores horários para lembretes, todos revisáveis.
  - [X] **8.5.4.3** Apresentar termos, consentimentos e aviso de que a plataforma não substitui atendimento profissional nem serviço de emergência.
  - [X] **8.5.4.4** Permitir salvar, retomar e revisar cada etapa, mostrando pendências factuais e conclusão sem atribuir nota, risco ou diagnóstico.

- [X] **8.5.5 — Entregar a área inicial do terapeuta.**
  **Escopo:** oferecer uma página inicial operacional com pacientes vinculados, próximos compromissos quando disponíveis e pendências de cadastro ou consentimento, sem inferir estado clínico. **Implementação:** compor consultas tenant-aware e autorizadas em cards, tabela e gráficos ApexCharts agregados, com filtros, estados vazios e atalhos para ações permitidas.
  - [X] **8.5.5.1** Exibir cards de pacientes ativos vinculados, novos vínculos, cadastros incompletos e consentimentos pendentes, com definição visível de cada métrica.
  - [X] **8.5.5.2** Criar tabela de pacientes com busca, filtros por status e vínculo, paginação, última atividade factual e ações condicionadas à permissão.
  - [X] **8.5.5.3** Apresentar gráfico agregado de cadastros e atividade por período com ApexCharts, acompanhado de resumo textual e tabela acessível.
  - [X] **8.5.5.4** Implementar atalhos para cadastrar paciente, enviar convite, revisar pendências e abrir ficha autorizada, registrando acessos relevantes em auditoria.


### 8.6 Sprint 6 — Diário emocional e check-in

**Classificação:** **Regulado** — a liberação depende da conclusão de 8.3.6 e dos aceites clínico e jurídico/regulatório aplicáveis.

### Objetivo
Entregar o núcleo de acompanhamento diário do paciente, com diário emocional, check-in rápido e semáforo de compartilhamento granular, garantindo que conteúdo privado nunca seja exibido ao terapeuta e que qualquer alerta dependa de regra configurada e revisão humana.

### Critérios de saída
- Paciente cria, edita e consulta registros do diário e check-ins em telas responsivas, acessíveis por teclado e leitor de tela.
- Cada registro apresenta estado de compartilhamento Verde, Amarelo ou Vermelho, com explicação clara e histórico de alterações.
- Registros Vermelhos não são retornados em consultas, buscas, exportações ou painéis do terapeuta; Amarelos exigem consentimento explícito antes da liberação.
- Regras de sinalização clínica são configuráveis, geram apenas itens para triagem humana e não enviam alertas clínicos automáticos.
- Testes automatizados cobrem autorização, isolamento entre clínicas, acessibilidade dos fluxos críticos e estados vazios/erro.

- [X] **8.6.1 — Modelar registros do diário e privacidade por item.** Escopo: persistir humor, emoções, intensidade, contexto, texto reflexivo e visibilidade independente por registro. Implementação: criar entidades, migrações, políticas de acesso e serviços com isolamento por clínica e paciente.
  - [X] **8.6.1.1** Definir o schema `JournalEntry`, catálogo de emoções, intensidade de 1 a 5, datas de criação/edição e enum técnico `shareable|confirmation_required|private`, exibido no frontend como Verde, Amarelo e Vermelho.
  - [X] **8.6.1.2** Implementar validações de autoria, limites de texto, datas válidas e transições de visibilidade registradas em auditoria.
  - [X] **8.6.1.3** Aplicar política no backend que exclua itens Vermelhos de qualquer consulta do terapeuta e retenha itens Amarelos sem consentimento vigente.
  - [X] **8.6.1.4** Criar testes de autorização para paciente, terapeuta autorizado, terapeuta sem vínculo e usuário de outra clínica.

- [X] **8.6.2 — Construir experiência do diário emocional.** Escopo: permitir registro e revisão diária de humor, emoções, gatilhos, reações e estratégias utilizadas. Implementação: usar componentes Duralux com Bootstrap e JavaScript próprio, salvamento explícito e feedback acessível.
  - [X] **8.6.2.1** Criar formulário responsivo com escala de humor, seleção múltipla de emoções, intensidade, contexto, gatilhos, reações físicas e “o que me ajudou”.
  - [X] **8.6.2.2** Implementar calendário emocional por cores com alternativa textual, legenda, foco visível e navegação completa por teclado.
  - [X] **8.6.2.3** Exibir histórico do próprio paciente com filtros por período e emoção, estados vazio/carregando/erro e paginação.
  - [X] **8.6.2.4** Validar contraste, rótulos, mensagens de erro associadas aos campos e comportamento em 320 px, tablet e desktop.

- [X] **8.6.3 — Implementar semáforo de compartilhamento.** Escopo: tornar a decisão de compartilhamento compreensível, granular e reversível pelo paciente. Implementação: seletor visual e textual, confirmação contextual e autorização aplicada no servidor.
  - [X] **8.6.3.1** Exibir as opções Verde “pode compartilhar”, Amarelo “perguntar antes” e Vermelho “somente eu”, sem depender apenas de cor.
  - [X] **8.6.3.2** Solicitar confirmação ao mudar para Verde e registrar finalidade, vínculo profissional, instante e versão do consentimento.
  - [X] **8.6.3.3** Criar fluxo de solicitação para item Amarelo, com aceite ou recusa pelo paciente e expiração configurável da autorização.
  - [X] **8.6.3.4** Garantir revogação imediata e testar ausência do conteúdo revogado em cache, API, pesquisa, relatório e notificações.

- [X] **8.6.4 — Entregar check-in diário configurável.** Escopo: coletar rapidamente estado geral, ansiedade, tristeza, irritabilidade, energia, sono, motivação e observação opcional. Implementação: questionário versionado, resposta idempotente por período e interface de poucos passos.
  - [X] **8.6.4.1** Modelar perguntas, escalas, obrigatoriedade, ordem e versões por clínica, preservando a interpretação das respostas históricas.
  - [X] **8.6.4.2** Criar check-in responsivo com progresso, linguagem simples, opção “prefiro não responder” e confirmação antes do envio.
  - [X] **8.6.4.3** Implementar consulta do histórico pessoal e edição dentro da janela configurada, com trilha de auditoria da versão anterior.
  - [X] **8.6.4.4** Cobrir por testes duplicidade de envio, mudança de fuso horário, questionário desativado e interrupção com retomada segura.

- [X] **8.6.5 — Criar triagem humana para sinalizações configuradas.** Escopo: identificar respostas que atendam a regras da clínica sem diagnosticar, prometer monitoramento contínuo ou tratar mensagens como emergência. Implementação: motor determinístico configurável e fila de revisão profissional.
  - [X] **8.6.5.1** Permitir que administrador clínico configure limiares, combinação de respostas, vigência, responsáveis e horário de monitoramento.
  - [X] **8.6.5.2** Gerar item de triagem com dados mínimos autorizados, motivo legível e enum técnico `pending|in_review|closed`, traduzido no frontend, sem disparo clínico automático.
  - [X] **8.6.5.3** Exibir ao paciente aviso permanente de que o aplicativo e as mensagens não atendem emergências, com orientação para serviços locais e contatos definidos.
  - [X] **8.6.5.4** Registrar revisão, decisão e responsável humano em auditoria, testando que conteúdo Vermelho jamais integra a avaliação da regra.

### 8.7 Sprint 7 — Metas, baixa energia e exercícios terapêuticos

**Classificação:** **Regulado** — a liberação depende da conclusão de 8.3.6 e dos aceites clínico e jurídico/regulatório aplicáveis.

### Objetivo
Permitir que paciente e profissional autorizado organizem metas e exercícios terapêuticos, com compartilhamento controlado e um modo de baixa energia que reduza a carga sem punir interrupções nem produzir recomendações clínicas automáticas.

### Critérios de saída
- Metas privadas e compartilhadas suportam etapas, prazo, progresso, revisão e histórico de alterações.
- Modo baixa energia apresenta apenas ações mínimas previamente definidas e pode ser ativado ou encerrado pelo paciente.
- Profissional atribui exercícios de catálogo versionado e acompanha somente respostas autorizadas.
- Prazos e lembretes respeitam preferências, horário de silêncio e limites de frequência.
- Fluxos críticos possuem testes de permissão, versionamento, responsividade e acessibilidade.

- [X] **8.7.1 — Estruturar metas e etapas acompanháveis.** Escopo: cadastrar metas pessoais ou terapêuticas de curto, médio e longo prazo com prioridade, prazo e pequenas etapas. Implementação: entidades versionadas, cálculo de progresso e APIs com autorização por item.
  - [X] **8.7.1.1** Modelar goal, step, priority, due date, defining actor, visibility e enum técnico `active|paused|completed|archived`, com rótulos em PT-BR no frontend.
  - [X] **8.7.1.2** Calcular progresso pelas etapas concluídas, preservando histórico de reabertura, mudança de prazo e conclusão.
  - [X] **8.7.1.3** Aplicar as mesmas regras Verde, Amarelo e Vermelho ao acesso profissional, sem inferir compartilhamento por autoria conjunta.
  - [X] **8.7.1.4** Testar alterações concorrentes, prazo vencido, meta sem etapa e bloqueio de acesso após revogação.

- [X] **8.7.2 — Criar painel de metas do paciente.** Escopo: oferecer visão simples das prioridades, próximos passos, obstáculos e conquistas. Implementação: cartões Duralux, filtros JavaScript próprio e interações acessíveis sem recarregamento integral.
  - [X] **8.7.2.1** Construir lista responsiva por prioridade e prazo, com progresso textual, barra com nome acessível e estados vazios orientativos.
  - [X] **8.7.2.2** Implementar criação e edição guiadas, dividindo a meta em ações pequenas com validação de prazo e ordem.
  - [X] **8.7.2.3** Permitir registrar obstáculo, plano de ação e conclusão sem pontos negativos, perda de sequência ou linguagem punitiva.
  - [X] **8.7.2.4** Adicionar revisão semanal com resumo do próprio paciente e escolha explícita do que será compartilhado.

- [X] **8.7.3 — Implementar modo baixa energia.** Escopo: simplificar a jornada em dias difíceis com ações mínimas previamente escolhidas pelo paciente e profissional, sem substituir orientação de crise. Implementação: preferência temporária, conjunto versionado de ações e redução de notificações não essenciais.
  - [X] **8.7.3.1** Permitir configurar ações mínimas como beber água, abrir a janela ou realizar uma etapa curta, com autoria e consentimento registrados.
  - [X] **8.7.3.2** Criar ativação em um toque, confirmação não alarmista e tela simplificada com no máximo três ações prioritárias.
  - [X] **8.7.3.3** Suspender notificações não essenciais durante o período escolhido, mantendo consultas e lembretes explicitamente marcados como essenciais.
  - [X] **8.7.3.4** Oferecer encerramento manual, expiração automática e testes que comprovem ausência de diagnóstico ou escalonamento clínico automático.

- [X] **8.7.4 — Disponibilizar catálogo de exercícios terapêuticos.** Escopo: profissional cria, publica e atribui exercícios de reflexão, respiração, atenção plena e cartões de enfrentamento. Implementação: modelos versionados, status editorial e atribuições vinculadas ao paciente.
  - [X] **8.7.4.1** Modelar exercício com título, instruções, abordagem, duração estimada, formato de resposta, acessibilidade e versão publicada.
  - [X] **8.7.4.2** Criar editor profissional com rascunho, pré-visualização e publicação, impedindo alteração retroativa de uma versão já atribuída.
  - [X] **8.7.4.3** Implementar atribuição com frequência, prazo, observação e confirmação do paciente, limitada aos profissionais vinculados.
  - [X] **8.7.4.4** Incluir modelos iniciais revisáveis para respiração, autocompaixão, valores pessoais e resolução de problemas, sem recomendações automatizadas.

- [X] **8.7.5 — Entregar execução e acompanhamento de exercícios.** Escopo: paciente realiza atividade em texto ou seleção estruturada e decide o compartilhamento da resposta. Implementação: sessão retomável, respostas versionadas e comentários profissionais assíncronos.
  - [X] **8.7.5.1** Construir executor responsivo com instruções, estimativa de duração, salvamento de rascunho e retomada no último passo válido.
  - [X] **8.7.5.2** Aplicar semáforo separadamente à resposta, garantindo que a atribuição compartilhada não torne a execução automaticamente visível.
  - [X] **8.7.5.3** Permitir comentário profissional apenas em resposta autorizada e notificar o paciente sem incluir conteúdo sensível no texto da notificação.
  - [X] **8.7.5.4** Testar expiração de prazo, nova versão do exercício, resposta privada e navegação por teclado em todos os tipos de campo.

### 8.8 Sprint 8 — Agenda, consultas, lembretes e comunicação

**Classificação:** **Regulado** — a liberação depende da conclusão de 8.3.6 e dos aceites clínico e jurídico/regulatório aplicáveis.

### Objetivo
Entregar a coordenação operacional entre paciente, profissional e clínica por agenda, consultas, lembretes e mensagens assíncronas, deixando explícito que os canais não atendem emergências.

### Critérios de saída
- Agenda impede conflitos e permite solicitar, confirmar, remarcar e cancelar consultas conforme políticas configuradas.
- Lembretes são enviados por canais habilitados, respeitam consentimento, fuso horário, silêncio e limite de frequência.
- Comunicação clínica e administrativa permanece separada, com disponibilidade e aviso de não emergência visíveis.
- Anexos, notificações e histórico obedecem autorização, retenção e auditoria.
- Testes validam concorrência de horários, idempotência, permissões, acessibilidade e ausência de dados sensíveis em notificações.

- [X] **8.8.1 — Modelar disponibilidade e agenda profissional.** Escopo: representar horários de atendimento, bloqueios, duração, intervalos, unidade e sala. Implementação: regras recorrentes, exceções e consulta de disponibilidade em fuso horário consistente.
  - [X] **8.8.1.1** Criar entidades de disponibilidade, bloqueio, unidade, sala e exceção com validação de sobreposição.
  - [X] **8.8.1.2** Implementar geração de horários livres considerando duração do serviço, intervalo, feriados configurados e consultas existentes.
  - [X] **8.8.1.3** Exibir agenda diária e semanal responsiva com lista textual equivalente, foco visível e navegação por teclado.
  - [X] **8.8.1.4** Testar horário de verão, profissionais em fusos distintos, bloqueio parcial e duas reservas concorrentes do mesmo horário.

- [X] **8.8.2 — Implementar ciclo de vida da consulta.** Escopo: paciente solicita e clínica confirma, remarca ou cancela; presença e falta são registradas após o horário. Implementação: máquina de estados, política configurável e trilha de auditoria.
  - [X] **8.8.2.1** Definir estados e transições técnicas `requested|confirmed|reschedule_requested|canceled|completed|no_show`, com actor, timestamp e reason; apresentar os rótulos correspondentes em PT-BR.
  - [X] **8.8.2.2** Criar fluxo de solicitação e confirmação idempotente que reserve o horário atomicamente e apresente resumo antes da conclusão.
  - [X] **8.8.2.3** Implementar remarcação e cancelamento conforme antecedência configurada, preservando o histórico e liberando o horário corretamente.
  - [X] **8.8.2.4** Registrar presença ou falta apenas para perfis autorizados e testar todas as transições inválidas e operações repetidas.

- [X] **8.8.3 — Orquestrar lembretes e preferências.** Escopo: avisar sobre consulta, exercício e check-in sem excesso, exposição indevida ou envio fora do período permitido. Implementação: fila idempotente, templates neutros e central de preferências.
  - [X] **8.8.3.1** Criar preferências por tipo e canal, fuso horário, horário de silêncio, antecedência e frequência máxima diária.
  - [X] **8.8.3.2** Agendar lembretes com chave idempotente e cancelar eventos pendentes quando consulta ou tarefa mudar de estado.
  - [X] **8.8.3.3** Redigir templates que não revelem humor, respostas, exercício ou condição clínica na tela bloqueada, e registrar entrega sem conteúdo sensível.
  - [X] **8.8.3.4** Testar adiamento, canal indisponível, retirada de consentimento, modo baixa energia e mudança de fuso após agendamento.

- [X] **8.8.4 — Criar mensagens assíncronas separadas por canal.** Escopo: permitir conversas clínica e administrativa entre pessoas vinculadas, sem caracterizar atendimento emergencial. Implementação: threads tipadas, mensagens imutáveis, disponibilidade e resposta automática fora do expediente.
  - [X] **8.8.4.1** Modelar `Conversation` com enum técnico `clinical|administrative`, participants, messages, read status e retention policy, bloqueando participantes sem vínculo ativo e traduzindo o canal para PT-BR na interface.
  - [X] **8.8.4.2** Construir interface responsiva com histórico paginado, indicador de canal, horário de disponibilidade e confirmação de envio.
  - [X] **8.8.4.3** Exibir antes do primeiro envio e no cabeçalho o aviso “Este canal não atende emergências”, com orientação para serviços locais apropriados.
  - [X] **8.8.4.4** Configurar resposta fora do expediente sem prometer prazo incompatível e testar revogação de vínculo, leitura e isolamento entre clínicas.

- [X] **8.8.5 — Implementar anexos e notificações de comunicação.** Escopo: suportar anexos seguros e avisos de nova mensagem sem vazar conteúdo. Implementação: upload validado, armazenamento privado, URLs temporárias e eventos de notificação.
  - [X] **8.8.5.1** Restringir formatos, tamanho e quantidade; validar tipo real do arquivo e rejeitar conteúdo executável ou nome inseguro.
  - [X] **8.8.5.2** Armazenar anexos fora da área pública, aplicar verificação antimalware e liberar download apenas por URL temporária autorizada.
  - [X] **8.8.5.3** Enviar notificação neutra de nova mensagem, respeitando preferências e sem reproduzir texto, nome de arquivo ou informação clínica.
  - [X] **8.8.5.4** Auditar upload, acesso e exclusão e testar arquivo inválido, URL expirada, participante removido e falha de processamento.

### 8.9 Sprint 9 — Dashboards e relatórios MVP

**Classificação:** **Regulado** — a liberação depende da conclusão de 8.3.6 e dos aceites clínico e jurídico/regulatório aplicáveis.

### Objetivo
Transformar dados autorizados em visões úteis para paciente, profissional e clínica, com indicadores transparentes, acessíveis e minimizados, sem diagnóstico automatizado nem exposição de registros privados.

### Critérios de saída
- Paciente visualiza sua evolução de humor, check-ins, metas, exercícios e consultas no período selecionado.
- Profissional visualiza apenas pacientes vinculados e dados explicitamente compartilhados, com pendências de triagem humana separadas de indicadores.
- Clínica acessa métricas operacionais agregadas e anonimizadas conforme limiar mínimo configurado.
- Relatório MVP possui período, fonte, critérios de cálculo, data de geração e exportação segura.
- ApexCharts oferece tabelas alternativas, contraste, rótulos e navegação compatíveis com acessibilidade.

- [X] **8.9.1 — Definir camada de métricas e contratos de dados.** Escopo: padronizar cálculos de evolução, adesão, frequência e operação para uso consistente. Implementação: consultas agregadas, filtros obrigatórios de autorização e dicionário versionado de métricas.
  - [X] **8.9.1.1** Documentar fórmula, granularidade, população, período e limitações de cada indicador MVP.
  - [X] **8.9.1.2** Implementar serviços que filtrem primeiro por clínica, vínculo e consentimento antes de agregar qualquer dado individual.
  - [X] **8.9.1.3** Excluir registros Vermelhos e Amarelos não autorizados de séries, totais, tendências, relatórios e contagens indiretas.
  - [X] **8.9.1.4** Criar testes com conjuntos conhecidos para validar fórmulas, ausência de dados, revogação e isolamento multiclínica.

- [X] **8.9.2 — Construir dashboard de evolução do paciente.** Escopo: apresentar ao paciente seu humor, check-ins, progresso de metas, exercícios e frequência de consultas. Implementação: cards Duralux, ApexCharts e filtros de período sincronizados.
  - [X] **8.9.2.1** Criar resumo com frequência de check-ins, distribuição de humor, metas em andamento, exercícios concluídos e próximas consultas.
  - [X] **8.9.2.2** Implementar gráficos semanais e mensais com escala íntegra, legenda, valores no foco e tabela acessível equivalente.
  - [X] **8.9.2.3** Permitir comparação apenas com períodos do próprio paciente, explicando que associação visual não representa causalidade ou diagnóstico.
  - [X] **8.9.2.4** Tratar dados insuficientes, carregamento e erro sem inferências, testando responsividade, redução de movimento e contraste.

- [X] **8.9.3 — Construir dashboard do profissional.** Escopo: resumir pacientes vinculados, adesão autorizada, próximos atendimentos e fila de revisão. Implementação: lista filtrável, detalhe progressivo e controles de acesso no servidor.
  - [X] **8.9.3.1** Exibir pacientes ativos, próxima consulta, frequência de check-ins e atividades pendentes somente quando esses dados estiverem autorizados.
  - [X] **8.9.3.2** Separar visualmente sinalizações pendentes para revisão humana de indicadores comuns, mostrando regra, vigência e horário de monitoramento.
  - [X] **8.9.3.3** Criar filtros por período, status e profissional responsável sem busca textual sobre conteúdo privado do diário.
  - [X] **8.9.3.4** Testar vínculo encerrado, consentimento revogado, paciente de outra clínica e tentativa de acesso direto por identificador.

- [X] **8.9.4 — Entregar painel operacional da clínica.** Escopo: acompanhar pacientes ativos, ocupação, consultas realizadas, cancelamentos e faltas sem expor conteúdo clínico. Implementação: agregações por unidade e período com anonimização.
  - [X] **8.9.4.1** Calcular ocupação da agenda, taxa de faltas, cancelamentos e volume de pacientes ativos por unidade e profissional.
  - [X] **8.9.4.2** Aplicar limiar mínimo configurado para recortes agregados e ocultar combinações que permitam reidentificação.
  - [X] **8.9.4.3** Criar gráficos ApexCharts com tabela alternativa, exportação dos dados agregados e indicação da última atualização.
  - [X] **8.9.4.4** Validar fórmulas contra consultas de referência e testar perfis sem permissão administrativa e unidade sem movimento.

- [X] **8.9.5 — Gerar relatórios MVP e exportações seguras.** Escopo: produzir resumo individual autorizado para paciente/profissional e relatório operacional agregado para clínica. Implementação: geração assíncrona, arquivo temporário e auditoria.
  - [X] **8.9.5.1** Definir modelos com período, fontes, fórmulas, limitações, identidade da clínica e data/hora de geração.
  - [X] **8.9.5.2** Gerar relatório individual somente sob solicitação autorizada, reavaliando consentimento e vínculo no início e no download.
  - [X] **8.9.5.3** Gerar relatório clínico operacional apenas com dados agregados acima do limiar de anonimização, sem textos livres do paciente.
  - [X] **8.9.5.4** Disponibilizar arquivo por URL temporária, registrar geração/download e testar expiração, revogação e falha parcial do processamento.

### 8.10 Sprint 10 — Administração da clínica e início do financeiro

### Objetivo
Iniciar a fase comercial com administração segura de clínicas, unidades, profissionais e permissões, além de um contas a receber básico para preços e cobranças de consultas, sem processar pagamentos ou emitir documentos fiscais nesta etapa.

### Critérios de saída
- Administrador gerencia cadastro da clínica, unidades, salas, profissionais, especialidades e horários com isolamento multiclínica.
- Perfis e permissões seguem menor privilégio e todas as alterações administrativas relevantes são auditadas.
- Agenda central e painel operacional funcionam por unidade e profissional com os indicadores MVP da Sprint 9.
- Financeiro básico cadastra preços, gera cobranças por consulta e controla vencimento, pagamento manual, cancelamento e inadimplência.
- Dados financeiros são separados dos clínicos; pacientes e profissionais visualizam apenas o necessário para seu papel.

- [X] **8.10.1 — Criar cadastro da clínica, unidades e salas.** Escopo: manter identidade operacional, contatos, fuso, unidades físicas e recursos de agenda. Implementação: entidades com escopo de locatário, validações e telas administrativas Duralux.
  - [X] **8.10.1.1** Modelar clínica, unidade e sala com nome, documento identificador, contatos, endereço, fuso horário e status ativo/inativo.
  - [X] **8.10.1.2** Aplicar chave de clínica obrigatória em consultas e restrições de unicidade, impedindo referência cruzada entre locatários.
  - [X] **8.10.1.3** Construir CRUD responsivo com confirmação para inativação e bloqueio quando houver consulta futura vinculada.
  - [X] **8.10.1.4** Testar duplicidade, inativação, alteração de fuso, acesso por outra clínica e navegação completa por teclado.

- [X] **8.10.2 — Administrar profissionais, especialidades e vínculos.** Escopo: convidar profissionais, definir especialidades, unidades e horários de atuação. Implementação: convite com validade, vínculo versionado e ativação controlada.
  - [X] **8.10.2.1** Modelar profissional, especialidade, registro informado, vínculo com clínica, unidades permitidas e período de vigência.
  - [X] **8.10.2.2** Implementar convite de uso único com expiração, confirmação de identidade e ativação explícita pelo administrador.
  - [X] **8.10.2.3** Integrar unidades e horários permitidos à disponibilidade da agenda, rejeitando conflito com vínculo inativo.
  - [X] **8.10.2.4** Preservar histórico ao encerrar vínculo e testar que o profissional perde acesso imediato sem apagar registros auditáveis.

- [X] **8.10.3 — Implementar perfis, permissões e auditoria administrativa.** Escopo: separar administrador, recepção, financeiro e profissional clínico pelo menor privilégio. Implementação: RBAC explícito, checagem no backend e log imutável de eventos críticos.
  - [X] **8.10.3.1** Definir matriz de permissões para clínica, usuários, agenda, relatórios operacionais, financeiro e dados clínicos.
  - [X] **8.10.3.2** Impedir que recepção e financeiro acessem diário, check-in, respostas terapêuticas, mensagens clínicas ou anotações profissionais.
  - [X] **8.10.3.3** Registrar ator, ação, alvo, clínica, data, resultado e metadados mínimos em mudanças de permissão, vínculo, agenda e cobrança.
  - [X] **8.10.3.4** Criar testes por papel para interface, API, exportação e acesso direto, incluindo tentativa de elevação de privilégio.

- [X] **8.10.4 — Entregar agenda central e operação por unidade.** Escopo: permitir que recepção encontre horários, acompanhe consultas e lista de espera sem acessar dados clínicos. Implementação: visão consolidada, filtros autorizados e encaixe controlado.
  - [X] **8.10.4.1** Criar agenda central por dia e semana com filtros de unidade, profissional, sala, especialidade e estado da consulta.
  - [X] **8.10.4.2** Implementar lista de espera com preferência de período e unidade, ordem transparente e contato registrado sem detalhes clínicos.
  - [X] **8.10.4.3** Permitir preencher vaga cancelada após confirmação humana, validando disponibilidade e evitando reserva automática silenciosa.
  - [X] **8.10.4.4** Exibir ocupação e faltas do painel MVP por unidade, testando escopo da recepção e atualização após remarcação.

- [X] **8.10.5 — Iniciar financeiro com preços e contas a receber.** Escopo: cadastrar preço de serviço e acompanhar cobrança de consulta por registro manual, sem gateway, cartão, Pix, boleto, nota fiscal ou repasse nesta entrega. Implementação: livro de eventos financeiros separado e estados auditáveis.
  - [X] **8.10.5.1** Modelar service, effective price table, charge, due date, justified discount e enums técnicos `open|paid|overdue|canceled`, traduzidos para PT-BR no frontend.
  - [X] **8.10.5.2** Gerar cobrança idempotente a partir de consulta confirmada conforme configuração da clínica, preservando o preço vigente no momento da geração.
  - [X] **8.10.5.3** Criar telas de contas a receber e detalhe da cobrança com filtros por período, unidade e estado, sem qualquer conteúdo terapêutico.
  - [X] **8.10.5.4** Implementar baixa e cancelamento manuais com motivo, ator e auditoria, testando permissão financeira, duplicidade e reconciliação dos totais.


### 8.11 Sprint 11 — Operação financeira completa

### Objetivo
Entregar o ciclo financeiro ponta a ponta da plataforma, incluindo catálogo e contratação, cobrança, documentos fiscais, repasses, conciliação, estornos, inadimplência, relatórios e trilha de auditoria, com segregação por organização e sem armazenar dados sensíveis de cartão.

### Critérios de saída
- É possível contratar, renovar, alterar e cancelar planos com cálculo proporcional, cupons e período de teste, sem cobranças duplicadas.
- Cobranças, reembolsos, estornos, chargebacks e inadimplência são refletidos em um razão financeiro imutável e conciliável.
- Documentos fiscais e recibos têm situação rastreável e podem ser reprocessados de forma idempotente.
- Repasses a profissionais e clínicas possuem regras versionadas, memória de cálculo e aprovação antes da liquidação.
- Dashboards e exportações fecham com o razão; permissões, logs de auditoria, alertas e testes de integração estão ativos.

- [X] **8.11.1 — Catálogo comercial, assinaturas e ciclo de cobrança**
  - **Escopo:** disponibilizar planos, preços, cupons, períodos de teste e assinaturas para pacientes, profissionais e organizações, cobrindo contratação, upgrade, downgrade, renovação, pausa e cancelamento.
  - **Implementação:** modelar catálogo e contratos versionados; integrar o provedor de pagamentos por adapter; usar chaves de idempotência por operação; persistir eventos, tentativas e transições de estado em logs correlacionáveis.
  - [X] **8.11.1.1 —** Criar entidades e APIs para planos, itens de preço, recorrência, moeda, impostos, cupons, elegibilidade e vigência, com isolamento por organização e histórico de versões.
  - [X] **8.11.1.2 —** Implementar checkout tokenizado e gestão de assinaturas por adapter, sem persistir PAN ou CVV, com cálculo proporcional testado para upgrade, downgrade e cancelamento.
  - [X] **8.11.1.3 —** Processar webhooks de autorização, captura, falha e renovação com assinatura validada, chave idempotente, ordenação segura e registro do payload sanitizado.
  - [X] **8.11.1.4 —** Cobrir jornadas de contratação e renovação com testes unitários, contratuais e ponta a ponta, incluindo repetição de webhook, timeout do provedor e retomada após falha.

- [X] **8.11.2 — Cobranças avulsas, inadimplência, reembolsos e disputas**
  - **Escopo:** administrar cobranças por consulta ou serviço, retentativas, comunicação de inadimplência, reembolsos totais e parciais, estornos e chargebacks.
  - **Implementação:** criar uma máquina de estados financeira independente do provedor, executar operações por adapters e jobs idempotentes e registrar motivo, ator, origem, correlação e resultado de cada transição.
  - [X] **8.11.2.1 —** Implementar cobranças avulsas vinculadas a agendamento, pedido ou contrato, impedindo duplicidade por chave de negócio e validando valor, moeda e beneficiário.
  - [X] **8.11.2.2 —** Configurar régua de inadimplência com retentativas parametrizáveis, notificações consentidas, período de tolerância e bloqueios proporcionais sem interromper acesso a recursos críticos de segurança.
  - [X] **8.11.2.3 —** Implementar reembolso total e parcial, estorno e chargeback com saldos consistentes, justificativa obrigatória, autorização por perfil e evidência anexável.
  - [X] **8.11.2.4 —** Criar fila de exceções e alertas para cobranças órfãs, divergências de valor, webhook inválido e disputa vencida, com reprocessamento idempotente e logs pesquisáveis.

- [X] **8.11.3 — Razão financeiro, conciliação e fechamento**
  - **Escopo:** manter um livro-razão imutável de débitos e créditos, conciliar eventos internos com extratos dos provedores e executar fechamento por período e organização.
  - **Implementação:** adotar partidas dobradas, lançamentos append-only e referências causais; importar extratos por adapter; reconciliar automaticamente por identificadores e valores, com workflow auditável para divergências.
  - [X] **8.11.3.1 —** Definir plano de contas, lançamentos, saldos e vínculos com cobrança, reembolso, taxa, imposto, repasse e ajuste, proibindo alteração destrutiva de lançamentos liquidados.
  - [X] **8.11.3.2 —** Implementar importação incremental de extratos e liquidações por adapter, com cursor, checksum, idempotência por transação externa e retenção do arquivo de origem protegido.
  - [X] **8.11.3.3 —** Criar conciliação automática e manual com estados pendente, conciliado e divergente, tolerâncias explícitas e dupla aprovação para ajustes acima do limite organizacional.
  - [X] **8.11.3.4 —** Entregar fechamento diário e mensal com trava de período, reabertura autorizada, memória de alterações e testes que comprovem igualdade entre saldos, transações e extratos.

- [X] **8.11.4 — Repasses, comissões e documentos fiscais**
  - **Escopo:** calcular e liquidar repasses para profissionais e clínicas, aplicar comissões e taxas e emitir ou integrar documentos fiscais e recibos conforme configuração da organização.
  - **Implementação:** versionar regras de split e competência; separar cálculo, aprovação e pagamento; integrar provedores bancários e fiscais por adapters; garantir idempotência e logs em emissão, cancelamento e liquidação.
  - [X] **8.11.4.1 —** Criar regras de repasse por serviço, profissional, clínica e período, com taxas fixas ou percentuais, retenções, arredondamento determinístico e simulação antes da vigência.
  - [X] **8.11.4.2 —** Gerar lotes de repasse com memória de cálculo item a item, fluxo de aprovação, conta de destino validada e bloqueio de liquidação quando houver saldo ou cadastro inconsistente.
  - [X] **8.11.4.3 —** Integrar liquidação por adapter com chave idempotente por lote e beneficiário, retorno de situação, comprovante, retentativa segura e conciliação automática.
  - [X] **8.11.4.4 —** Integrar emissão, consulta, cancelamento e reprocessamento de nota fiscal ou recibo por adapter, armazenando número, competência, status, erros normalizados e log de auditoria.

- [X] **8.11.5 — Relatórios financeiros, controles e observabilidade**
  - **Escopo:** oferecer visão operacional e gerencial de receita, recebíveis, inadimplência, reembolsos, taxas, repasses e documentos fiscais, com exportações e controles de acesso.
  - **Implementação:** construir projeções derivadas do razão, filtros por organização e período, exportações assíncronas protegidas e métricas de saúde das integrações; auditar visualização, exportação e ações privilegiadas.
  - [X] **8.11.5.1 —** Criar dashboards de faturamento bruto e líquido, receita recorrente, contas a receber, inadimplência, estornos, chargebacks, taxas e repasses, com reconciliação numérica ao razão.
  - [X] **8.11.5.2 —** Implementar exportações CSV e XLSX com filtros persistidos, fuso horário e moeda explícitos, mascaramento de dados pessoais, expiração do arquivo e registro de quem gerou e baixou.
  - [X] **8.11.5.3 —** Aplicar permissões de menor privilégio e segregação de funções para consultar, ajustar, reembolsar, aprovar e liquidar, com autenticação reforçada nas ações de maior risco.
  - [X] **8.11.5.4 —** Publicar métricas e alertas de falhas, latência, backlog, duplicidade evitada e divergência financeira, além de executar testes de carga, recuperação e auditoria de isolamento entre organizações.

### 8.12 Sprint 12 — Conteúdo, cursos e operação white label

### Objetivo
Entregar uma plataforma de conteúdo e cursos com autoria, revisão clínica, publicação, consumo e acompanhamento, além de personalização white label segura e isolada por organização.

### Critérios de saída
- Conteúdos e cursos percorrem autoria, revisão, aprovação profissional, agendamento, publicação e arquivamento com histórico completo.
- Pacientes consomem trilhas acessíveis, retomam progresso entre dispositivos e recebem certificados somente após regras verificáveis.
- Recomendações clínicas não são publicadas nem atribuídas sem aprovação registrada de profissional habilitado.
- Cada organização configura marca, domínio, textos e comunicações sem acessar ou alterar dados de outro tenant.
- Conteúdo e configurações white label possuem métricas, moderação, auditoria, rollback e testes de acessibilidade e isolamento.

- [X] **8.12.1 — CMS, taxonomia e ciclo editorial**
  - **Escopo:** permitir criação e gestão de artigos, vídeos, áudios, exercícios e materiais anexos, com taxonomias, públicos, versões, autoria e agendamento editorial.
  - **Implementação:** criar modelo de conteúdo versionado, editor com sanitização, armazenamento de mídia por referências assinadas e workflow explícito de rascunho, revisão, aprovação, publicação e arquivamento.
  - [X] **8.12.1.1 —** Modelar conteúdo, versão, autor, idioma, categoria, tag, público, contraindicação, fonte, validade e organização proprietária, com APIs filtradas por permissão e tenant.
  - [X] **8.12.1.2 —** Implementar editor com blocos acessíveis, pré-visualização responsiva, sanitização contra conteúdo ativo indevido e upload com validação de tipo, tamanho, malware e metadados.
  - [X] **8.12.1.3 —** Criar workflow editorial com comentários, comparação de versões, aprovação, agendamento por fuso horário, expiração e rollback para versão previamente publicada.
  - [X] **8.12.1.4 —** Indexar somente versões publicadas na busca, respeitando idioma, público e organização, e testar autorização, sanitização, agendamento e invalidação de cache.

- [X] **8.12.2 — Cursos, trilhas e avaliações educacionais**
  - **Escopo:** estruturar cursos em módulos e aulas, organizar trilhas por objetivo, aplicar avaliações educacionais e emitir certificados de conclusão.
  - **Implementação:** modelar currículo versionado e pré-requisitos; registrar matrícula, progresso e tentativa de forma idempotente; separar avaliações educacionais de instrumentos clínicos e deixar essa distinção explícita na interface.
  - [X] **8.12.2.1 —** Criar APIs de curso, módulo, aula, trilha, pré-requisito, duração, instrutor e material complementar, com ordenação estável e publicação coordenada do currículo.
  - [X] **8.12.2.2 —** Implementar matrícula individual e por coorte, disponibilidade por período, limite de vagas e regras de acesso vinculadas a plano, organização ou convite.
  - [X] **8.12.2.3 —** Construir questionários educacionais com banco de questões, embaralhamento, tentativas, nota mínima e feedback explicativo, sem produzir diagnóstico ou decisão clínica automática.
  - [X] **8.12.2.4 —** Emitir certificado verificável após critérios de conclusão, com identificador público não previsível, revogação auditada e testes contra emissão duplicada ou conclusão indevida.

- [X] **8.12.3 — Experiência de aprendizagem, progresso e acessibilidade**
  - **Escopo:** oferecer consumo multiplataforma de conteúdo, retomada de progresso, favoritos, anotações privadas, legendas, transcrições e acompanhamento de conclusão.
  - **Implementação:** persistir eventos de aprendizagem idempotentes, consolidar progresso no servidor e disponibilizar mídia adaptativa por URLs temporárias; seguir WCAG 2.2 AA nos fluxos principais.
  - [X] **8.12.3.1 —** Implementar player de vídeo e áudio com legendas, transcrição, velocidade, navegação por teclado, controle de volume e retomada da última posição confirmada.
  - [X] **8.12.3.2 —** Registrar início, posição, conclusão e tempo ativo com identificador único por evento, rejeitando duplicatas e evitando contabilizar reprodução automática como engajamento.
  - [X] **8.12.3.3 —** Criar favoritos e anotações privadas com sincronização entre dispositivos, exportação pelo titular e exclusão conforme política de retenção.
  - [X] **8.12.3.4 —** Validar contraste, foco, leitores de tela, redimensionamento, legendas e navegação sem mouse em testes automatizados e sessões manuais documentadas.

- [X] **8.12.4 — Curadoria clínica, recomendações e governança de conteúdo**
  - **Escopo:** permitir curadoria e recomendação de conteúdos para pacientes e grupos, assegurando revisão clínica, validade, contraindicações e responsabilidade profissional.
  - **Implementação:** exigir credencial profissional válida e aprovação registrada antes de publicar ou atribuir qualquer recomendação clínica; manter regras como apoio à decisão, nunca como substituição do julgamento profissional.
  - [X] **8.12.4.1 —** Criar fila de revisão com especialidade requerida, evidências, referências, data de validade, parecer e assinatura eletrônica do profissional habilitado.
  - [X] **8.12.4.2 —** Bloquear publicação e recomendação clínica quando aprovação estiver ausente, vencida ou revogada, preservando histórico, motivo e impacto sobre atribuições existentes.
  - [X] **8.12.4.3 —** Implementar atribuição individual ou por coorte com objetivo, período, prioridade e contexto, exibindo ao paciente quem recomendou e sem sugerir garantia de resultado terapêutico.
  - [X] **8.12.4.4 —** Criar revisão periódica, denúncia e retirada de conteúdo, com alerta aos usuários afetados, substituição controlada e trilha de auditoria para moderação e decisão clínica.

- [X] **8.12.5 — White label, domínios e configuração por organização**
  - **Escopo:** permitir que organizações personalizem identidade visual, domínio, textos, navegação e comunicações transacionais, mantendo segurança, acessibilidade e isolamento de dados.
  - **Implementação:** armazenar tema e conteúdo institucional por tenant, validar configurações antes da publicação, automatizar domínio e certificado por adapter e suportar pré-visualização, versionamento e rollback.
  - [X] **8.12.5.1 —** Criar configuração de logotipo, ícones, cores, tipografia, nome, textos legais, remetente e links institucionais, com tokens de design e validação automática de contraste.
  - [X] **8.12.5.2 —** Implementar domínio personalizado com verificação de propriedade, provisionamento de TLS por adapter, renovação monitorada, cabeçalhos seguros e fallback para domínio padrão.
  - [X] **8.12.5.3 —** Criar modelos versionados de e-mail, notificações e páginas públicas com variáveis permitidas, pré-visualização, envio de teste, sanitização e aprovação antes de ativar.
  - [X] **8.12.5.4 —** Executar testes automatizados de isolamento entre tenants, cache por domínio, permissões administrativas e rollback, registrando alterações e publicações em log de auditoria.

### 8.13 Sprint 13 — WhatsApp, calendários e videoconferência

### Objetivo
Integrar comunicações e agenda clínica com WhatsApp, calendários externos e videoconferência por meio de adapters desacoplados, fluxos consentidos, processamento idempotente, observabilidade e alternativas quando provedores estiverem indisponíveis.

### Critérios de saída
- Integrações têm contratos de adapter, credenciais protegidas, health checks, logs correlacionáveis e testes contratuais.
- WhatsApp respeita consentimento, templates aprovados, janela de atendimento, opt-out e minimização de dados sensíveis.
- Agendamentos sincronizam com calendários externos sem duplicidade e com resolução auditável de conflitos.
- Salas de videoconferência têm acesso controlado, ciclo de vida vinculado ao atendimento e plano de contingência.
- Webhooks e jobs podem ser repetidos com segurança; falhas transitórias são retentadas e falhas permanentes vão para fila de exceção.

- [X] **8.13.1 — Plataforma de adapters e processamento confiável de integrações**
  - **Escopo:** estabelecer contratos comuns para WhatsApp, calendários e videoconferência, centralizando credenciais, idempotência, webhooks, retentativas, logs e métricas.
  - **Implementação:** definir interfaces por capacidade, normalizar eventos externos, usar inbox/outbox transacional e filas com dead-letter; propagar correlation ID sem registrar tokens ou conteúdo clínico desnecessário.
  - [X] **8.13.1.1 —** Definir contratos versionados de adapter para enviar, consultar, criar, atualizar, cancelar e receber eventos, com erros normalizados e matriz de capacidades por provedor.
  - [X] **8.13.1.2 —** Implementar cofre de credenciais e rotação por organização, com criptografia, escopos mínimos, teste de conexão e auditoria sem exposição do segredo.
  - [X] **8.13.1.3 —** Criar pipeline de webhook com validação de assinatura e timestamp, deduplicação por evento externo, persistência antes do processamento, retentativa exponencial e dead-letter.
  - [X] **8.13.1.4 —** Publicar métricas, logs estruturados e traces para latência, erro, quota, retentativa e deduplicação, com painéis e alertas que identificam provedor, tenant e operação.

- [X] **8.13.2 — WhatsApp para lembretes e atendimento administrativo**
  - **Escopo:** enviar lembretes, confirmações e mensagens administrativas e receber respostas simples, sem usar o canal para emergências ou expor detalhes clínicos além do necessário.
  - **Implementação:** integrar a API oficial por adapter, gerenciar opt-in e opt-out, templates aprovados e janela de atendimento; registrar status e eventos idempotentes com conteúdo minimizado nos logs.
  - [X] **8.13.2.1 —** Implementar consentimento granular por finalidade e número, com origem, data, versão do texto, revogação imediata e bloqueio de envio quando não houver base válida.
  - [X] **8.13.2.2 —** Criar catálogo de templates por idioma e organização para lembrete, confirmação, cancelamento e instrução administrativa, impedindo inclusão de diagnóstico ou informação clínica sensível.
  - [X] **8.13.2.3 —** Processar respostas de confirmar, remarcar, cancelar e parar, vinculando-as ao agendamento correto por token não previsível e deduplicando mensagens repetidas.
  - [X] **8.13.2.4 —** Exibir entrega, leitura e falha na linha do tempo administrativa, com fallback configurável para outro canal, fila de exceção e logs sem texto integral quando não for necessário.

- [X] **8.13.3 — Sincronização com calendários externos**
  - **Escopo:** sincronizar disponibilidade e compromissos com Google Calendar, Microsoft Outlook e calendários compatíveis, preservando privacidade e consistência do agendamento interno.
  - **Implementação:** conectar provedores por adapters OAuth com escopos mínimos; mapear IDs externos; sincronizar incrementalmente por cursor; aplicar idempotência e política explícita de resolução de conflitos.
  - [X] **8.13.3.1 —** Implementar conexão, renovação e revogação OAuth por organização e profissional, com estado anti-CSRF, armazenamento cifrado e aviso quando a autorização expirar.
  - [X] **8.13.3.2 —** Criar sincronização bidirecional incremental de criação, alteração e cancelamento, usando vínculo único interno-externo, versão do evento e prevenção de loops de atualização.
  - [X] **8.13.3.3 —** Mapear disponibilidade, bloqueios, fuso horário, horário de verão e recorrência, enviando ao calendário externo somente título e detalhes mínimos configurados.
  - [X] **8.13.3.4 —** Implementar central de conflitos para alterações concorrentes, evento removido e série divergente, com regra determinística, escolha manual e trilha de decisão.

- [X] **8.13.4 — Videoconferência clínica integrada**
  - **Escopo:** criar e gerenciar salas vinculadas a atendimentos remotos, com acesso seguro de paciente e profissional, testes prévios e contingência de provedor.
  - **Implementação:** usar adapters para provedores de vídeo, criar sala sob demanda com chave idempotente por atendimento, emitir tokens curtos por participante e registrar somente metadados operacionais necessários.
  - [X] **8.13.4.1 —** Implementar criação, consulta e encerramento de sala por adapter, com política de abertura, expiração, sala de espera e proibição de reutilização entre atendimentos.
  - [X] **8.13.4.2 —** Gerar links ou tokens individuais de curta duração, validar papel e vínculo com o atendimento e impedir entrada antecipada ou posterior à janela configurada.
  - [X] **8.13.4.3 —** Criar teste de câmera, microfone, alto-falante e conectividade, com instruções acessíveis e alternativas de contato sem registrar áudio ou vídeo do teste.
  - [X] **8.13.4.4 —** Implementar fallback para segundo provedor ou link administrativo seguro, monitorar indisponibilidade e deixar gravação desativada por padrão, sujeita a consentimento e política específica quando habilitada.

- [X] **8.13.5 — Orquestração da jornada de agendamento e resiliência**
  - **Escopo:** coordenar confirmação, lembretes, calendário e sala de vídeo em uma única jornada, garantindo consistência diante de reenvios, indisponibilidade e alterações de última hora.
  - **Implementação:** orquestrar por saga com estados persistidos e compensações, gerar comandos idempotentes por versão do agendamento e oferecer console operacional para reprocessamento controlado.
  - [X] **8.13.5.1 —** Definir saga de agendamento criado, confirmado, remarcado, cancelado, iniciado e concluído, incluindo ações e compensações em cada integração.
  - [X] **8.13.5.2 —** Garantir que remarcação atualize calendário, mensagens e sala na versão correta, descartando eventos atrasados sem apagar a evidência de recebimento.
  - [X] **8.13.5.3 —** Criar console de operações com filtros por correlação, provedor, tenant e estado, permitindo reprocessar ou compensar somente a usuários autorizados e com justificativa.
  - [X] **8.13.5.4 —** Executar testes de caos e contrato para timeout, rate limit, webhook duplicado, evento fora de ordem, expiração de credencial e indisponibilidade parcial, validando recuperação sem duplicidade.

### 8.14 Sprint 14 — Hábitos, rotina, medicamentos e sono

### Objetivo
Entregar ferramentas seguras de autocuidado e acompanhamento de hábitos, rotina, adesão a medicamentos previamente prescritos e sono, com consentimento, privacidade e supervisão clínica quando houver recomendação.

### Critérios de saída
- Usuários criam rotinas e registram hábitos sem linguagem punitiva, e podem pausar, ajustar ou excluir seus planos.
- O módulo de medicamentos serve apenas para cadastro e lembrete de prescrições existentes; não prescreve, recomenda dose nem orienta início, troca ou interrupção.
- Dados de sono e rotina podem ser registrados manualmente ou importados mediante consentimento, com procedência e possibilidade de revogação.
- Alertas e sugestões clínicas ficam bloqueados até aprovação individual ou protocolar por profissional habilitado.
- Painéis distinguem autorrelato de dado importado, evitam diagnóstico automático e passam por testes de segurança, acessibilidade e privacidade.

- [X] **8.14.1 — Planejamento de hábitos e rotina pessoal**
  - **Escopo:** permitir criar hábitos e blocos de rotina com frequência, contexto, lembrete, meta flexível e pausas, priorizando autonomia e redução de culpa.
  - **Implementação:** modelar planos versionados e ocorrências por fuso horário; gerar instâncias de forma idempotente; manter histórico de alterações e usar linguagem neutra em progresso e falhas.
  - [X] **8.14.1.1 —** Criar APIs para hábito, rotina, frequência, janela de execução, duração, dias ativos, lembrete, pausa e arquivamento, com validação de fuso e recorrência.
  - [X] **8.14.1.2 —** Implementar agenda diária e semanal com reordenação, divisão de atividade, exceções de calendário e atualização das ocorrências futuras sem alterar registros passados.
  - [X] **8.14.1.3 —** Gerar ocorrências por job idempotente com chave de plano, data local e versão, evitando duplicidade em mudança de fuso ou repetição do processamento.
  - [X] **8.14.1.4 —** Criar fluxos de pausa, redução e retomada que preservem autonomia, removam pressão por sequência perfeita e mantenham explicação acessível sobre o cálculo do progresso.

- [X] **8.14.2 — Check-ins, lembretes e evolução de hábitos**
  - **Escopo:** registrar conclusão, execução parcial, adiamento e motivo opcional, enviar lembretes consentidos e apresentar tendências pessoais sem comparação social.
  - **Implementação:** persistir check-ins idempotentes, separar evento bruto de agregados e recalcular métricas quando houver correção; respeitar preferências, horário silencioso e opt-out por canal.
  - [X] **8.14.2.1 —** Implementar check-in de concluído, parcial, adiado e ignorado com intensidade ou duração opcional, edição auditável e uma decisão efetiva por ocorrência.
  - [X] **8.14.2.2 —** Criar lembretes por push, e-mail ou canal integrado, com antecedência, horário silencioso, limite de frequência e cancelamento automático após conclusão ou pausa.
  - [X] **8.14.2.3 —** Exibir tendências de frequência, regularidade e esforço em períodos selecionáveis, sem rankings, punições ou afirmações causais sobre saúde.
  - [X] **8.14.2.4 —** Adicionar exportação e exclusão dos registros pelo titular, testes de mudança de fuso, recorrência e notificações duplicadas e logs de entrega sem conteúdo sensível.

- [X] **8.14.3 — Cadastro e lembretes de medicamentos sem prescrição**
  - **Escopo:** registrar medicamentos já prescritos e apoiar adesão com lembretes e histórico, vedando prescrição, sugestão de medicamento, ajuste de dose e orientação para iniciar, substituir ou interromper tratamento.
  - **Implementação:** exigir que o usuário informe a origem da prescrição; usar campos estruturados sem motor prescritivo; incluir avisos persistentes e encaminhar dúvidas, efeitos adversos e mudanças ao profissional habilitado ou aos canais adequados.
  - [X] **8.14.3.1 —** Criar cadastro de nome informado, apresentação, dose prescrita, unidade, via, horários, período, prescritor e data da prescrição, deixando explícito que o registro reproduz uma orientação externa existente.
  - [X] **8.14.3.2 —** Implementar lembretes e registro de tomado, atrasado, omitido ou não informado, com repetição idempotente, horário silencioso configurável e proibição de compensação automática de dose.
  - [X] **8.14.3.3 —** Bloquear textos e fluxos que recomendem iniciar, interromper, substituir ou alterar dose; diante de dúvida ou efeito adverso, orientar contato com profissional habilitado e, em sinais graves, busca imediata por serviço de emergência.
  - [X] **8.14.3.4 —** Criar compartilhamento opcional do histórico de adesão com o profissional, mediante consentimento granular, registrando acesso e mantendo qualquer alteração de esquema dependente de prescrição externa válida.

- [X] **8.14.4 — Diário e integração de dados de sono**
  - **Escopo:** registrar horários, despertares, percepção de qualidade, cochilos e fatores contextuais, além de importar dados de dispositivos quando autorizado.
  - **Implementação:** armazenar autorrelato e dado de dispositivo com procedência distinta; integrar fontes por adapters com sincronização incremental e idempotente; calcular tendências descritivas sem diagnosticar distúrbios.
  - [X] **8.14.4.1 —** Criar diário de sono para deitar, tentativa de dormir, despertar, levantar, cochilos, qualidade percebida e observações, validando intervalos que cruzam a meia-noite.
  - [X] **8.14.4.2 —** Implementar adapters para fontes de saúde compatíveis, com consentimento por tipo de dado, cursor de sincronização, deduplicação, revogação e exclusão da cópia importada quando aplicável.
  - [X] **8.14.4.3 —** Calcular duração estimada, regularidade e tendências separando valor informado, estimado e medido, exibindo limitações e sem classificar automaticamente condição clínica.
  - [X] **8.14.4.4 —** Criar visualizações acessíveis por dia, semana e mês, com correção manual preservando procedência, exportação e testes para fuso, horário de verão e dados sobrepostos.

- [X] **8.14.5 — Planos de cuidado e supervisão profissional**
  - **Escopo:** permitir que profissionais acompanhem hábitos, rotina, adesão declarada e sono e proponham planos de cuidado, sem automatizar decisões clínicas.
  - **Implementação:** produzir resumos transparentes com dados de origem; exigir aprovação de profissional habilitado para toda recomendação clínica; registrar autoria, justificativa, validade, consentimento e leitura pelo paciente.
  - [X] **8.14.5.1 —** Criar painel profissional com filtros de período, completude e procedência, diferenciando claramente autorrelato, dado importado e ausência de registro.
  - [X] **8.14.5.2 —** Implementar proposta de plano com objetivo, ações, frequência, justificativa, contraindicações, validade e responsável, bloqueando ativação até assinatura do profissional habilitado.
  - [X] **8.14.5.3 —** Permitir aceite, recusa, pausa e pedido de revisão pelo paciente, sem penalização, registrando a versão apresentada e notificando o profissional responsável.
  - [X] **8.14.5.4 —** Auditar criação, aprovação, alteração, visualização e revogação do plano e testar que regras automáticas apenas sinalizam dados para revisão, sem publicar recomendações diretamente.

### 8.15 Sprint 15 — Atividade física, bem-estar, sobriedade e modo crise

### Objetivo
Entregar acompanhamento seguro de atividade física e bem-estar, suporte à sobriedade e prevenção de recaída e um modo crise claramente não emergencial, com planos personalizados somente após aprovação profissional e encaminhamento imediato para recursos de emergência quando necessário.

### Critérios de saída
- Atividades e check-ins de bem-estar podem ser registrados ou importados com consentimento, procedência e limites de segurança visíveis.
- Recomendações de atividade, bem-estar, sobriedade e prevenção de recaída só são ativadas após aprovação de profissional habilitado.
- O plano de prevenção de recaída é privado, editável, compartilhável de forma granular e não usa linguagem moralizante.
- O modo crise afirma de forma inequívoca que o aplicativo não é serviço de emergência e oferece ações imediatas e contatos locais configuráveis.
- Testes de segurança confirmam que automações não diagnosticam, prescrevem, prometem resposta humana nem atrasam o acesso a serviços de emergência.

- [X] **8.15.1 — Registro de atividade física e integração com dispositivos**
  - **Escopo:** registrar caminhada, corrida, mobilidade, força e outras atividades, manualmente ou por fontes integradas, com duração, intensidade percebida e contexto.
  - **Implementação:** manter catálogo configurável sem prescrição automática; importar dados por adapters com consentimento e idempotência; preservar procedência e permitir correção sem apagar o evento original.
  - [X] **8.15.1.1 —** Criar registro manual de tipo, início, duração, intensidade percebida, distância opcional, observações e adaptações, com suporte a atividades acessíveis e assistidas.
  - [X] **8.15.1.2 —** Implementar adapters para fontes de saúde e wearables compatíveis, com escopos mínimos, cursor incremental, deduplicação por atividade externa e revogação da conexão.
  - [X] **8.15.1.3 —** Consolidar atividades sobrepostas por regra transparente, distinguindo dado manual e importado e permitindo que o usuário escolha qual registro considerar nas tendências.
  - [X] **8.15.1.4 —** Exibir volume, frequência e intensidade percebida por período, com avisos para respeitar limites individuais e procurar avaliação profissional diante de dor, mal-estar ou restrição clínica.

- [X] **8.15.2 — Check-ins de bem-estar e planos de movimento seguros**
  - **Escopo:** acompanhar energia, humor percebido, estresse e disposição e permitir planos graduais de movimento e autocuidado revisados por profissional.
  - **Implementação:** tratar check-ins como autorrelato, sem inferência diagnóstica; separar sugestões gerais de recomendações clínicas e exigir aprovação registrada de profissional habilitado antes de ativar plano individualizado.
  - [X] **8.15.2.1 —** Criar check-in opcional com escalas explicadas, contexto e preferência de privacidade, evitando conclusões automáticas a partir de uma resposta isolada.
  - [X] **8.15.2.2 —** Implementar biblioteca de práticas gerais de mobilidade, pausa e bem-estar com autoria, fontes, contraindicações, validade e revisão editorial.
  - [X] **8.15.2.3 —** Criar plano individual de atividade com objetivo, frequência, intensidade, progressão, adaptações e sinais de interrupção, bloqueado até aprovação de profissional habilitado.
  - [X] **8.15.2.4 —** Permitir feedback de dificuldade, dor ou desconforto que pause o plano e solicite revisão profissional, sem sugerir diagnóstico, medicamento ou retomada automática.

- [X] **8.15.3 — Jornada de sobriedade e rede de apoio**
  - **Escopo:** apoiar metas definidas pelo usuário, check-ins, marcos pessoais e acesso rápido a contatos de apoio, respeitando privacidade e diferentes trajetórias de recuperação.
  - **Implementação:** usar linguagem não moralizante, tornar marcos optativos e privados por padrão e armazenar compartilhamento com consentimento granular; não substituir acompanhamento clínico ou grupos de apoio.
  - [X] **8.15.3.1 —** Criar configuração de objetivo, data de referência, motivações, preferências de linguagem e visibilidade, permitindo redefinição sem apagar o histórico ou rotular o usuário.
  - [X] **8.15.3.2 —** Implementar check-in de vontade, contexto, estratégia utilizada e resultado percebido, com campos opcionais e proteção contra exposição em notificações e telas bloqueadas.
  - [X] **8.15.3.3 —** Criar marcos e reconhecimentos privados sem ranking, competição ou punição por interrupção, permitindo ocultar contadores e focar em ações do dia.
  - [X] **8.15.3.4 —** Cadastrar contatos e recursos de apoio com consentimento para acionamento, ordem de preferência, disponibilidade e teste periódico dos dados sem enviar mensagem automática não autorizada.

- [X] **8.15.4 — Plano de prevenção de recaída**
  - **Escopo:** permitir identificar gatilhos, sinais precoces, estratégias, ambientes seguros e pessoas de apoio em um plano revisável e acionável.
  - **Implementação:** oferecer estrutura guiada sem diagnóstico; versionar o plano e suas permissões; exigir aprovação de profissional habilitado quando houver conteúdo clínico recomendado e nunca acionar terceiros sem consentimento ou comando explícito.
  - [X] **8.15.4.1 —** Criar seções para gatilhos, sinais precoces, fatores protetores, estratégias pessoais, locais seguros, contatos e recursos profissionais, com edição e ordem definidas pelo usuário.
  - [X] **8.15.4.2 —** Implementar ensaio guiado do plano e revisão periódica, registrando versão, data, responsável e itens desatualizados, sem afirmar que o plano elimina risco.
  - [X] **8.15.4.3 —** Permitir compartilhamento granular por seção com profissional ou contato escolhido, prazo de acesso, revogação imediata e log de quem consultou.
  - [X] **8.15.4.4 —** Criar fluxo pós-lapso acolhedor para registrar o ocorrido, retomar estratégias e solicitar apoio, sem punição, perda de dados ou instrução clínica automática.

- [X] **8.15.5 — Modo crise, segurança e encaminhamento emergencial**
  - **Escopo:** oferecer uma interface de acesso rápido para aterramento, consulta ao plano pessoal, contatos de confiança e serviços de emergência, deixando explícito que o aplicativo não é serviço de emergência.
  - **Implementação:** manter o modo crise disponível com baixa conectividade, textos revisados por profissionais e recursos locais configuráveis; não prometer monitoramento ou resposta humana; priorizar ligação para emergência quando houver perigo imediato.
  - [X] **8.15.5.1 —** Exibir no primeiro painel e antes de qualquer exercício: “Este aplicativo não é um serviço de emergência e não oferece monitoramento em tempo real. Em perigo imediato, acione agora o serviço de emergência da sua localidade.”
  - [X] **8.15.5.2 —** Implementar ações de um toque para serviço de emergência local configurado, linha de crise disponível, contato de confiança e abertura do plano pessoal, sempre pedindo confirmação antes de ligar ou enviar mensagem.
  - [X] **8.15.5.3 —** Disponibilizar exercícios breves de aterramento e redução de estímulo offline, com opção de sair a qualquer momento e conteúdo clínico publicado somente após aprovação de profissional habilitado.
  - [X] **8.15.5.4 —** Executar revisão clínica e jurídica e testes de cenários de ideação suicida, overdose, violência, recaída e indisponibilidade de rede, comprovando que o fluxo não diagnostica, não prescreve, não promete resposta e não cria barreiras ao socorro imediato.


### 8.16 Sprint 16 — Rede de apoio, proteção de menores e espiritualidade opcional

**Objetivo:** disponibilizar vínculos de apoio consentidos e recursos opcionais de espiritualidade, com proteção reforçada para menores, privacidade por padrão, segregação multi-tenant e experiência acessível conforme WCAG 2.2 AA.

**Critérios de saída:**
- Fluxos de convite, aceite, revogação e emergência da rede de apoio operam com consentimento explícito, trilha de auditoria e escopo mínimo de dados.
- Contas de menores aplicam regras etárias, consentimento do responsável quando juridicamente exigido, linguagem adequada e bloqueio de exposição pública.
- Recursos de espiritualidade permanecem desativados por padrão, sem inferência de crença, proselitismo ou impacto no atendimento clínico.
- Testes automatizados comprovam isolamento multi-tenant, autorização por vínculo, acessibilidade WCAG 2.2 AA e não regressão dos fluxos críticos.

- [X] **8.16.1 — Implementar rede de apoio com consentimento granular**
  - **Escopo:** permitir que a pessoa convide familiares, responsáveis ou contatos de confiança e escolha, por contato, quais dados e ações podem ser acessados; excluir acesso implícito a prontuário, mensagens clínicas e resultados de instrumentos.
  - **Implementação:** criar entidades de vínculo, finalidade, permissões, validade e revogação; aplicar autorização no backend e filtros de campo no frontend; registrar eventos imutáveis de consentimento sem persistir conteúdo sensível no log.
  - [X] **8.16.1.1 —** Modelar convite, vínculo, finalidade, permissões permitidas, expiração, revogação e tenant, com índices e restrições contra vínculos duplicados.
  - [X] **8.16.1.2 —** Construir APIs de criar, aceitar, recusar e revogar convite, exigindo autenticação reforçada para alteração de permissões sensíveis.
  - [X] **8.16.1.3 —** Criar telas acessíveis para selecionar permissões em linguagem clara, revisar o consentimento e visualizar quem possui acesso ativo.
  - [X] **8.16.1.4 —** Testar matriz de autorização, enumeração de identificadores, expiração, revogação imediata e isolamento entre tenants.

- [X] **8.16.2 — Estabelecer salvaguardas para menores e responsáveis legais**
  - **Escopo:** aplicar jornadas específicas por faixa etária e base legal, equilibrando participação do menor, dever de cuidado e confidencialidade; impedir perfil público, descoberta por desconhecidos e compartilhamento amplo.
  - **Implementação:** manter política versionada por jurisdição e idade, coletar assentimento e consentimento quando aplicáveis, separar papéis de menor e responsável e submeter exceções a fluxo operacional documentado.
  - [X] **8.16.2.1 —** Implementar classificação etária e motor de políticas versionadas, sem expor data de nascimento completa fora dos serviços autorizados.
  - [X] **8.16.2.2 —** Criar fluxo de vinculação do responsável com verificação proporcional, validade, revisão periódica e contestação assistida pela operação.
  - [X] **8.16.2.3 —** Restringir busca, comunidades, mensagens, exportações e notificações conforme faixa etária e relação jurídica confirmada.
  - [X] **8.16.2.4 —** Validar cenários de mudança de idade, perda de guarda, múltiplos responsáveis, revogação e tentativas de acesso cruzado.

- [X] **8.16.3 — Disponibilizar plano de apoio e contatos para situações urgentes**
  - **Escopo:** permitir cadastro voluntário de contatos, preferências e recursos públicos para momentos de necessidade, sem substituir serviços de emergência nem gerar alerta clínico automatizado.
  - **Implementação:** criar plano editável pelo usuário, atalhos de chamada e mensagem acionados conscientemente, confirmação antes do compartilhamento e conteúdo localizado; qualquer encaminhamento clínico dependerá de profissional habilitado.
  - [X] **8.16.3.1 —** Modelar contatos priorizados, instruções pessoais, recursos locais, idioma, região e data da última revisão do plano.
  - [X] **8.16.3.2 —** Implementar acionamento explícito com prévia do conteúdo e do destinatário, sem envio silencioso ou inferência automática de crise.
  - [X] **8.16.3.3 —** Exibir aviso persistente sobre limites do recurso e opções de emergência adequadas à localidade, com navegação por teclado e leitor de tela.
  - [X] **8.16.3.4 —** Testar ausência de disparo automático, funcionamento com permissões negadas, números indisponíveis e revogação de contatos.

- [X] **8.16.4 — Adicionar espiritualidade e práticas contemplativas como módulo opcional**
  - **Escopo:** oferecer conteúdos contemplativos, de sentido e valores somente após adesão explícita, incluindo alternativa secular equivalente e controles para ocultar integralmente o módulo.
  - **Implementação:** usar catálogo revisado com metadados de tradição, neutralidade, idioma e acessibilidade; não inferir crença, não personalizar por dado sensível e não usar adesão em publicidade, score ou decisão clínica.
  - [X] **8.16.4.1 —** Criar preferência desativada por padrão com opções “secular”, “inter-religiosa” e tradições cadastradas, além de exclusão imediata do histórico de uso.
  - [X] **8.16.4.2 —** Implantar fluxo editorial com revisão de diversidade, segurança, direitos autorais, linguagem não coercitiva e versão do conteúdo.
  - [X] **8.16.4.3 —** Implementar recomendações exclusivamente dentro das preferências escolhidas, sem correlação com prontuário ou inferência de religião.
  - [X] **8.16.4.4 —** Realizar testes de acessibilidade, neutralidade da alternativa secular, retirada do consentimento e ausência do módulo para não aderentes.

- [X] **8.16.5 — Instrumentar qualidade, privacidade e rollout dos vínculos protegidos**
  - **Escopo:** preparar monitoramento, testes, suporte e liberação gradual dos recursos da sprint sem coletar conteúdo íntimo em telemetria.
  - **Implementação:** definir indicadores técnicos e de segurança agregados, feature flags por tenant e faixa etária, alertas operacionais e runbooks; bloquear rollout quando houver falha de autorização ou acessibilidade crítica.
  - [X] **8.16.5.1 —** Criar painéis de convites, revogações, erros de autorização e latência com identificadores pseudonimizados e retenção mínima.
  - [X] **8.16.5.2 —** Automatizar testes E2E das jornadas de adulto, menor e responsável em teclado, leitor de tela e viewport móvel.
  - [X] **8.16.5.3 —** Executar análise de ameaças e testes de abuso para coerção, tomada de conta, acesso indevido e exposição entre tenants.
  - [X] **8.16.5.4 —** Liberar por coortes internas e tenants-piloto, medir critérios de bloqueio e documentar rollback, suporte e comunicação de incidente.

### 8.17 Sprint 17 — Comunidades, grupos, moderação e gamificação responsável

**Objetivo:** habilitar convivência segura em comunidades e grupos com moderação auditável e mecanismos de engajamento que não promovam competição nociva, dependência ou exposição de dados de saúde.

**Critérios de saída:**
- Comunidades respeitam visibilidade, consentimento, idade, tenant e controles de bloqueio e denúncia.
- Moderação combina regras transparentes, automação apenas para triagem e decisão humana nos casos com impacto sobre pessoas.
- Gamificação é opcional, privada por padrão, sem punição por inatividade, ranking clínico ou recompensa por divulgar dados sensíveis.
- Operação dispõe de filas, SLAs, apelação, métricas, testes de abuso e procedimentos de incidente validados.

- [X] **8.17.1 — Construir comunidades e grupos com privacidade por padrão**
  - **Escopo:** permitir grupos privados por convite, grupos institucionais e comunidades temáticas aprovadas, mantendo identidades e conteúdo isolados por tenant e restringindo menores a espaços elegíveis.
  - **Implementação:** modelar comunidade, grupo, associação, papel, regras e visibilidade; aplicar ABAC por tenant, idade e status; desabilitar indexação externa e descoberta pública por padrão.
  - [X] **8.17.1.1 —** Criar esquema de dados e APIs para grupos, membros, papéis, regras, convites e encerramento, com exclusão lógica auditável.
  - [X] **8.17.1.2 —** Implementar diretório limitado ao tenant e às políticas etárias, com busca que não revele membros nem conteúdo a não participantes.
  - [X] **8.17.1.3 —** Criar onboarding acessível com regras, consentimento, pseudônimo opcional, preferências de notificação e saída imediata.
  - [X] **8.17.1.4 —** Testar autorização de proprietário, moderador e membro, além de isolamento, convites expirados e remoção de participante.

- [X] **8.17.2 — Entregar publicação, interação e controles de segurança social**
  - **Escopo:** oferecer posts, comentários e reações com limites de conteúdo, edição, exclusão, silenciamento, bloqueio e denúncia; excluir mensagens diretas entre desconhecidos e exposição de status clínico.
  - **Implementação:** criar feed paginado, sanitização de conteúdo, anexos seguros, controles anti-spam e preferências de notificação; preservar provas de denúncia em cofre segregado conforme política de retenção.
  - [X] **8.17.2.1 —** Implementar criação, edição e exclusão de posts e comentários com validação de MIME, varredura de anexos e proteção contra XSS.
  - [X] **8.17.2.2 —** Criar bloqueio, silenciamento e denúncia acessíveis em até dois acionamentos, sem notificar a pessoa denunciada sobre a identidade do denunciante.
  - [X] **8.17.2.3 —** Aplicar rate limits, detecção de spam e modo lento configurável sem analisar prontuário ou conversas clínicas.
  - [X] **8.17.2.4 —** Testar abuso de upload, menções, exclusão concorrente, bloqueio bilateral e vazamento por notificações ou prévias.

- [X] **8.17.3 — Implantar moderação humana, triagem e apelação**
  - **Escopo:** processar denúncias com prioridade, evidências mínimas, decisão humana e direito de apelação; automação pode classificar fila, mas não aplicar sanção definitiva de forma autônoma.
  - **Implementação:** construir console segregado, taxonomia de violações, SLAs, dupla revisão para casos graves e trilha de decisão; ocultar dados clínicos não necessários ao moderador.
  - [X] **8.17.3.1 —** Modelar caso, evidência, categoria, severidade, responsável, decisão, justificativa, prazo e apelação com auditoria append-only.
  - [X] **8.17.3.2 —** Criar fila priorizada por regras explícitas e sinais de plataforma, exigindo confirmação humana antes de advertência, suspensão ou remoção.
  - [X] **8.17.3.3 —** Implementar notificações de decisão e apelação em linguagem clara, com prazos e canal alternativo acessível.
  - [X] **8.17.3.4 —** Calibrar amostras entre moderadores e testar consistência, vieses, segregação de acesso, SLA e restauração após recurso procedente.

- [X] **8.17.4 — Implementar gamificação responsável e opt-in**
  - **Escopo:** oferecer metas pessoais, marcos privados e lembretes configuráveis, sem rankings públicos, streaks punitivos, caixas-surpresa, pressão social ou associação entre pontos e resultado clínico.
  - **Implementação:** criar motor de conquistas baseado em ações de autocuidado escolhidas pelo usuário, limites de frequência, pausa simples e explicações; nenhuma recompensa exigirá publicação ou compartilhamento de dado sensível.
  - [X] **8.17.4.1 —** Definir catálogo revisado de marcos não clínicos, critérios transparentes, limites diários e linguagem que normalize pausas e recaídas.
  - [X] **8.17.4.2 —** Implementar adesão, pausa, redefinição e exclusão do histórico, mantendo placar e comparação social desabilitados.
  - [X] **8.17.4.3 —** Criar preferências de lembrete com horário silencioso, frequência máxima e cancelamento no próprio aviso.
  - [X] **8.17.4.4 —** Testar padrões manipulativos, acessibilidade cognitiva, ausência de punição por inatividade e não uso dos marcos em decisões clínicas.

- [X] **8.17.5 — Preparar operação e rollout seguro das experiências sociais**
  - **Escopo:** validar capacidade da moderação, segurança, acessibilidade e comportamento dos recursos antes da expansão por tenant e público.
  - **Implementação:** adotar feature flags independentes para comunidades e gamificação, testes de carga e abuso, painéis sem conteúdo sensível e critérios de interrupção mensuráveis.
  - [X] **8.17.5.1 —** Simular volume de posts, picos de denúncias e indisponibilidade da moderação, verificando degradação segura e preservação de evidências.
  - [X] **8.17.5.2 —** Auditar fluxos principais contra WCAG 2.2 AA, incluindo foco, contraste, reflow, mensagens de erro e alternativas a gestos.
  - [X] **8.17.5.3 —** Definir SLOs, alertas e runbooks para fila represada, abuso coordenado, vazamento entre tenants e falhas de notificação.
  - [X] **8.17.5.4 —** Executar piloto moderado, revisar métricas de segurança e bem-estar e expandir apenas após aprovação conjunta de produto, privacidade e operação.

### 8.18 Sprint 18 — Prontuário, documentos, assinatura e retenção regulada

**Objetivo:** consolidar documentação clínica íntegra e rastreável, com assinatura eletrônica, controle de acesso mínimo, retenção regulada e exercício seguro de direitos do titular.

**Critérios de saída:**
- Registros clínicos possuem autoria, versão, assinatura, correções por adendo e auditoria inviolável sem sobrescrita silenciosa.
- Documentos são armazenados e entregues com criptografia, varredura, autorização por finalidade e segregação multi-tenant.
- Políticas de retenção, bloqueio legal, descarte e exportação são versionadas e executadas com comprovação.
- Testes de segurança, acessibilidade, restauração, carga e continuidade operacional são aprovados antes do rollout.

- [X] **8.18.1 — Estruturar prontuário clínico longitudinal e controle de versões**
  - **Escopo:** registrar episódios, evoluções, observações e adendos por profissional autorizado, distinguindo conteúdo clínico de anotações administrativas e impedindo alteração destrutiva após assinatura.
  - **Implementação:** modelar entradas imutáveis versionadas, relações de adendo, autoria, tenant, paciente, finalidade e estado; aplicar RBAC/ABAC e criptografia de campos sensíveis.
  - [X] **8.18.1.1 —** Criar esquema de entrada, versão, adendo, autoria e estado com integridade referencial e carimbo temporal confiável.
  - [X] **8.18.1.2 —** Implementar APIs de rascunho, revisão, assinatura e adendo com bloqueio otimista e prevenção de sobrescrita concorrente.
  - [X] **8.18.1.3 —** Construir linha do tempo acessível com distinção visual e semântica entre versão vigente, histórico e correções.
  - [X] **8.18.1.4 —** Testar acesso por função e vínculo assistencial, imutabilidade, concorrência, isolamento de tenant e restauração de backup.

- [X] **8.18.2 — Gerenciar documentos clínicos e administrativos com segurança**
  - **Escopo:** permitir upload, geração, classificação, visualização e download de documentos autorizados, evitando execução de conteúdo ativo e exposição por URLs previsíveis.
  - **Implementação:** armazenar objetos criptografados em namespace por tenant, usar URLs curtas e assinadas, validar tipo real, executar antivírus e registrar acesso com finalidade.
  - [X] **8.18.2.1 —** Definir taxonomia, metadados mínimos, tamanho máximo, tipos aceitos, proprietário, vínculo clínico e nível de confidencialidade.
  - [X] **8.18.2.2 —** Implementar pipeline de upload em quarentena, detecção MIME, varredura, normalização segura e promoção somente após aprovação.
  - [X] **8.18.2.3 —** Criar visualizador e download acessíveis com expiração de link, marca d’água configurável e cabeçalhos contra cache indevido.
  - [X] **8.18.2.4 —** Testar arquivos maliciosos, polyglots, acesso direto, troca de tenant, expiração de URL e indisponibilidade do antivírus.

- [X] **8.18.3 — Implementar assinatura eletrônica e cadeia de custódia**
  - **Escopo:** assinar documentos e entradas clínicas com evidências adequadas ao risco e à política institucional, mantendo verificação futura e distinção entre assinatura, ciência e aprovação.
  - **Implementação:** integrar provedor homologado ou assinatura interna conforme classe documental, gerar hash, manifesto de evidências e carimbo temporal; nunca armazenar segredo de assinatura no cliente.
  - [X] **8.18.3.1 —** Mapear classes documentais para nível de assinatura, identidade exigida, ordem de signatários e validade jurídica aplicável.
  - [X] **8.18.3.2 —** Implementar desafio de autenticação, consentimento de assinatura, hash do artefato e manifesto com versão e contexto.
  - [X] **8.18.3.3 —** Criar verificador de integridade e status com indicação acessível de assinatura válida, revogada, expirada ou não verificável.
  - [X] **8.18.3.4 —** Testar adulteração, reuso de desafio, troca de arquivo, falha do provedor, renovação de certificado e trilha de custódia.

- [X] **8.18.4 — Automatizar retenção regulada, bloqueio legal e descarte**
  - **Escopo:** cumprir prazos por tipo documental, jurisdição, contrato e idade, conciliando direitos LGPD com obrigações legais e preservando materiais sujeitos a litígio ou investigação.
  - **Implementação:** criar políticas versionadas e avaliador diário, congelamento por legal hold, aprovação segregada para descarte e certificados de execução; anonimizar quando a finalidade estatística permitir.
  - [X] **8.18.4.1 —** Cadastrar matriz de retenção por categoria, evento inicial, prazo, base legal, destino e responsável pela política.
  - [X] **8.18.4.2 —** Implementar legal hold com justificativa, escopo, aprovador, revisão periódica e bloqueio de exclusão em todas as réplicas elegíveis.
  - [X] **8.18.4.3 —** Executar descarte em lote idempotente, incluindo objetos, índices e caches, e emitir certificado sem conteúdo clínico.
  - [X] **8.18.4.4 —** Testar transição de menor para adulto, solicitações LGPD, conflito de regras, restauração temporária e expurgo posterior de backups.

- [X] **8.18.5 — Entregar auditoria, continuidade e rollout do prontuário**
  - **Escopo:** garantir rastreabilidade, disponibilidade e operação segura de documentação clínica em produção.
  - **Implementação:** centralizar logs append-only com minimização, monitorar SLOs, ensaiar recuperação e liberar em ondas com migração reversível e suporte treinado.
  - [X] **8.18.5.1 —** Registrar criação, leitura, exportação, assinatura, adendo, retenção e descarte com ator, finalidade e correlação, sem texto clínico no log.
  - [X] **8.18.5.2 —** Executar testes de carga, autorização, acessibilidade WCAG 2.2 AA, recuperação de desastre e consistência após restore.
  - [X] **8.18.5.3 —** Criar painéis e alertas para falha de assinatura, backlog de quarentena, acesso anômalo e erro de retenção com runbooks associados.
  - [X] **8.18.5.4 —** Migrar tenant-piloto com reconciliação de contagens e hashes, validar rollback e ampliar rollout após aceite clínico, jurídico e operacional.

### 8.19 Sprint 19 — IA assistiva, relatórios avançados e anonimização

**Objetivo:** introduzir assistência de IA limitada, explicável e sempre revisada por pessoa habilitada, além de relatórios avançados com minimização, anonimização e controles contra reidentificação.

**Critérios de saída:**
- Toda saída de IA permanece em rascunho, identifica fonte e incerteza, exige revisão humana e registra aprovação, edição ou rejeição.
- IA não diagnostica, prescreve, interpreta testes, decide elegibilidade, prioriza cuidado ou envia alerta clínico sem validação humana.
- Relatórios respeitam finalidade, tenant, consentimento e limiares de anonimização, com exportação auditada e resistente a ataques de diferenciação.
- Avaliações de qualidade, segurança, viés, privacidade, acessibilidade, monitoramento e rollback são aprovadas em ambiente controlado.

- [X] **8.19.1 — Implementar assistente de redação clínica com revisão humana obrigatória**
  - **Escopo:** auxiliar profissionais na síntese e formatação de texto fornecido explicitamente, sem gerar decisão clínica, inserir fatos ausentes ou gravar diretamente no prontuário.
  - **Implementação:** manter saída como rascunho separado, exibir trechos de origem, registrar versão de modelo e prompt, exigir comparação e ação humana antes de copiar para documento clínico.
  - [X] **8.19.1.1 —** Criar endpoint isolado por tenant com minimização de contexto, limites de tamanho, criptografia em trânsito e política de não treinamento pelo fornecedor.
  - [X] **8.19.1.2 —** Construir interface de revisão lado a lado com citações de origem, marcação de conteúdo não suportado e edição integral pelo profissional.
  - [X] **8.19.1.3 —** Impedir persistência automática e exigir confirmação nominal do revisor, finalidade e responsabilidade antes da incorporação ao prontuário.
  - [X] **8.19.1.4 —** Testar alucinação, instrução maliciosa em documento, troca de tenant, indisponibilidade do modelo e ausência de fonte verificável.

- [X] **8.19.2 — Aplicar guardrails e excluir usos de IA de alto risco**
  - **Escopo:** bloquear diagnóstico, prescrição, interpretação de testes, triagem autônoma, score de risco, decisão de tratamento e alerta clínico sem validação humana; proibir uso disciplinar ou securitário.
  - **Implementação:** manter registro de casos permitidos e proibidos, classificador de intenção conservador, regras determinísticas de bloqueio, revisão de segurança e canal de incidente; não tratar filtro automático como controle único.
  - [X] **8.19.2.1 —** Codificar política de usos permitidos, condicionais e proibidos com exemplos testáveis, responsáveis e revisão periódica.
  - [X] **8.19.2.2 —** Implementar bloqueios no gateway e na interface para solicitações de alto risco, retornando explicação e rota segura de atendimento humano.
  - [X] **8.19.2.3 —** Criar suíte adversarial em PT-BR para jailbreak, inferência diagnóstica indireta, prescrição velada, interpretação de escala e automação de alerta.
  - [X] **8.19.2.4 —** Configurar kill switch, feature flag por tenant, auditoria de violações e runbook para suspender o recurso e preservar evidências.

- [X] **8.19.3 — Estabelecer governança, avaliação e monitoramento de IA**
  - **Escopo:** controlar modelos, fornecedores, dados, versões, qualidade, viés e incidentes ao longo do ciclo de vida.
  - **Implementação:** criar inventário de modelos e datasets de avaliação aprovados, avaliações offline e amostragem humana, métricas por grupo apenas quando lícitas e suficientemente agregadas, com rollback de versão.
  - [X] **8.19.3.1 —** Registrar finalidade, proprietário, fornecedor, região de processamento, base legal, versão, riscos e data de reavaliação de cada modelo.
  - [X] **8.19.3.2 —** Montar conjunto de avaliação desidentificado com casos de fidelidade, omissão, linguagem estigmatizante, segurança e recusa adequada.
  - [X] **8.19.3.3 —** Medir taxa de aceitação, edição, rejeição, conteúdo sem fonte e incidentes sem usar concordância humana como prova de correção clínica.
  - [X] **8.19.3.4 —** Executar revisão periódica de deriva, viés e fornecedor, promovendo versão somente após limiares aprovados e possibilidade de rollback.

- [X] **8.19.4 — Criar relatórios avançados com controle de finalidade**
  - **Escopo:** oferecer relatórios clínico-operacionais autorizados e painéis agregados por tenant, período e serviço, sem permitir exploração livre de dados sensíveis ou comparação indevida entre profissionais e pacientes.
  - **Implementação:** usar camada semântica com métricas versionadas, consultas parametrizadas, ABAC por finalidade e supressão de células pequenas; separar relatórios assistenciais identificados dos analíticos agregados.
  - [X] **8.19.4.1 —** Definir dicionário de métricas, população, denominador, atualização, proprietário e interpretação permitida para cada indicador.
  - [X] **8.19.4.2 —** Implementar construtor limitado a dimensões aprovadas, filtros com escopo de tenant e autorização adicional para visão identificada.
  - [X] **8.19.4.3 —** Criar exportação com marcação de finalidade, expiração, trilha de acesso e proteção contra fórmulas em arquivos tabulares.
  - [X] **8.19.4.4 —** Testar consistência de métricas, paginação, fuso horário, filtros combinados, acesso cruzado e inferência por células pequenas.

- [X] **8.19.5 — Implantar anonimização, testes de reidentificação e rollout controlado**
  - **Escopo:** produzir datasets analíticos sem identificadores diretos e com risco residual medido, além de validar operação e acessibilidade dos recursos de IA e relatórios.
  - **Implementação:** aplicar generalização, supressão, limiares mínimos e, quando necessário, privacidade diferencial; manter chaves de pseudonimização em serviço separado e aprovar cada finalidade de compartilhamento.
  - [X] **8.19.5.1 —** Classificar quasi-identificadores e implementar perfis de anonimização por caso de uso, com orçamento de privacidade quando aplicável.
  - [X] **8.19.5.2 —** Executar ataques de ligação, singling out e diferenciação entre consultas, bloqueando exportações acima do risco aceito.
  - [X] **8.19.5.3 —** Validar WCAG 2.2 AA, latência, carga, falhas do fornecedor, revisão humana e observabilidade sem registrar prompts ou respostas sensíveis.
  - [X] **8.19.5.4 —** Liberar IA e relatórios separadamente para coortes aprovadas, monitorar critérios de parada e obter aceite de clínica, privacidade e segurança.

### 8.20 Sprint 20 — Integrações, PWA/mobile, observabilidade e operação

**Objetivo:** abrir integrações controladas e experiências móveis resilientes, consolidando observabilidade, acessibilidade, testes e operação para uma expansão segura da plataforma.

**Critérios de saída:**
- API, webhooks, CSV e wearables aplicam consentimento, escopos mínimos, idempotência, isolamento multi-tenant, auditoria e revogação.
- PWA e experiência mobile funcionam em conectividade instável sem armazenar dados sensíveis indevidamente nem produzir conflitos silenciosos.
- SLOs, telemetria minimizada, segurança, acessibilidade WCAG 2.2 AA e testes de recuperação atendem aos limiares de produção.
- Rollout gradual, suporte, resposta a incidentes, continuidade e rollback são ensaiados e aprovados pelos responsáveis.

- [X] **8.20.1 — Publicar API segura e portal de integrações**
  - **Escopo:** disponibilizar recursos autorizados de cadastro, agenda, atividades e documentos compatíveis, excluindo endpoints que permitam decisão clínica automatizada ou acesso irrestrito ao prontuário.
  - **Implementação:** adotar API versionada, OAuth 2.1/OIDC, escopos por finalidade, quotas, idempotência e OpenAPI; validar tenant a partir da credencial e do recurso, nunca de parâmetro confiado isoladamente.
  - [X] **8.20.1.1 —** Definir contratos OpenAPI, códigos de erro, paginação, filtros permitidos, escopos e política de compatibilidade e descontinuação.
  - [X] **8.20.1.2 —** Implementar clientes confidenciais com rotação de segredo, PKCE quando aplicável, tokens curtos e revogação imediata.
  - [X] **8.20.1.3 —** Aplicar idempotency keys, rate limits por cliente e tenant, validação de schema e correlação sem conteúdo sensível em logs.
  - [X] **8.20.1.4 —** Executar testes de contrato, autorização objeto a objeto, mass assignment, enumeração, replay e isolamento multi-tenant.

- [X] **8.20.2 — Entregar webhooks, importação/exportação CSV e integração com wearables**
  - **Escopo:** enviar eventos mínimos, trocar dados tabulares e importar métricas de dispositivos com consentimento granular; dados de wearables serão informativos e jamais gerarão diagnóstico, prescrição ou alerta clínico automático.
  - **Implementação:** assinar webhooks, implementar retries e replay seguro, validar CSV em quarentena e normalizar conectores de wearables; registrar proveniência, unidade, fuso e qualidade do dado.
  - [X] **8.20.2.1 —** Criar catálogo de eventos, assinatura HMAC, timestamp, chave rotacionável, entrega idempotente, fila de falhas e replay autorizado.
  - [X] **8.20.2.2 —** Implementar importação CSV com template versionado, prévia, validação por linha, proteção contra fórmula e relatório de rejeições sem dados excessivos.
  - [X] **8.20.2.3 —** Implementar exportação CSV com escopo, finalidade, expiração, codificação consistente e auditoria de solicitante e volume.
  - [X] **8.20.2.4 —** Integrar wearables por opt-in, permitir revogação e exclusão, exibir proveniência e impedir uso automático dos sinais em decisões clínicas.

- [X] **8.20.3 — Implementar PWA, modo offline e experiência mobile segura**
  - **Escopo:** oferecer instalação PWA e uso móvel responsivo para funções elegíveis, limitando o offline a dados mínimos e excluindo prontuário completo, assinatura e ações críticas sem conexão.
  - **Implementação:** usar service worker com cache allowlist, armazenamento local criptografado quando suportado, fila de mutações não críticas e resolução explícita de conflitos; limpar dados no logout e na revogação.
  - [X] **8.20.3.1 —** Criar manifest, ícones, atalhos e service worker com estratégia de cache por classe de recurso e atualização segura de versão.
  - [X] **8.20.3.2 —** Implementar leitura offline apenas para conteúdo autorizado e previamente selecionado, com expiração e indicador visível de desatualização.
  - [X] **8.20.3.3 —** Criar fila idempotente para check-ins e preferências não críticas, exibindo conflitos para escolha consciente sem sobrescrita silenciosa.
  - [X] **8.20.3.4 —** Testar perda de conexão, retomada, atualização do app, dispositivo compartilhado, logout remoto, leitor de tela e orientações de tela.

- [X] **8.20.4 — Consolidar observabilidade, acessibilidade e estratégia de testes**
  - **Escopo:** assegurar visibilidade operacional ponta a ponta sem capturar conteúdo clínico, além de conformidade WCAG 2.2 AA e cobertura dos riscos de integração e mobilidade.
  - **Implementação:** instrumentar métricas, logs e traces com redaction central, definir SLOs e error budgets, automatizar testes de acessibilidade, contrato, segurança, desempenho, offline e recuperação.
  - [X] **8.20.4.1 —** Definir SLOs de disponibilidade, latência, entrega de webhook, sincronização e erro por jornada, com alertas baseados em impacto.
  - [X] **8.20.4.2 —** Implantar correlação distribuída pseudonimizada, filtros de segredos e PHI, amostragem e retenção diferenciada por telemetria.
  - [X] **8.20.4.3 —** Automatizar testes WCAG 2.2 AA e revisão manual de teclado, foco, leitor de tela, zoom, contraste, reflow e autenticação acessível.
  - [X] **8.20.4.4 —** Executar suites de contrato, caos, carga, segurança, sincronização e disaster recovery, registrando evidências e critérios objetivos de aprovação.

- [X] **8.20.5 — Executar rollout, preparar operação e encerrar riscos de lançamento**
  - **Escopo:** colocar integrações e canais móveis em produção de forma gradual, com suporte, governança de parceiros, continuidade e resposta a incidentes.
  - **Implementação:** usar feature flags e canários por tenant e integração, checklist de prontidão, runbooks exercitados, comunicação de mudança e rollback automatizado; exigir avaliação de fornecedor e acordo de tratamento de dados.
  - [X] **8.20.5.1 —** Homologar parceiros com segurança, privacidade, residência de dados, suboperadores, SLA, revogação e plano de saída documentados.
  - [X] **8.20.5.2 —** Treinar suporte e operação em consentimento, revogação, falha de sincronização, incidente, acessibilidade e escalonamento clínico humano.
  - [X] **8.20.5.3 —** Realizar game day de indisponibilidade, vazamento de credencial, webhook duplicado, conflito offline e rollback de service worker.
  - [X] **8.20.5.4 —** Liberar por canário e ondas, acompanhar error budget e métricas de segurança, registrar aceite final e manter rollback até estabilização comprovada.



---

## 9. Dependências, riscos e decisões de governança

### 9.1 Dependências externas

1. Provedor de e-mail transacional e push.
2. Provedor oficial de WhatsApp ou Evolution API conforme avaliação comercial e jurídica.
3. Gateway de pagamento com Pix, cartão, boleto, estorno, split e webhooks.
4. Google Calendar, Outlook, Google Meet e Zoom mediante credenciais por clínica.
5. Provedor de assinatura eletrônica e emissão fiscal conforme região.
6. Armazenamento de objetos com criptografia, URLs temporárias e varredura de arquivos.
7. Serviço de transcrição e modelo de IA com contrato de tratamento de dados compatível.

### 9.2 Riscos principais e mitigação

1. **Vazamento entre clínicas:** filtros obrigatórios por tenant, testes de isolamento e negação por padrão.
2. **Exposição de diário privado:** política de compartilhamento no domínio e não apenas na interface; testes de autorização em API, exportação e relatórios.
3. **Interpretação clínica indevida:** textos de limite, bloqueio de usos proibidos e revisão humana.
4. **Dependência de integrações:** adapters, idempotência, circuit breaker, retentativa e fila de falhas.
5. **Excesso de notificações:** orçamento de frequência, horário de silêncio e preferências por canal.
6. **Conteúdo de risco em grupos:** moderação, denúncia, bloqueio, fila de revisão e protocolo aprovado.
7. **Complexidade excessiva:** feature flags, módulos por plano e liberação progressiva por clínica.
8. **Dados incompletos offline:** registro de versão, detecção de conflito e confirmação explícita da sincronização.

### 9.3 Decisões que exigem aprovação antes da produção

1. Categoria profissional e regras aplicáveis ao prontuário.
2. Base legal, retenção e processo de exclusão para cada tipo de dado.
3. Fluxo de menores, responsáveis e revogação de acesso.
4. Protocolo da clínica para situações de crise e horários de monitoramento.
5. Provedor, residência e uso secundário de dados por serviços de IA.
6. Escopo de assinatura eletrônica e validade dos documentos.
7. Estratégia de pagamentos, split, nota fiscal e tratamento contábil.

---

## 10. Estratégia de testes e aceite

### 10.1 Pirâmide de testes

1. Testes unitários para regras de domínio, estados, cálculos e validações.
2. Testes de integração para banco, filas, storage, e-mail, notificações e adapters externos.
3. Testes de contrato para API e webhooks versionados.
4. Testes de autorização cobrindo cada papel, vínculo, clínica e categoria de privacidade.
5. Testes de jornada para convite, onboarding, check-in, diário, agenda, mensagem, cobrança e exportação.
6. Testes de acessibilidade automatizados e revisão manual por teclado e leitor de tela.
7. Testes de restauração de backup, recuperação de job e rollback de implantação.

### 10.2 Cenários críticos obrigatórios

1. Um profissional de uma clínica não consulta paciente de outra clínica, mesmo alterando identificadores.
2. Um registro vermelho não aparece em painel, busca, resumo, exportação ou IA do profissional.
3. Revogar consentimento interrompe novos compartilhamentos e registra o efeito sobre dados anteriores.
4. Repetir webhook de pagamento, consulta ou mensagem não duplica eventos.
5. Falha de rede durante check-in não cria múltiplos registros.
6. Usuário sem permissão recebe resposta segura sem confirmar existência do recurso.
7. Modo crise funciona com tecnologia assistiva e não promete monitoramento contínuo.
8. Exclusão e portabilidade respeitam retenção obrigatória e produzem comprovante auditável.

### 10.3 Definição global de pronto

Uma tarefa só pode ser marcada com `[X]` quando:

1. Critérios funcionais e de autorização foram atendidos.
2. Testes automatizados relevantes passam no pipeline.
3. Migração de dados possui estratégia de avanço e reversão aplicável.
4. Logs não contêm segredos nem conteúdo clínico.
5. Interface atende estados claro, escuro, mobile, teclado, carregamento, vazio e erro.
6. Telemetria técnica e de produto foi adicionada sem dado pessoal desnecessário.
7. Documentação de operação e suporte foi atualizada.
8. Produto, engenharia e, quando regulado, responsável clínico/jurídico aceitaram o incremento.

---

## 11. Matriz de cobertura do catálogo original

| Grupo do `PROMPT.prd` | Sprints principais | Fase |
|---|---:|---|
| Cadastro, perfil, onboarding e avaliação inicial | 3–4 | MVP |
| Agenda, consultas e notificações | 8 | MVP |
| Diário emocional e check-in | 6 | MVP |
| Metas, plano e exercícios terapêuticos | 7 | MVP |
| Comunicação e painel profissional | 5, 9 | MVP |
| Administração da clínica e relatórios operacionais | 10 | Comercial |
| Financeiro | 10–11 | Comercial |
| Conteúdo, cursos e white label | 12 | Comercial |
| Calendários, videoconferência e WhatsApp | 13 | Comercial |
| Hábitos, rotina e medicamentos | 14 | Especializações |
| Sono, atividade física e bem-estar | 14 | Especializações |
| Sobriedade, recaída e situações de crise | 15 | Especializações / Regulado |
| Rede de apoio, familiares e menores | 16 | Especializações / Regulado |
| Espiritualidade | 16 | Especializações |
| Comunidades, grupos e gamificação | 17 | Especializações / Regulado |
| Prontuário, documentos e assinatura | 18 | Regulado |
| Inteligência artificial assistiva | 19 | Inteligência / Regulado |
| Relatórios avançados e anonimização | 19 | Inteligência |
| API, webhooks, CSV e dispositivos vestíveis | 19 | Integrações |
| PWA, offline, mobile e robustez operacional | 20 | Plataforma |
| Acessibilidade, segurança, privacidade e LGPD | 1–20 | Transversal |
| Resumo de consulta, cartão “Hoje não estou bem”, cápsula, jornada personalizada, semáforo, baixa energia e cartões de enfrentamento | 6–7, 9, 15–16 | Transversal |

---

## 12. Marcos de liberação

### 12.1 Marco A — Piloto interno

Concluído ao final do Sprint 5 com fundação, design system, segurança, identidade, perfis, consentimentos, onboarding e painel profissional básico.

### 12.2 Marco B — MVP clínico controlado

Concluído ao final do Sprint 9 com diário, check-in, metas, atividades, agenda, comunicação e relatórios essenciais. O piloto deve ocorrer com poucas clínicas, termos aprovados e suporte próximo.

### 12.3 Marco C — Produto comercial

Concluído ao final do Sprint 13 com administração, financeiro, conteúdo, white label e integrações comerciais.

### 12.4 Marco D — Especializações

Concluído ao final do Sprint 18 após validação das regras de medicamentos, crise, menores, comunidades e prontuário.

### 12.5 Marco E — Plataforma ampliada

Concluído ao final do Sprint 20 com IA assistiva, API, offline, observabilidade, acessibilidade e preparação mobile.

---

## 13. Aprovações requeridas

- [X] **13.1 Produto:** validar objetivos, priorização, jornadas e métricas.
- [X] **13.2 Engenharia:** validar arquitetura, estimativas, integrações e operação.
- [X] **13.3 Design:** validar adaptação do Duralux, acessibilidade e linguagem visual.
- [X] **13.4 Segurança e privacidade:** validar LGPD, isolamento, retenção, incidentes e fornecedores.
- [X] **13.5 Responsável clínico:** validar conteúdo, alertas, crise, medicamentos, sobriedade e limites de IA.
- [X] **13.6 Jurídico/regulatório:** validar prontuário, assinatura, menores, consentimentos, pagamentos e termos.
