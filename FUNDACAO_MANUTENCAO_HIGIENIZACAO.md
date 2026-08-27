# Fundação de Manutenção e Higienização — implementação (27/08/2026)

Escopo: exatamente o aprovado — `apps.maintenance` (enums, models `Maintenance`/`Cleaning`, services básicos, permissões, migrations, testes de domínio). **Nada além disso** foi implementado (sem fotos, notificações, dashboard, calendário, jobs, IA, recorrência automática, mudanças de infraestrutura/storage, e sem views/urls/templates — a fundação é só a camada de domínio).

Nenhuma das quatro primeiras decisões (matriz de status, matriz Maintenance×Movement, estratégia de restauração, decisão sobre `next_due_at`) exigiu mudança estrutural relevante no model proposto em 26/08 — a única adição real foi o campo `status_before` (necessário para a restauração determinística pedida na decisão 3), que é aditiva, não uma reestruturação. Por isso a implementação seguiu direto, sem pausar para nova aprovação antes da migration.

---

## 1. Matriz de status da Maintenance

Precondição de abertura **sem** `departure_movement`: `Equipment.status` ∈ {DISPONIVEL, EM_OPERACAO} — mesma regra que `ENVIO_MANUTENCAO` já exige em `apps.operations.services._TRANSITION_RULES`, por consistência.
Precondição de abertura **com** `departure_movement`: nenhuma — o Movement ENVIO_MANUTENCAO já validou e já mudou o status antes.

| Cenário | Status anterior | Abertura | Durante | Fechamento | Status final |
|---|---|---|---|---|---|
| **A — Estoque, sem Movement** | DISPONIVEL | `change_status(MANUTENCAO)`; `status_before=DISPONIVEL` | MANUTENCAO | restaura `status_before` → `change_status(DISPONIVEL)` | DISPONIVEL |
| **B — Cliente, sem Movement** | EM_OPERACAO | `change_status(MANUTENCAO)`; `status_before=EM_OPERACAO` | MANUTENCAO | restaura → `change_status(EM_OPERACAO)` | EM_OPERACAO |
| **C — Com ENVIO_MANUTENCAO** | DISPONIVEL/EM_OPERACAO (já mudado pelo Movement) | nenhuma chamada a `change_status()`; `status_before` só informativo (=MANUTENCAO) | MANUTENCAO | sem `return_movement`: nenhuma mudança. Com `return_movement`: só grava o vínculo (Movement já mudou o status) | MANUTENCAO (ainda fora) ou DISPONIVEL (quando o retorno for registrado) |
| **D — Sem movimentação física** | generalização de A/B | idem A/B | MANUTENCAO | idem A/B | idem A/B |
| **E1 — Cancelada, sem Movement** | (o que era antes) | idem A/B | MANUTENCAO | restaura `status_before` (mesma lógica do fechamento) | volta ao anterior |
| **E2 — Cancelada, com Movement** | — | sem alteração | MANUTENCAO | nenhuma mudança de status (cancelar a ficha não desfaz o fato físico) | MANUTENCAO |

**Regra de idempotência/corrida** (linhas A, B, D, E1 — sempre que `departure_movement is None`): o fechamento/cancelamento só restaura se `Equipment.status` (sob `select_for_update()`) **ainda for MANUTENCAO** no momento. Um Movement externo (ex.: `RETORNO_ESTOQUE`, que aceita MANUTENCAO como precondição) pode trazer o equipamento de volta enquanto a Maintenance segue aberta — nesse caso a restauração é pulada silenciosamente, porque o status já reflete a realidade física mais recente. Testado em `IdempotenciaRestauracaoTest`.

**Estados impossíveis bloqueados** (constraint de banco + validação de service, dupla camada):
- Duas `Maintenance` `ABERTA` para o mesmo equipamento (`UniqueConstraint` condicional + checagem em `open_maintenance()`).
- `CONCLUIDA` sem `service_performed` (`CheckConstraint`).
- `closed_at` incoerente com `status` (`CheckConstraint`).
- `departure_movement`/`return_movement` reclamado por duas `Maintenance` (agora `OneToOneField`, Django recomendou trocar de `ForeignKey(unique=True)` — ver seção de ajustes abaixo).
- Fechar/cancelar uma `Maintenance` que não está `ABERTA`.

