# Locus Equipamentos

Sistema próprio de identificação, rastreamento e gestão de equipamentos da Locus Locações. Este repositório implementa a **Fase 1 — Patrimônio Digital**, conforme a `Especificação Técnica v1.0` (documento de referência, mantido em `docs/`).

## Status atual (primeiro passo da Fase 1)

O que já está implementado e testado nesta etapa:

- Projeto Django modular (`apps/accounts`, `apps/catalog`, `apps/equipment`, `apps/clients`, `apps/operations` com schema pronto; `apps/attachments`, `apps/qrcodes`, `apps/dashboard` como esqueletos para as próximas etapas).
- `User` customizado com os 4 perfis da especificação (Administrador, Administrativo, Operacional/Técnico, Consulta) e matriz de permissões em `apps/accounts/permissions.py`.
- `Category` e `EquipmentModel` (com `code`, travado após o primeiro equipamento vinculado).
- `Equipment` com `patrimonio` no formato `LOC-{MODEL_CODE}-{SEQUENCE}`, gerado **atomicamente** e sequência independente por modelo (`apps/equipment/services.py`).
- Procedimentos de reclassificação de modelo e reemissão excepcional de patrimônio, conforme seção 8 da especificação.
- Django admin funcional para cadastro (categorias, modelos, equipamentos) — já passa pela geração atômica, não pelo `save()` cru.
- Listagem de equipamentos e ficha individual (pública/autenticada), a mesma URL que o QR Code vai apontar.
- `django-simple-history` habilitado em `EquipmentModel` e `Equipment` (histórico automático de alterações).
- Comando `seed_catalog` com os códigos de modelo já definidos pela Locus.
- 17 testes automatizados passando contra PostgreSQL real, incluindo o teste de concorrência exigido pela especificação (12 cadastros simultâneos do mesmo modelo, zero duplicidade).

**O que ainda não está nesta etapa** (próximos passos dentro da própria Fase 1): geração de QR Code/etiqueta em PDF, exportação CSV/Excel, importação assistida da planilha legada, cadastro de usuários pela interface (hoje só via admin/shell), refinamento visual das telas. Fase 2 (clientes, movimentação, manutenção, higienização) e Fase 3 (dashboard) são backlog — schema já preparado, sem tela nem lógica ainda.

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

E em `apps/accounts/tests/test_permissions.py` — a matriz de permissões da especificação (seção 11) como teste, não só documentação.

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
