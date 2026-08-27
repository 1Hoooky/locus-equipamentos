# Revisão: Maintenance × Movement — fechamento das duas lacunas (27/08/2026)

Escopo: só as duas lacunas de domínio apontadas. Nenhuma UI, nenhuma foto, nenhuma agenda/notificação/dashboard.

---

## 1. Solução adotada para evitar dependência circular

**Não existe um ciclo de import real hoje** entre `apps.operations` e `apps.maintenance` — tracei o grafo: `apps.maintenance.models` importa `apps.operations.models` (não `.services`), e nada em `apps.maintenance` importa `apps.operations.services`. Um `import` no topo de `apps/operations/services.py` puxando `apps.maintenance` não quebraria nada tecnicamente hoje.

O problema é **de direção**, não de técnica: `apps.operations` existe desde a Fase 1 (camada mais baixa/mais antiga) e `apps.maintenance` foi introduzido depois, consumindo `operations` (camada mais alta). Um import estático no topo do módulo inverteria essa direção — `operations` passaria a "conhecer", em tempo de import, um domínio que só existe para usá-lo, e criaria risco real de ciclo assim que `apps.maintenance` precisar de algo de `apps.operations.services` no futuro (bem plausível).

**Solução**: import **local, dentro da função**, em `apps.operations.services._validate_transition()`, chamando um único predicado público novo em `apps.maintenance.services`:

```python
def has_open_maintenance(equipment: Equipment) -> bool:
    return Maintenance.objects.filter(equipment=equipment, status=MaintenanceStatus.ABERTA, is_active=True).exists()
```

`apps.operations` não importa `Maintenance`/`MaintenanceStatus` — só chama uma função booleana. Isso corresponde à opção "policy/service desacoplado em camada apropriada" + "função de domínio cuja dependência não provoque ciclo de imports" que você listou — não é um import-dentro-de-função como gambiarra: é deliberado, documentado no próprio código (comentário extenso em `_validate_transition()` e no topo de `apps/maintenance/services.py`), e resolve o problema de direção mesmo sem haver ciclo técnico hoje.

Descartei `django.apps.apps.get_model()` (a outra opção que você listou) porque, neste caso específico, eu ainda precisaria de uma segunda peça — o valor do enum `MaintenanceStatus.ABERTA` — para montar a query corretamente; encapsular a query INTEIRA (incluindo o `is_active=True`) atrás de uma função pública em `apps.maintenance` é mais simples e mantém TODO o conhecimento sobre os campos internos de `Maintenance` dentro do próprio app dono desse conhecimento.

## 2. Matriz final garantida pelo backend

| MovementType | Bloqueado por Maintenance ABERTA e ativa? | Onde é aplicado |
|---|---|---|
| INSTALACAO | **Sim, sempre** — mesmo se `Equipment.status` já permitisse | `apps.operations.services._validate_transition()`, checagem nova |
| RETIRADA | **Sim, sempre** | idem |
| TRANSFERENCIA | **Sim, sempre** | idem |
| ENVIO_MANUTENCAO | **Sim, sempre** — evita reenviar/duplicar | idem |
| RETORNO_ESTOQUE | Não — permitido sempre que o status já permitir | inalterado |
| RETORNO_MANUTENCAO | Não — caminho natural de retorno | inalterado |
| OUTRO | Não — evento apenas anotado | inalterado |

Cenário do relatório (equipamento volta a DISPONIVEL via `RETORNO_ESTOQUE`/`RETORNO_MANUTENCAO` sem fechar a Maintenance) agora bloqueia `INSTALACAO` corretamente — coberto por `test_instalacao_bloqueada_mesmo_com_status_disponivel` e pelos dois testes de concorrência.

## 3. Estratégia de locking

`open_maintenance()` e `create_movement()` já tomavam `Equipment` como único lock (`select_for_update()`, sempre a primeira operação de banco) antes de tocar `Maintenance`/`Movement`. A checagem nova (`has_open_maintenance()`) roda **depois** desse lock, dentro de `_validate_transition()` — chamada só depois do `select_for_update()` do chamador (`create_movement()`).

Como as duas funções tomam o MESMO e ÚNICO lock, na mesma ordem, e nenhuma das duas segura um segundo lock esperando a outra, não há risco de deadlock: PostgreSQL serializa as duas transações inteiramente por esse lock — quem chega primeiro termina (commit/rollback) antes da outra sequer conseguir ler `Maintenance`. Verifiquei separadamente que `close_maintenance()` (que trava `Maintenance` primeiro, `Equipment` depois) também não introduz deadlock com `create_movement()`, porque `create_movement()` nunca disputa o lock de `Maintenance` — o único ponto de disputa real continua sendo `Equipment`.