## 2. Matriz Maintenance(ABERTA) × MovementType

Nenhuma linha exigiu código novo em `apps.operations.services` — o resultado já emerge das regras existentes em `_TRANSITION_RULES`. **Nenhuma mudança foi feita nesse arquivo.**

| MovementType | Precondição de status já existente | Compatível com MANUTENCAO? | Efeito com Maintenance ABERTA |
|---|---|---|---|
| INSTALACAO | DISPONIVEL | Não | Bloqueado |
| RETIRADA | EM_OPERACAO | Não | Bloqueado |
| TRANSFERENCIA | EM_OPERACAO | Não | Bloqueado |
| RETORNO_ESTOQUE | EM_OPERACAO ou MANUTENCAO | **Sim** | Permitido — muda status "por fora" (ver regra de idempotência) |
| ENVIO_MANUTENCAO | DISPONIVEL ou EM_OPERACAO | Não | Bloqueado — evita reenviar um equipamento já em manutenção |
| RETORNO_MANUTENCAO | MANUTENCAO | **Sim** | Permitido — caminho natural de retorno |
| OUTRO | nenhuma | Sim (sempre) | Permitido sempre — evento só anotado |

`RETORNO_ESTOQUE`/`RETORNO_MANUTENCAO` continuam permitidos por fora de uma Maintenance aberta **de propósito** — a paperwork pode ficar atrasada em relação ao fato físico.

## 3. Estratégia de restauração de status

`Maintenance.status_before` — snapshot **determinístico**, capturado automaticamente por `open_maintenance()` no instante da abertura (nunca um palpite tipo "provavelmente DISPONIVEL ou EM_OPERACAO"). A restauração só roda quando a própria `Maintenance` é dona da mudança (`departure_movement is None`), implementada em `_restore_status_if_owned()` (`apps/maintenance/services.py`), com a checagem de idempotência descrita acima.

## 4. Decisão sobre `next_due_at`

Mantido como campo simples em `Maintenance`/`Cleaning` — **sem** motor de recorrência. É a última data planejada conhecida, sem comportamento algum associado (não dispara nada, não é lido por nenhum job nesta etapa). Se uma fase futura precisar de recorrência real, isso vira um model novo e separado (`MaintenanceSchedule`); o campo atual não conflita com esse futuro. Raciocínio completo no topo de `apps/maintenance/services.py`.

## 5. Auditoria de `apps.attachments`

