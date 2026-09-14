# apps.attachments

## Objetivo

`apps.attachments` está registrado em `INSTALLED_APPS` (`config/settings/base.py`) mas é hoje um **esqueleto vazio** — reservado para uma futura funcionalidade de fotos/anexos de equipamento (prevista na tela de cadastro, mas não é critério de aceite explícito da especificação original). Não é código morto no sentido de "sobrou de algo que existiu": nunca foi implementado.

## Models

`apps/attachments/models.py` contém só o boilerplate do `startapp` (`from django.db import models` + comentário). **Nenhum model, nenhuma migration real** (`migrations/` só tem `__init__.py`).

## Services

Não existe `services.py`.

## Forms

Não existe `forms.py`.

## Views

`apps/attachments/views.py` é boilerplate vazio (`from django.shortcuts import render`).

## URLs

Não existe `urls.py`. Não há rota nenhuma para este app.

## Permissions

Não aplicável — sem views, sem models.

## Templates

Nenhum.

## JavaScript

Nenhum.

## Dependências

Nenhuma — o app não importa nada além do boilerplate padrão do Django.

## Quem chama apps.attachments

Nenhum outro app importa ou referencia `apps.attachments` — confirmado por busca textual em todo o projeto. Em particular, **não** tem FK para `Equipment` apesar do nome sugerir "anexos de equipamento" — a expectativa de que `apps.equipment`/`apps.crm` dependessem deste app não se confirma no código atual (a aba "Arquivos" da ficha de oportunidade do CRM, por exemplo, foi deliberadamente omitida por causa disso).

## O que apps.attachments chama

Nada.

## Testes

`apps/attachments/tests.py` é o stub padrão do `startapp` (`# Create your tests here.`), sem nenhum teste real.

## Migrations

Nenhuma.

## Pontos importantes

- **Mantido no repositório propositalmente**, não removido durante a limpeza desta rodada: é um placeholder para uma feature futura já prevista no roadmap ("fotos/anexos de equipamento"), não um resíduo de algo que existiu e foi abandonado. Removê-lo exigiria voltar a criá-lo do zero (registro em `INSTALLED_APPS`, `AppConfig`, etc.) no dia em que a feature for priorizada.
- Se/quando esta funcionalidade for implementada, o padrão esperado pelo resto do projeto é: um `services.py` como único caminho de escrita, permissões via o catálogo aditivo (`apps.accounts.permission_catalog`, seguindo o padrão de `apps.crm`, já que é um app novo) ou via `RoleRequiredMixin`/`CAN_*` (seguindo o padrão legado da maioria dos apps) — a escolha entre os dois sistemas deve ser deliberada, não incidental (ver `docs/permissions.md`).
