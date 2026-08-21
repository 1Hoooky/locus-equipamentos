# Locus Equipamentos

Sistema próprio de identificação, rastreamento e gestão de equipamentos da Locus Locações. Este repositório implementa a **Fase 1 — Patrimônio Digital**, conforme a `Especificação Técnica v1.0` (documento de referência, mantido em `docs/`).

## Status atual

O que já está implementado e testado:

- Projeto Django modular (`apps/accounts`, `apps/catalog`, `apps/equipment`, `apps/clients`, `apps/operations` com schema pronto; `apps/attachments`, `apps/dashboard` como esqueletos para as próximas etapas).
- `User` customizado com os 4 perfis da especificação (Administrador, Administrativo, Operacional/Técnico, Consulta) e matriz de permissões em `apps/accounts/permissions.py`.
- `Category` e `EquipmentModel` (com `code`, travado após o primeiro equipamento vinculado).
- `Equipment` com `patrimonio` no formato `LOC-{MODEL_CODE}-{SEQUENCE}`, gerado **atomicamente** e sequência independente por modelo (`apps/equipment/services.py`).
- Procedimentos de reclassificação de modelo e reemissão excepcional de patrimônio, conforme seção 8 da especificação.
- **Telas próprias de cadastro/edição de equipamento, categoria e modelo** (`apps/equipment/views.py`, `apps/catalog/views.py`), de reclassificação de modelo e reemissão excepcional de patrimônio — todas com permissão validada no backend via `RoleRequiredMixin`, respeitando a matriz da seção 11 (não dependem de `is_staff`). O Django admin continua existindo, mas só como ferramenta técnica/contingência — `status`/`condition` do equipamento ficam somente-leitura lá, forçando toda mudança a passar pelas telas dedicadas (garante que `StatusHistory`/`ConditionHistory` nunca fiquem incompletos).
- **`StatusHistory` e `ConditionHistory`** (`apps/equipment/models.py`): evento estruturado (equipamento, valor anterior, novo valor, responsável, data/hora, motivo) gerado automaticamente a cada mudança de status/condição, sempre pelo mesmo caminho (`apps/equipment/services.py: change_status()`/`change_condition()`), nunca por edição direta.
- **`django-axes`** contra força bruta no login (especificação, seção 11): bloqueia por usuário ou por IP após `AXES_FAILURE_LIMIT` tentativas falhas (padrão 5, configurável via `.env`), com cooloff automático (padrão 30 min).
- Django admin funcional para cadastro (categorias, modelos, equipamentos) — já passa pela geração atômica, não pelo `save()` cru. Hoje é só ferramenta técnica/contingência, não a interface operacional.
- Listagem de equipamentos com busca livre e filtros combinados (status, condição, categoria, modelo) e ficha individual (pública/autenticada), a mesma URL que o QR Code aponta.
- **Geração de QR Code (PNG) e etiqueta em PDF** (`apps/qrcodes/`), individual e em lote (action no admin: "Baixar etiquetas em PDF") — o QR codifica só a URL permanente do patrimônio, nunca dados do equipamento.
- **Exportação CSV/Excel** da listagem de equipamentos, respeitando os filtros aplicados (`apps/equipment/export.py`).
- `django-simple-history` habilitado em `EquipmentModel` e `Equipment` (histórico automático de alterações).
- Comando `seed_catalog` com os códigos de modelo já definidos pela Locus.
- **Importação assistida da planilha legada** (`apps/equipment/legacy_import.py` + `views_import.py`): upload do `.xlsx` → sugestão automática de modelo por linha (comparando subcategoria/descrição do sistema/descrição livre contra o catálogo, ficando com a melhor correspondência) → tela de revisão onde o Administrador confirma ou corrige manualmente cada linha, com todos os modelos ativos disponíveis mesmo quando a categoria da planilha não bate com nenhuma cadastrada → confirmação grava via o mesmo `create_equipment()` atômico usado em todo o resto do sistema. Duas camadas de proteção contra duplicidade por reimportação (no parse e na confirmação). Restrita a Administrador. Validada rodando de ponta a ponta contra a planilha real da Locus (306 linhas: 125 com sugestão automática, as demais — a maioria climatizadores, cuja subcategoria na planilha antiga é mais granular que os 6 códigos de modelo cadastrados hoje — ficam corretamente marcadas para escolha manual em vez de arriscar um match errado).
- **Cadastro de usuários pela interface web** (`apps/accounts/views.py` + `forms.py`, telas em `templates/accounts/`): listar, criar (com perfil e senha inicial) e editar (perfil, ativar/desativar) usuários, substituindo o uso de admin/shell do primeiro passo da Fase 1. Restrito a Administrador; inclui a trava de "não pode desativar a si mesmo".
- 96 testes automatizados passando contra PostgreSQL real, incluindo: concorrência na geração do patrimônio (12 cadastros simultâneos do mesmo modelo, zero duplicidade), decodificação real do QR, vazamento de dados na página pública, matriz de permissões de cada tela nova, reclassificação/reemissão pela tela, `StatusHistory`/`ConditionHistory` automáticos, filtros da listagem, bloqueio de força bruta do `django-axes`, exportação, importação da planilha legada e gestão de usuários.