- **O que já existe**: app Django registrado em `INSTALLED_APPS` (`config/settings/base.py`), mas é o esqueleto padrão do `startapp`, sem nenhuma alteração — `models.py`/`views.py`/`admin.py`/`tests.py` vazios (só os comentários gerados pelo Django), `migrations/` só tem `__init__.py`. Nenhum model, nenhuma tabela, nenhuma view registrada em nenhum `urls.py`.
- **Por que foi criado**: reservado desde a Fase 1 para "fotos/anexos de equipamento" — confirmado pelo comentário em `CAN_ADD_PHOTOS` (`apps/accounts/permissions.py`): *"fotos/anexos de equipamento — Fase 2/3 (apps.attachments ainda é esqueleto vazio)"*.
- **Permissões existentes**: `CAN_ADD_PHOTOS = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL)` já existe.
- **Storage/media atual**: `MEDIA_URL`/`MEDIA_ROOT` genéricos em `base.py` (filesystem local, `BASE_DIR/media`). Em `render.py`, `STORAGES["default"]` = `FileSystemStorage`, com um aviso **já existente antes desta sessão**: o disco do Render Free é efêmero (não sobrevive a redeploy/restart) — antes de usar fotos em produção lá, MEDIA precisa migrar para armazenamento externo (S3-compatible, spec seção 15). `prod.py` (VPS) não sobrescreve `STORAGES`/`MEDIA` — herda o filesystem local, que no VPS é persistente (Nginx serve `/static/` do mesmo volume compartilhado).
- **Pode servir de infraestrutura reutilizável?** Em princípio sim, mas hoje não há nada além do nome reservado e da permissão — "reaproveitar" significaria criar os models do zero de qualquer forma.
- **Como evitar `GenericForeignKey` desnecessário**: um model por domínio (`EquipmentPhoto`, `MaintenancePhoto`, `CleaningPhoto`) dentro de `apps.attachments`, cada um com FK explícita ao seu dono — o projeto não usa `GenericForeignKey` em nenhum outro lugar, e essa abordagem preserva `on_delete=PROTECT`/`CASCADE` de verdade e queryability direta (`equipment.photos.all()`).
- **Impacto no Render/VPS**: nenhum hoje (nada implementado). Quando fotos forem implementadas, o aviso já registrado em `render.py` precisa virar ação real (S3-compatible) antes do primeiro deploy com fotos na Render. VPS não tem esse bloqueio.
- **Proposta (não implementada)**: `EquipmentPhoto`/`MaintenancePhoto`/`CleaningPhoto` como models irmãos dentro de `apps.attachments`, `on_delete=CASCADE` (composicionais), reaproveitando `CAN_ADD_PHOTOS`.

---

## Arquivos criados/alterados

**Criados:**
- `apps/maintenance/__init__.py`, `apps.py`, `models.py`, `services.py`, `admin.py`
- `apps/maintenance/migrations/__init__.py`, `0001_initial.py`
- `apps/maintenance/tests/__init__.py`, `test_maintenance_services.py`, `test_cleaning_services.py`

**Alterados:**
- `config/settings/base.py` — `apps.maintenance` adicionada a `LOCAL_APPS`.
- `apps/accounts/permissions.py` — `CAN_VIEW_MAINTENANCE` adicionada.

## Models finais

**`MaintenanceType`**: `PREVENTIVA`, `CORRETIVA`.
**`MaintenanceStatus`**: `ABERTA`, `CONCLUIDA`, `CANCELADA`.

**`Maintenance(TimeStampedModel, SoftDeleteModel)`**: `equipment` (PROTECT), `maintenance_type`, `status` (default `ABERTA`), `diagnosis`, `service_performed`, `condition_before`/`condition_after` (snapshots), `status_before` (snapshot p/ restauração), `departure_movement`/`return_movement` (`OneToOneField` a `Movement`, `null=True`, `PROTECT`), `responsible` (PROTECT), `notes`, `next_due_at`, `closed_at`, `created_by` (PROTECT), `history = HistoricalRecords()`.

**`Cleaning(TimeStampedModel, SoftDeleteModel)`**: `equipment` (PROTECT), `performed_at`, `responsible` (PROTECT), `notes`, `next_due_at`, `movement` (FK opcional a `Movement`, `PROTECT`), `created_by` (PROTECT). Sem `HistoricalRecords` (evento atômico, nunca editado).

### Ajuste feito durante a implementação (não estrutural)

`departure_movement`/`return_movement` foram declarados inicialmente como `ForeignKey(unique=True)` — o `manage.py check` acusou `fields.W342` (Django recomenda `OneToOneField` nesse caso). Troquei para `OneToOneField`, que é semanticamente idêntico ao que a proposta já previa ("no máximo uma Maintenance por Movement"), sem qualquer efeito no comportamento documentado nas matrizes.

## Constraints

```python
# Maintenance.Meta.constraints
CheckConstraint(~Q(status=CONCLUIDA) | ~Q(service_performed=""), name="maintenance_conclusao_exige_servico")
CheckConstraint(
    Q(status=ABERTA, closed_at__isnull=True) | (~Q(status=ABERTA) & Q(closed_at__isnull=False)),
    name="maintenance_closed_at_coerente_com_status",
)
UniqueConstraint(fields=["equipment"], condition=Q(status=ABERTA), name="uniq_maintenance_aberta_por_equipamento")
```

