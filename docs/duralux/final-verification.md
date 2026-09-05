# Verificação final da migração Duralux

Data: 2026-09-05
Estado: migração implementada; encerramento global condicionado aos gates externos listados abaixo.

## Gate técnico

- `uv run pytest`: **1.150 aprovados, 1 ignorado**, cobertura total **86%**.
- `uv run ruff check .`: aprovado.
- `uv run mypy .`: aprovado em **565 arquivos-fonte**.
- `DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py check`: aprovado, zero problemas.
- `DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py collectstatic --noinput --dry-run`: aprovado.
- `uv run python -m py_compile accounts/services.py accounts/views.py journal/forms.py`: aprovado no Python 3.14 do projeto.
- `node --check static/duralux/js/*.js`: aprovado.
- `git diff --check`: aprovado.
- Gate focado de legado, templates, staticfiles, formulários, Sprint 4 e layouts: **64 aprovados**.
- Suíte clínica de consentimentos, diário, check-in, metas, exercícios e baixa energia: **130 aprovados, 1 ignorado**.
- Suíte MFA: **40 aprovados**.

## Cobertura e runtime

- Catálogo Duralux analisado: **77/77**.
- Baseline da aplicação: **95/95** reconciliada; 94 templates retidos, um órfão removido com guarda automatizada e três auxiliares Duralux adicionados, totalizando 97 HTML atuais.
- Runtime visual legado: zero referências ativas conforme guardas automatizadas.
- Manifesto: 13 assets publicados com SHA-256 validado contra os arquivos reais.
- Staticfiles local, sem CDN e sem arquivos demonstrativos servidos como páginas finais.

## Evidência visual

- `docs/duralux/evidence/integrated-final/`: 120 verificações, 10 jornadas, larguras 320, 375, 768, 1024, 1280 e 1440, temas claro/escuro, 40 PNGs, zero falhas.
- `docs/duralux/evidence/final-rereview/`: 48 verificações corretivas em check-in, diário, metas e estado inválido de metas, nas mesmas larguras e temas; zero overflow, imagens quebradas, recursos externos ou alvos `aria-describedby` inválidos; 8 PNGs.
- No formulário inválido de metas, erros visíveis, `aria-invalid` e os alvos de erro de horizon, priority e visibility foram confirmados.
- Menu móvel: abertura, ciclo de foco, fechamento com Escape e retorno de foco ao acionador verificados em Chrome.

## Segurança MFA

- QR SVG e URI `otpauth` gerados localmente com Segno.
- Segredo criptografado, confirmação TOTP, prevenção de reutilização, rate limit e oito códigos de recuperação preservados.
- O passo TOTP usado no cadastro é consumido; fator confirmado não pode ser reconfirmado para emitir novos recovery codes.
- Segredo, URI, código submetido e recovery codes são protegidos nos parâmetros POST e em todos os frames do `ExceptionReporter` testados.
- Falhas descendentes de Segno, renderização sensível e consumo do código são convertidas em exceções sanitizadas com supressão da cadeia que continha material MFA.
- Respostas de cadastro, desafio e recuperação permanecem `no-store` e não indexáveis.

## Revisões independentes

- Cobertura 95/95, remoção do legado e manifesto: **aprovado**, sem Critical/Important.
- Segurança MFA após as ondas corretivas: **aprovado**, sem Critical/Important.
- Sprint 6 e acessibilidade automatizável após as ondas corretivas: **aprovado**, sem Critical/Important.

## Pendências externas ou manuais

- Escanear o QR Code em dispositivo físico com Google Authenticator Android ou iOS e confirmar o primeiro código.
- Executar validação manual completa com leitor de tela.
- Percorrer exaustivamente todas as rotas HTML com todos os perfis autorizados.
- Fechar os critérios compostos de WCAG/zoom 200%/`prefers-reduced-motion` e calendário por teclado que ainda exigem evidência manual específica.

Nenhum commit, push ou deploy foi executado.