**O que ainda não está implementado** (próximos passos dentro da própria Fase 1): fotos/anexos de equipamento (`apps/attachments` continua um esqueleto vazio — não é critério de aceite explícito da seção 20, mas é campo previsto na tela de cadastro da seção 12), e-mail transacional de produção (dev já funciona via console backend; produção depende de escolher provedor — Mailgun/Resend/SES), refinamento visual das telas, build compilado do Tailwind (hoje via CDN). Fase 2 (clientes, movimentação, manutenção, higienização) e Fase 3 (dashboard) são backlog — schema já preparado, sem tela nem lógica ainda.

## Por que PostgreSQL também em desenvolvimento

A geração atômica do patrimônio depende de `SELECT FOR UPDATE`, que o SQLite não implementa de forma confiável sob concorrência real. Por isso não existe fallback para SQLite neste projeto — nem em dev, nem em testes.

## Rodando localmente com Docker (recomendado)

```bash
cp .env.example .env
# edite o .env com uma SECRET_KEY própria (gere com get_random_secret_key())

docker compose -f docker-compose.dev.yml up --build
```

Depois, num outro terminal:

```bash
docker compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
docker compose -f docker-compose.dev.yml exec web python manage.py seed_catalog
```

A aplicação sobe em `http://localhost:8000`. O admin fica em `/admin/`.

## Rodando localmente sem Docker

Requer PostgreSQL 16 rodando localmente.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt

cp .env.example .env
# ajuste DB_HOST=localhost e as credenciais do seu Postgres local