## Services (`apps/maintenance/services.py`)

- `open_maintenance(NewMaintenanceData) -> Maintenance`
- `close_maintenance(*, maintenance, data: CloseMaintenanceData) -> Maintenance`
- `cancel_maintenance(*, maintenance, cancelled_by, reason="") -> Maintenance`
- `create_cleaning(NewCleaningData) -> Cleaning`
- `cancel_cleaning(*, cleaning) -> Cleaning`

Todos com `select_for_update()` em `Equipment` (e em `Maintenance`, nos fechamentos/cancelamentos) — mesma disciplina de `create_movement()`. Nenhum atribui `equipment.status`/`condition`/`current_location`/`current_client` diretamente — só via `change_status()`/`change_condition()` já existentes, ou nunca (location/client).

## Migrations

`apps/maintenance/migrations/0001_initial.py` — cria `Maintenance`, `HistoricalMaintenance`, `Cleaning`, e as 3 constraints acima. `makemigrations --check` limpo depois de aplicada.

## Permissões

```python
CAN_VIEW_MAINTENANCE = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA)
```

Escrita reaproveita `CAN_REGISTER_OPERATIONS` (já reservada desde a Fase 1 para "manutenção/higienização/movimentação") — nenhuma constante nova. `CAN_ADD_PHOTOS` fica para quando fotos forem decididas (item 8, não implementado).

## Total de testes

- **31 testes novos** (`apps.maintenance`), todos passando.
- **Suíte completa: 410/410 passando** (379 anteriores + 31 novos) contra PostgreSQL real.
- `manage.py check`: limpo.
- `makemigrations --check --dry-run`: `No changes detected`.

## Checklist de reteste manual

- [ ] Abrir manutenção sem movimentação para um equipamento `DISPONIVEL` em estoque — confirmar que o status vira "Manutenção" na ficha do equipamento.
- [ ] Fechar essa manutenção com serviço executado preenchido — confirmar que o status volta para "Disponível".
- [ ] Tentar fechar sem preencher "serviço executado" — confirmar rejeição com mensagem clara.
- [ ] Tentar abrir uma segunda manutenção para o mesmo equipamento enquanto a primeira ainda está aberta — confirmar rejeição.
- [ ] Registrar um `ENVIO_MANUTENCAO` (tela já existente) e depois abrir uma manutenção linkando esse Movement — confirmar que o status não é alterado de novo e que nenhum `StatusHistory` duplicado aparece na timeline.
- [ ] Fechar essa manutenção sem `RETORNO_MANUTENCAO` — confirmar que o equipamento continua "Em manutenção".
- [ ] Registrar `RETORNO_MANUTENCAO` (tela existente) separadamente — confirmar que o status muda para "Disponível" por conta do Movement, independente da Maintenance.
- [ ] Cancelar uma manutenção aberta sem movimentação — confirmar que o status é restaurado ao que era antes.
- [ ] Registrar uma higienização (via `create_cleaning()`, ainda sem tela) — confirmar que nem status nem condição do equipamento mudam.
- [ ] Conferir no Django Admin (`/admin/`) que `Maintenance`/`Cleaning` aparecem, mas sem botão de "Adicionar" (só leitura — criação é só via service).

Este checklist cobre só a camada de domínio (sem UI própria ainda) — os passos que mencionam "tela" usam as telas de `Movement` já existentes; abrir/fechar Maintenance e registrar Cleaning, nesta etapa, só são acessíveis via `manage.py shell`/testes, já que nenhuma view foi criada (fora do escopo aprovado).

---

## Não implementado (fora de escopo, como solicitado)

Fotos/anexos (`MaintenancePhoto`/`CleaningPhoto`), notificações, dashboard, calendário, jobs, IA, recorrência automática, mudanças de infraestrutura/storage, e também views/urls/templates para Maintenance/Cleaning (a lista aprovada não os incluía — só a fundação de domínio).

Nenhum deploy foi feito.
