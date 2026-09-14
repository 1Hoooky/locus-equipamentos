# LocusHub — Locus Equipamentos

Sistema de gestão de equipamentos, clientes, operação e CRM da Locus Locações: cadastro de equipamentos com patrimônio digital (QR Code), clientes e movimentação (instalar/retirar/transferir), manutenção e higienização, e um funil de vendas (CRM) — tudo numa aplicação Django única, server-rendered.

## Documentação

Este README é só a porta de entrada. A documentação completa vive em [`docs/`](docs/):

- [`docs/architecture.md`](docs/architecture.md) — visão geral, stack, mapa de dependências entre apps, o padrão `services.py`, configuração.
- [`docs/permissions.md`](docs/permissions.md) — os dois sistemas de autorização do projeto (legado `Role`/`CAN_*` e o novo "Cargo"), e como eles se relacionam.
- [`docs/flows.md`](docs/flows.md) — os fluxos principais do sistema, passo a passo (geração de patrimônio, movimentação, manutenção, CRM, hard delete, importações).
- [`docs/testing.md`](docs/testing.md) — como rodar a suíte (`pytest`, não `manage.py test`), estado atual, testes de concorrência real.
- [`docs/storage.md`](docs/storage.md) — estáticos vs. mídia, quem serve cada um em cada caminho de deploy, por que download de anexo nunca é um link `/media/` direto.
- [`docs/deployment.md`](docs/deployment.md) — os dois caminhos de deploy (VPS Oracle+FRP e Render+Neon).
- [`docs/apps/`](docs/apps/) — um documento por app Django, cobrindo models, services, forms, views, URLs, permissões, templates, JS, dependências, testes e armadilhas conhecidas.

## Apps

| App | Papel |
|---|---|
| [`core`](docs/apps/core.md) | Base compartilhada (models abstratos, hard delete, navegação, template tags) |
| [`accounts`](docs/apps/accounts.md) | Usuários e autorização |
| [`catalog`](docs/apps/catalog.md) | Categorias e Modelos de equipamento |
| [`equipment`](docs/apps/equipment.md) | Equipamentos, patrimônio atômico, página pública do QR |
| [`clients`](docs/apps/clients.md) | Clientes, endereço fiscal, consulta de CNPJ, importação Auvo |
| [`operations`](docs/apps/operations.md) | Unidades (`Location`) e movimentação (`Movement`) |
| [`maintenance`](docs/apps/maintenance.md) | Manutenção e Higienização |
| [`attachments`](docs/apps/attachments.md) | Anexos genéricos (hoje: PDFs de Proposta Comercial/Contrato do CRM) |
| [`qrcodes`](docs/apps/qrcodes.md) | Geração de QR/código de barras/etiquetas PDF |
| [`dashboard`](docs/apps/dashboard.md) | Home operacional |
| [`crm`](docs/apps/crm.md) | Funil de vendas (Kanban de Oportunidades) |

## Por que PostgreSQL também em desenvolvimento

A geração atômica do patrimônio depende de `SELECT ... FOR UPDATE`, que o SQLite não implementa de forma confiável sob concorrência real. Por isso não existe fallback para SQLite — nem em dev, nem em testes. Ver [`docs/architecture.md`](docs/architecture.md).

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

A aplicação sobe em `http://localhost:8000`. O admin fica em `/admin/` — é só ferramenta técnica/contingência, não a interface operacional (ver [`docs/permissions.md`](docs/permissions.md)).

## Rodando os testes

```bash
python -m pytest
```

**Nunca use `python manage.py test`** — usa o settings errado para este projeto e produz falhas falsas em massa. Ver [`docs/testing.md`](docs/testing.md) para o motivo exato.

## Deploy

Dois caminhos em paralelo: VPS (Oracle Cloud + túnel FRP, principal) e Render+Neon (alternativo, para validação). Nenhum push/deploy é feito a partir deste ambiente de trabalho — ver [`docs/deployment.md`](docs/deployment.md) para o procedimento completo de cada um.