python manage.py migrate
python manage.py createsuperuser
python manage.py seed_catalog
python manage.py runserver
```

## Testes

```bash
python -m pytest -v
```

Os testes mais importantes ficam em `apps/equipment/tests/`:

- `test_patrimonio_generation.py` — geração atômica, incluindo o teste de concorrência com 12 threads.
- `test_immutability_and_reclassification.py` — patrimônio nunca muda por edição direta; reclassificação de modelo preserva o patrimônio; reemissão excepcional cria um novo.
- `test_public_detail_view.py` — a ficha pública do QR nunca vaza cliente, valor de aquisição ou observações internas; e (`AcquisitionValueVisibilityByRoleTest`) que, na ficha autenticada, Administrador e Administrativo veem valor de aquisição/fornecedor mas Operacional/Técnico e Consulta não, mesmo tendo acesso à mesma tela (seção 11).
- `test_export.py` — exportação CSV/Excel reproduz os dados certos e respeita os filtros e a permissão de quem exporta.

- `test_legacy_import.py` — parser da planilha legada (sugestão por subcategoria/descrição, detecção de dados faltando, categoria desconhecida ainda oferecendo lista completa de modelos, duplicidade contra equipamento já existente) e o fluxo HTTP completo de upload → revisão → confirmação, incluindo a segunda camada de defesa contra duplicidade na confirmação.
- `test_equipment_crud_views.py` — cadastro/edição de equipamento por perfil, edição não conseguindo tocar em modelo/status/patrimônio, alteração de status/condição gerando `StatusHistory`/`ConditionHistory` automaticamente, reclassificação e reemissão pela tela, filtros combinados da listagem.

Em `apps/catalog/tests/test_catalog_views.py`: cadastro/edição de categoria e modelo por perfil, trava de `code` no formulário assim que o modelo já tem equipamento (mesmo tentando forçar o valor no POST).

Em `apps/accounts/tests/test_axes_lockout.py`: bloqueio real de login por força bruta via `django-axes` — usa requisições HTTP reais para `/contas/login/` (não o atalho `client.login()`, que não é compatível com o backend do axes) para confirmar que o limite de tentativas bloqueia mesmo a senha certa, que o bloqueio não afeta outro usuário vindo de outro IP, e que um login bem-sucedido reseta o contador. Como o atalho `client.login()` é usado no resto da suíte só para autenticar rapidamente antes de testar outra coisa, `config/settings/test.py` desliga `AXES_ENABLED` por padrão nos testes — só este arquivo o reativa via `override_settings`.

Em `apps/qrcodes/tests/test_qr_and_labels.py`: o QR é decodificado de verdade (não só "gerou um PNG") e confere que a URL bate com a permanente do patrimônio; PDF de etiqueta é validado; download é restrito a Administrador/Administrativo.

Em `apps/accounts/tests/test_permissions.py` — a matriz de permissões da especificação (seção 11) como teste, não só documentação. Em `apps/accounts/tests/test_user_management.py` — criação e edição de usuário pela interface, incluindo a trava de autodesativação e a restrição a Administrador.

Em `apps/accounts/tests/test_password_reset.py`: fluxo HTTP completo de recuperação de senha (pedido → e-mail real no backend de teste → link → nova senha → login com a senha nova), incluindo e-mail para endereço desconhecido (não revela se existe) e link adulterado (rejeitado). Esse teste revelou e cobriu a correção de um `NoReverseMatch` real que quebrava o envio do e-mail e o sucesso do fluxo — as views genéricas de auth do Django assumem nomes de rota sem namespace, e este projeto registra tudo sob `accounts:`; corrigido com `success_url` explícito em `apps/accounts/urls.py` e um `templates/registration/password_reset_email.html` próprio.

## Deploy em produção (HostGator VPS NVMe 4)

1. Provisionar o VPS (Ubuntu/AlmaLinux/Rocky), instalar Docker e Docker Compose.
2. Apontar o DNS de `estoque.locuslocacoes.com.br` (subdomínio, especificação seção 22) para o IP do VPS.
3. Clonar o repositório no servidor, criar o `.env` real (nunca o mesmo do dev) com `DJANGO_SETTINGS_MODULE=config.settings.prod`.
4. Emitir o certificado TLS (ver comentário em `docker-compose.yml`, serviço `certbot`).
5. `docker compose up -d --build`.
6. Configurar backup automático (`pg_dump` diário + cópia externa) — ver seção 17/19 da especificação; ainda não incluído neste primeiro passo, é o próximo item de infraestrutura.

## Estrutura

Ver seção 19/20 da `Especificação Técnica v1.0` para a justificativa de cada pasta. Resumo:

```
apps/            → um app Django por domínio (accounts, catalog, equipment, ...)
config/settings/ → base.py (comum) + dev.py + prod.py
templates/       → templates Django, um subdiretório por app
docker/          → Dockerfile auxiliar (entrypoint), nginx.conf
requirements/    → base.txt, dev.txt, prod.txt
docs/            → especificação técnica e futuras decisões de arquitetura
```
