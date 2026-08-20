# Locus Equipamentos

Sistema próprio de identificação, rastreamento e gestão de equipamentos da Locus Locações. Este repositório implementa a **Fase 1 — Patrimônio Digital**, conforme a `Especificação Técnica v1.0` (documento de referência, mantido em `docs/`).

## Status atual

O que já está implementado e testado:

- Projeto Django modular (`apps/accounts`, `apps/catalog`, `apps/equipment`, `apps/clients`, `apps/operations` com schema pronto; `apps/attachments`, `apps/dashboard` como esqueletos para as próximas etapas).
- `User` customizado com os 4 perfis da especificação (Administrador, Administrativo, Operacional/Técnico, Consulta) e matriz de permissões em `apps/accounts/permissions.py`.
- `Category` e `EquipmentModel` (com `code`, travado após o primeiro equipamento vinculado).
- `Equipment` com `patrimonio` no formato `LOC-{MODEL_CODE}-{SEQUENCE}`, gerado **atomicamente** e sequência independente por modelo (`apps/equipment/services.py`).
- Procedimentos de reclassificação de modelo e reemissão excepcional de patrimônio, conforme seção 8 da especificação.
- Django admin funcional para cadastro (categorias, modelos, equipamentos) — já passa pela geração atômica, não pelo `save()` cru.
- Listagem de equipamentos (com busca e filtros combinados) e ficha individual (pública/autenticada), a mesma URL que o QR Code aponta.
- **Geração de QR Code (PNG) e etiqueta em PDF** (`apps/qrcodes/`), individual e em lote (action no admin: "Baixar etiquetas em PDF") — o QR codifica só a URL permanente do patrimônio, nunca dados do equipamento.
- **Exportação CSV/Excel** da listagem de equipamentos, respeitando os filtros aplicados (`apps/equipment/export.py`).
- `django-simple-history` habilitado em `EquipmentModel` e `Equipment` (histórico automático de alterações).
- Comando `seed_catalog` com os códigos de modelo já definidos pela Locus.
- **Importação assistida da planilha legada** (`apps/equipment/legacy_import.py` + `views_import.py`): upload do `.xlsx` → sugestão automática de modelo por linha (comparando subcategoria/descrição do sistema/descrição livre contra o catálogo, ficando com a melhor correspondência) → tela de revisão onde o Administrador confirma ou corrige manualmente cada linha, com todos os modelos ativos disponíveis mesmo quando a categoria da planilha não bate com nenhuma cadastrada → confirmação grava via o mesmo `create_equipment()` atômico usado em todo o resto do sistema. Duas camadas de proteção contra duplicidade por reimportação (no parse e na confirmação). Restrita a Administrador. Validada rodando de ponta a ponta contra a planilha real da Locus (306 linhas: 125 com sugestão automática, as demais — a maioria climatizadores, cuja subcategoria na planilha antiga é mais granular que os 6 códigos de modelo cadastrados hoje — ficam corretamente marcadas para escolha manual em vez de arriscar um match errado).
- **Cadastro de usuários pela interface web** (`apps/accounts/views.py` + `forms.py`, telas em `templates/accounts/`): listar, criar (com perfil e senha inicial) e editar (perfil, ativar/desativar) usuários, substituindo o uso de admin/shell do primeiro passo da Fase 1. Restrito a Administrador; inclui a trava de "não pode desativar a si mesmo".
- 54 testes automatizados passando contra PostgreSQL real, incluindo: concorrência na geração do patrimônio (12 cadastros simultâneos do mesmo modelo, zero duplicidade), decodificação real do QR (confere que ele aponta para a URL certa), vazamento de dados na página pública, matriz de permissões, exportação, importação da planilha legada (parser e fluxo HTTP completo) e gestão de usuários.

**O que ainda não está implementado** (próximos passos dentro da própria Fase 1): refinamento visual das telas, build compilado do Tailwind (hoje via CDN). Fase 2 (clientes, movimentação, manutenção, higienização) e Fase 3 (dashboard) são backlog — schema já preparado, sem tela nem lógica ainda.

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
- `test_public_detail_view.py` — a ficha pública do QR nunca vaza cliente, valor de aquisição ou observações internas.
- `test_export.py` — exportação CSV/Excel reproduz os dados certos e respeita os filtros e a permissão de quem exporta.

- `test_legacy_import.py` — parser da planilha legada (sugestão por subcategoria/descrição, detecção de dados faltando, categoria desconhecida ainda oferecendo lista completa de modelos, duplicidade contra equipamento já existente) e o fluxo HTTP completo de upload → revisão → confirmação, incluindo a segunda camada de defesa contra duplicidade na confirmação.

Em `apps/qrcodes/tests/test_qr_and_labels.py`: o QR é decodificado de verdade (não só "gerou um PNG") e confere que a URL bate com a permanente do patrimônio; PDF de etiqueta é validado; download é restrito a Administrador/Administrativo.

Em `apps/accounts/tests/test_permissions.py` — a matriz de permissões da especificação (seção 11) como teste, não só documentação. Em `apps/accounts/tests/test_user_management.py` — criação e edição de usuário pela interface, incluindo a trava de autodesativação e a restrição a Administrador.

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