Dois testes de concorrência real (`TransactionTestCase` + threads + PostgreSQL real, mesmo padrão de `test_movement_concurrency.py`):

- `AbrirManutencaoVersusInstalarConcurrencyTest` — exatamente o pedido: abrir Maintenance × instalar, disparados ao mesmo tempo. As duas ordens possíveis são verificadas e são as ÚNICAS que ocorrem em 5 execuções seguidas.
- `FecharManutencaoVersusInstalarConcurrencyTest` — complementar: fechar a ficha × instalar, a partir do cenário exato relatado (status já livre "por fora").

## 4. UniqueConstraint e soft delete

Ajustada, como você esperava: `Maintenance` herda `SoftDeleteModel`, e uma ficha inativada (`is_active=False`) não deveria prender o equipamento atrás de uma constraint de banco para sempre. Trocada:

```python
UniqueConstraint(fields=["equipment"], condition=Q(status=ABERTA, is_active=True), name="uniq_maintenance_aberta_ativa_por_equipamento")
```

(renomeada de `uniq_maintenance_aberta_por_equipamento` para deixar a nova condição explícita no próprio nome). A checagem em `open_maintenance()`/`has_open_maintenance()` foi ajustada com a MESMA condição — dupla camada consistente.

Testes de PostgreSQL: `test_banco_rejeita_segunda_maintenance_ativa_aberta` (ativa bloqueia a segunda) e `test_maintenance_aberta_porem_inativa_nao_bloqueia_nova_ativa` (inativa não bloqueia).

## 5. Semântica definitiva de `status_before`

**Não renomeei o campo** — sem necessidade, como você preferiu. Documentei a semântica de forma inequívoca no `help_text` do campo e na docstring da classe `Maintenance`:

> `status_before` é o `Equipment.status` no instante em que **esta ficha** foi aberta — não "o status antes de qualquer manutenção" em sentido amplo. Sem `departure_movement`: é o valor genuíno a restaurar. Com `departure_movement`: vale sempre `MANUTENCAO` (o Movement já rodou antes) e **nunca** é usado para restaurar nada — se algum dia for preciso o status genuíno anterior ao envio físico, a fonte correta é `StatusHistory`/`Movement` anteriores a `departure_movement.created_at`, nunca este campo.

Isso é aplicado exatamente pela lógica já existente em `_restore_status_if_owned()`, que curto-circuita sempre que `departure_movement_id is not None` — o código já se comportava certo; só a documentação estava ambígua.

## Migration criada

`apps/maintenance/migrations/0002_maintenance_aberta_ativa_constraint.py` — troca a `UniqueConstraint` e atualiza o `help_text` de `status_before` (em `Maintenance` e `HistoricalMaintenance`). Sem migração de dados (nenhuma `Maintenance` foi soft-deletada até hoje — a fundação não expõe nenhuma operação que faça isso).

## Arquivos alterados

- `apps/maintenance/models.py` — `UniqueConstraint` ajustada, `status_before` com `help_text`/docstring revisados.
- `apps/maintenance/services.py` — `has_open_maintenance()` novo (público), `open_maintenance()` usa a mesma função, docstring das Matrizes 1/2 atualizada com o achado e a correção.
- `apps/operations/services.py` — `_BLOCKED_BY_OPEN_MAINTENANCE` novo, checagem nova dentro de `_validate_transition()` (import local, justificado em comentário).
- `apps/maintenance/migrations/0002_maintenance_aberta_ativa_constraint.py` — nova.
- Testes novos: `test_maintenance_movement_compatibility.py` (9), `test_maintenance_constraints.py` (3), `test_maintenance_movement_concurrency.py` (2) — **16 testes novos**.

## Total final de testes

- **apps.maintenance: 47/47** (31 anteriores + 16 novos).
- **Suíte completa do projeto: 426/426 passando** contra PostgreSQL real (410 anteriores + 16 novos).
- `manage.py check`: limpo.
- `makemigrations --check --dry-run`: `No changes detected`.
- Testes de `Movement` já existentes (`test_movement_services`, `test_movement_concurrency`, `test_movement_destination_selection`, `test_operations_views`): todos continuam passando sem alteração — a checagem nova não regrediu nenhum fluxo existente.

Nenhum deploy foi feito. Nenhuma UI, foto, notificação, agenda ou dashboard foi implementada.
