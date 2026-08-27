# Auditoria de fechamento — Fundação operacional da Fase 2

Data: 27/08/2026
Escopo: Client, Address, Location, Movement, CompanyLookupService/BrasilAPI, idempotência, backfill de clientes legados, Locations internas, timeline, permissões, migrations 0002–0005, diagnóstico de duplicatas, performance das queries críticas, regressões da Fase 1.

---

## Parte 1 — Resultado final da auditoria

### 1. Suíte completa contra PostgreSQL real

```
Ran 379 tests in 123.819s
OK
```

379/379 passando — mesmo total que antes deste fechamento (nenhum teste foi adicionado ou removido, porque nenhum bug funcional foi encontrado).

### 2. `manage.py check`

```
System check identified no issues (0 silenced).
```

### 3. `makemigrations --check --dry-run`

```
No changes detected
```

Nenhum model está fora de sincronia com as migrations aplicadas.

### 4. Revisão das migrations aplicadas (0002–0005)

Todas aplicadas (`showmigrations`), e revisadas linha a linha nesta auditoria:

- **0002** — cria `Movement`, `HistoricalLocation`, ajusta `Location.address`/`Location.client` para `PROTECT`, adiciona o `CheckConstraint` `location_client_matches_type` e `movement_outro_requires_reason`. Consistente com os models atuais.
- **0003** (`seed_internal_locations`) — cria "Estoque Locus"/"Manutenção Locus" via `get_or_create()`, reverso `noop` (correto: reverter poderia derrubar `Movement`s que já referenciam essas Locations, e `PROTECT` nem deixaria).
- **0004** (`backfill_principal_locations`) — cobre os 3 casos documentados (cliente sem Location ativa / com Location ativa / inativo), preserva a separação endereço fiscal × operacional (sempre uma `Address` nova, nunca reaproveita a FK), idempotente por construção (condição de entrada é "não tem Location CLIENTE ativa").
- **0005** (`deactivate_test_duplicate_locations`) — único critério: nome exato em `TARGET_NAMES` **e** ausência de `Movement` como origem ou destino; nunca hard delete; `PROTECTED_NAMES` exclui as duas Locations internas por segurança redundante; reverso `noop` (decisão correta — não há como distinguir no banco "desativado por esta migration" de "desativado depois por outro motivo").

Nenhuma inconsistência encontrada entre o que as migrations fazem e o que os models declaram hoje.

### 5. Testes de concorrência

`test_double_submit_concurrency.py` e `test_movement_concurrency.py` — passando. Confirmam que a proteção contra reenvio é real a nível de banco (`ConsumedSubmissionToken.token` com índice `UNIQUE`, PostgreSQL serializa os INSERTs concorrentes), não apenas de sessão — o cenário de corrida do 3º reteste manual (dois POSTs quase simultâneos, mesma cópia de sessão em memória) continua coberto.

### 6. Testes de idempotência

Rodados como lote isolado nesta auditoria:

```
apps.operations.tests.test_double_submit
apps.operations.tests.test_double_submit_concurrency
apps.clients.tests.test_client_double_submit
apps.operations.tests.test_seed_internal_locations
apps.operations.tests.test_backfill_principal_locations
apps.operations.tests.test_deactivate_test_duplicate_locations
apps.operations.tests.test_movement_concurrency

Ran 47 tests — OK
```

Cobre: reenvio de formulário (Location/Client/Movement), e as três migrations de dados (seed, backfill, desativação) rodando de novo sem efeito colateral.

### 7. Testes de permissões

`apps/accounts/tests/test_permissions.py` — passando. A matriz completa (seção 11) continua testada num único arquivo, sem depender de cada view "lembrar" de checar o perfil.

### 8. Testes da ficha pública

`test_public_detail_view.py` + `test_public_detail_no_operational_leak.py` — passando. Nenhum dado operacional (Location atual, cliente atual, histórico) vaza na ficha pública.

### 9. Testes de timeline

`test_equipment_history_timeline.py` — passando. A fusão `StatusHistory` + `ConditionHistory` + `Movement` em `get_equipment_history_timeline()` continua correta e ordenada.

### 10. Testes de movimentação

`test_movement_services.py`, `test_movement_destination_selection.py`, `test_operations_views.py` — passando. Regras de transição por status (`_validate_transition`) e de destino exigido por tipo (`_REQUIRED_DESTINATION_TYPE`) continuam corretas.

### 11. Testes de consulta CNPJ/fallback

`test_lookup_service.py` — passando. Código-fonte também revisado nesta auditoria (não só os testes):

- `CompanyLookupService.lookup()` — normaliza, valida, resolve o provider por `settings.COMPANY_LOOKUP_PROVIDER`, nunca deixa uma exceção "crua" de um provider escapar (barreira final converte qualquer erro inesperado em `CompanyLookupUnavailable`).
- `BrasilAPICompanyLookupProvider` — timeout curto (3s connect / 5s read) e **sem retry**, por design: a consulta externa nunca pode travar o cadastro manual, que é sempre o fallback. Erros de rede/timeout/JSON inválido/formato inesperado viram `CompanyLookupUnavailable`; 404 vira `CompanyLookupNotFound`. Todos os campos da resposta são lidos com `.get(...) or ""` — nenhum `KeyError` possível por campo ausente.

Nenhum problema encontrado.

### 12. Testes de query count (proteção N+1)

Confirmado por grep em todo o repositório: `assertNumQueries` existe **apenas** em `apps/operations/tests/test_duplicate_locations_report.py`. É a única área do código com essa proteção explícita hoje, e ela passa — `find_duplicate_location_groups()` continua em exatamente 2 queries, independente do número de grupos/Locations (verificado também por leitura direta do código: uma agregação `GROUP BY` + uma única query com `annotate(Count(..., distinct=True))` para origem/destino, com `distinct=True` em cada `Count` evitando o fan-out clássico de combinar duas relações reversas no mesmo JOIN).

### Regressões da Fase 1

Todos os arquivos de teste da Fase 1 (CRUD de equipamento, geração de patrimônio, import legado, criação em lote, listagem/paginação/filtros, exportação, imutabilidade/reclassificação) fazem parte dos 379 testes acima e passaram sem alteração. Nenhuma regressão.

### Modelos revisados diretamente (não só via testes)

- **`Client`** (`apps/clients/models.py`) — `document` obrigatório, único entre valores não vazios (inclusive contra clientes soft-deletados, evitando cadastro duplicado da mesma empresa); `display_name()` é a única fonte de nome de exibição, reaproveitada pelos snapshots de `Movement`. Sem escopo de CRM, como documentado.
- **`Address`** (`apps/core/models.py`) — sempre uma linha própria por dono (fiscal × operacional nunca compartilham FK), `PROTECT` dos dois lados, histórico próprio via `HistoricalRecords()`.
- **`Location`** (`apps/operations/models.py`) — sem `UNIQUE(name)` (unidades homônimas de clientes diferentes continuam legítimas); `CheckConstraint location_client_matches_type` garante `type=CLIENTE ⟺ client preenchido` a nível de banco.
- **`Movement`** (`apps/operations/models.py`) — imutável por convenção (único caminho: `create_movement()`), snapshots (`*_name`) nunca recalculados, `Movement.client` deliberadamente ausente (seria ambíguo entre origem/destino), `CheckConstraint movement_outro_requires_reason`.

Nenhum bug estrutural encontrado em nenhum destes models.

---

## Parte 1 — Bugs encontrados/corrigidos

**Nenhum bug funcional** foi encontrado. Uma única inconsistência objetiva de documentação foi corrigida:

- **`apps/operations/services.py`, bloco de comentário acima de `find_duplicate_location_groups()`** — o texto ainda descrevia a ferramenta de diagnóstico (management command + tela somente-leitura) como "TEMPORÁRIA", herdado de quando a ferramenta de ESCRITA (já removida na Fase 4) também vivia nesta seção. Isso contradizia sua própria confirmação nesta conversa de que a página de diagnóstico somente leitura pode permanecer. Reescrevi o comentário para descrever a ferramenta como permanente/contínua, mantendo o histórico de por que ela existe. Reexecutei a suíte completa depois da mudança (379/379, sem impacto — é comentário, nenhum código foi alterado).

Nenhuma outra decisão estrutural nova surgiu durante a auditoria — nada que exigisse pausar para sua aprovação nesta parte.

---

## Parte 1 — Total final de testes

**379 testes, 379 passando**, mais o lote de 47 testes de idempotência/concorrência isolado e citado acima (subconjunto dos 379, não uma soma adicional).

## Parte 1 — Checks

- `manage.py check` → limpo.
- `makemigrations --check --dry-run` → `No changes detected`.
- `showmigrations` → todas aplicadas em `operations`, `clients`, `core`, `equipment`, `accounts`.

---

## Parte 2 — Confirmação de limpeza de código temporário

| Item | Status |
|---|---|
| Rota de limpeza via navegador (`.../limpar/`) | ✅ Removida — só resta um comentário em `urls.py` explicando a remoção |
| View temporária de escrita (`DuplicateLocationsCleanupView` ou equivalente) | ✅ Removida — nenhuma referência viva em `views.py` |
| Template temporário de limpeza | ✅ Removido — `ls templates/operations/` não lista nenhum arquivo de cleanup |
| Service morto (`DUPLICATE_CLEANUP`, `DuplicateLocationCleanup`) | ✅ Nenhuma referência em `services.py` |
| Código de debug (`print`, `pdb`, `breakpoint`, `console.log`) | ✅ Nenhuma ocorrência fora de `/tests/` |
| Logging temporário (`logging.*`/`logger.*`) | ✅ Nenhuma ocorrência em todo o código de aplicação (fora de `/tests/`) |
| Comentários obsoletos ("limpeza ainda pendente") | ✅ Corrigido (ver bug acima) — os demais comentários que mencionam a ferramenta removida já estavam em tom histórico/passado, corretos |
| Página de diagnóstico somente leitura | ✅ Mantida de propósito, como você autorizou |

Observação à parte, fora do escopo desta limpeza (não é sobre o incidente de duplicatas): `templates/base.html:7` tem um `TODO` genuíno e pré-existente sobre trocar o CDN do Tailwind por um build compilado — é uma pendência da Fase 1, não relacionada a este fechamento. Não mexi nisso; menciono só para registro, caso você queira tratar em outro momento.

---

## Parte 3 — Proposta de arquitetura: Manutenção e Higienização

**Nada abaixo foi implementado.** É proposta para sua aprovação.

### Regra de domínio central (ponto de partida)

Movimentação física (`Movement`) e evento técnico (`Maintenance`/`Cleaning`) são conceitos diferentes e devem continuar em tabelas diferentes:

- `Movement` já sabe registrar "o equipamento saiu do local X e foi para o local Y" — inclusive `ENVIO_MANUTENCAO`/`RETORNO_MANUTENCAO`, que hoje já mudam `Equipment.status` para `MANUTENCAO`/`DISPONIVEL` via `_validate_transition()`. Isso **não muda**.
- `Maintenance` registra diagnóstico, serviço executado, condição antes/depois — um evento técnico que pode ou não coincidir com uma movimentação física (ex.: manutenção preventiva feita no local, sem o equipamento sair do lugar).
- `Cleaning` é o mesmo raciocínio, seu próprio evento técnico.

A ligação entre os dois mundos é **opcional e unidirecional** (Maintenance/Cleaning apontam para Movement quando relevante; Movement nunca sabe que Maintenance/Cleaning existem) — isso mantém `Movement` exatamente como está hoje, sem acoplamento novo.

### App novo: `apps.maintenance`

Recomendo um app novo, dedicado, em vez de encaixar em `apps.operations` ou `apps.equipment` — mesmo raciocínio que já separa `clients`/`operations`/`equipment` por domínio: `operations` é o domínio físico (onde as coisas estão), `maintenance` seria o domínio técnico (o que foi feito nelas). `Maintenance` e `Cleaning` moram juntos no mesmo app, do mesmo jeito que `Location` e `Movement` já moram juntos em `operations`.

*(Decisão em aberto — ver lista ao final: você pode preferir manter tudo dentro de `apps.equipment`, já que ambos os eventos são sempre sobre um `Equipment`.)*

### Models propostos

#### `MaintenanceType` / `MaintenanceStatus`

```python
class MaintenanceType(models.TextChoices):
    PREVENTIVA = "PREVENTIVA", "Preventiva"
    CORRETIVA = "CORRETIVA", "Corretiva"

class MaintenanceStatus(models.TextChoices):
    ABERTA = "ABERTA", "Aberta"
    CONCLUIDA = "CONCLUIDA", "Concluída"
    CANCELADA = "CANCELADA", "Cancelada"
```

Preventiva e corretiva **não** viram tabelas separadas — são o mesmo tipo de evento técnico (diagnóstico → serviço → condição resultante), só muda a origem (planejada vs. reativa). Separar em tabelas duplicaria schema sem necessidade, o mesmo raciocínio que já evita duplicar dado entre Movement/Maintenance.

#### `Maintenance(TimeStampedModel, SoftDeleteModel)`

```python
equipment = FK(Equipment, on_delete=PROTECT, related_name="maintenances")
maintenance_type = CharField(choices=MaintenanceType)
status = CharField(choices=MaintenanceStatus, default=ABERTA)

diagnosis = TextField(blank=True)           # preenchido na abertura
service_performed = TextField(blank=True)   # preenchido no fechamento

condition_before = CharField(choices=Condition, blank=True)  # snapshot
condition_after = CharField(choices=Condition, blank=True)   # snapshot, no fechamento

departure_movement = FK(Movement, null=True, blank=True, on_delete=PROTECT, related_name="maintenance_departures")
return_movement = FK(Movement, null=True, blank=True, on_delete=PROTECT, related_name="maintenance_returns")

responsible = FK(User, on_delete=PROTECT, related_name="maintenances_responsible")
next_due_at = DateField(null=True, blank=True)
notes = TextField(blank=True)
closed_at = DateTimeField(null=True, blank=True)

created_by = FK(User, on_delete=PROTECT, related_name="maintenances_created")
history = HistoricalRecords()
```

`departure_movement`/`return_movement` são **opcionais dos dois lados**: cobrem tanto o caso "equipamento foi para a Location de manutenção" (linkado ao `ENVIO_MANUTENCAO`/`RETORNO_MANUTENCAO` já existentes) quanto o caso "manutenção feita no local, sem o equipamento se mover". Nenhum dos dois é obrigatório — forçar um deles quebraria o caso legítimo de manutenção em campo.

`history = HistoricalRecords()` em vez de uma tabela paralela tipo `StatusHistory`: `Maintenance` é uma "ficha" que muda de estado ao longo do tempo (aberta → concluída), exatamente o padrão que `Client`/`Location`/`Address` já usam com `django-simple-history` — reaproveitar a mesma ferramenta em vez de inventar uma variante do padrão `StatusHistory`/`ConditionHistory` (que existe em `Equipment` por razões históricas de quando `simple_history` ainda não estava no projeto).

**Constraint proposta** (mesmo espírito de `movement_outro_requires_reason`): `status != CONCLUIDA OR service_performed != ''` — não é possível concluir uma manutenção sem registrar o que foi feito.

#### `MaintenancePhoto`

```python
maintenance = FK(Maintenance, on_delete=CASCADE, related_name="photos")
image = ImageField(upload_to=...)
caption = CharField(blank=True)
uploaded_by = FK(User, on_delete=PROTECT)
uploaded_at = DateTimeField(auto_now_add=True)
```

`apps.attachments` já existe no projeto mas está documentado como "esqueleto vazio" (ver comentário em `CAN_ADD_PHOTOS`, `apps/accounts/permissions.py`). Proponho **não** depender dele agora — construir `MaintenancePhoto`/`CleaningPhoto` como models dedicados, simples, sem `GenericForeignKey` (o projeto não usa esse padrão em nenhum outro lugar). Se `apps.attachments` ganhar um propósito definido no futuro, migrar para lá é um passo isolado. *(Decisão em aberto.)*

#### `Cleaning(TimeStampedModel, SoftDeleteModel)`

```python
equipment = FK(Equipment, on_delete=PROTECT, related_name="cleanings")
performed_at = DateTimeField()
responsible = FK(User, on_delete=PROTECT, related_name="cleanings_responsible")
notes = TextField(blank=True)
next_due_at = DateField(null=True, blank=True)
movement = FK(Movement, null=True, blank=True, on_delete=PROTECT, related_name="cleanings")

created_by = FK(User, on_delete=PROTECT, related_name="cleanings_created")
```

**Assimetria deliberada em relação a `Maintenance`**: higienização não tem `status`/ciclo aberta→concluída, porque normalmente é uma visita única, sem a separação temporal "diagnóstico hoje, serviço executado semana que vem" que a manutenção corretiva pode ter. `Cleaning` se parece mais com `Movement` (evento atômico, registrado já completo) do que com `Maintenance` (ficha com estado). Por isso não usa `HistoricalRecords()` — não há "mudança de estado" para historiar, só o registro em si (que segue a mesma regra de nunca ser apagado fisicamente: "cancelar" um registro por engano usa `is_active=False`, herdado de `SoftDeleteModel`).

`MaintenancePhoto`/`CleaningPhoto` como modelos irmãos, mesma estrutura.

*(Se no futuro a operação precisar de higienizações que também se estendem por dias — ex.: descontaminação —, dá pra reavaliar dar um `status` a `Cleaning` também. Não antecipo isso agora.)*

### Relacionamento com `Equipment`

`Equipment` não ganha campos novos (nada como `last_maintenance_at` armazenado) — isso duplicaria dado que já vive em `Maintenance`/`Cleaning` e viraria fonte de divergência (o mesmo motivo pelo qual `Location.address` não é uma cópia do endereço fiscal do cliente). Se um dia precisar de listagem rápida "todo equipamento com manutenção vencida" (dashboard — fora do escopo desta etapa), isso é uma query/annotate sobre `Maintenance`, não um campo redundante em `Equipment`.

### Integração com Movement (sem duplicar informação)

- `Movement` continua sendo a **única** fonte de verdade de "onde o equipamento está" — `Maintenance`/`Cleaning` nunca escrevem em `Equipment.current_location`/`current_client`, só `create_movement()` faz isso, sem exceção.
- Quando existe uma movimentação física associada, `Maintenance`/`Cleaning` apenas **apontam** para o `Movement` já criado (link opcional) — nunca duplicam nome de local/cliente em snapshot próprio. Precisando exibir "onde isso aconteceu", a tela busca via `departure_movement.destination_location_name` etc., a mesma fonte que a timeline já usa.

### Integração com status/condition (ponto que precisa da sua decisão)

Hoje, `Equipment.status`/`Equipment.condition` só mudam por dois caminhos: `_validate_transition()` dentro de `create_movement()`, ou diretamente via `change_status()`/`change_condition()` (usados fora do fluxo de movimentação). Proposta:

- **Ao abrir uma `Maintenance` sem `departure_movement`** (manutenção em campo, equipamento não saiu do lugar): o serviço `open_maintenance()` chama `change_status(equipment, Status.MANUTENCAO, reason=...)` diretamente — senão o status do equipamento mentiria (diz "disponível" mas está em manutenção). Se `departure_movement` foi informado, o status já foi setado por aquele `Movement`, nenhuma chamada duplicada.
- **Ao concluir uma `Maintenance`** com `condition_after` preenchido: o serviço `close_maintenance()` chama `change_condition(equipment, condition_after, reason=...)` — a fonte de verdade de "condição atual" continua sendo `ConditionHistory`, e `Maintenance.condition_after` é só o snapshot narrativo do próprio registro de manutenção (mesmo padrão que `Movement` já usa: FK viva + snapshot imutável lado a lado).
- **Ao concluir uma `Maintenance` sem `return_movement`** (a que foi aberta sem movimentação): `close_maintenance()` reverte o status para o que era antes (provavelmente `DISPONIVEL`/`EM_OPERACAO`) via `change_status()`. Se `return_movement` existe, esse `Movement` já cuidou disso.
- `Cleaning` não deveria, a princípio, mudar `status`/`condition` — higienizar não altera a condição operacional do equipamento por si só. Se a operação achar que uma condição muito ruim é revelada durante a limpeza, isso é registrado em `notes` e — se quiser refletir no status — é uma `change_condition()` separada, feita pelo operador, não uma decisão automática de `Cleaning`.

Este é o ponto mais entrelaçado com o código existente (mexe no ciclo de vida de `Equipment.status`, hoje "propriedade" de `Movement`). Por isso trago como decisão explícita, não implemento sozinho.

### Timeline

Estender `get_equipment_history_timeline()` (`apps/equipment/services.py`) com mais dois blocos, no mesmo formato de dict já usado pelos três blocos atuais (`event_type`, `event_type_label`, `old_value_display`, `new_value_display`, `reason`, `changed_by`, `changed_at`) — nenhuma mudança de template necessária, o mesmo raciocínio que já permitiu adicionar o bloco de `Movement` na Fase 2 sem tocar a página.

- Bloco `manutencao`: uma entrada por `Maintenance`, timestamp em `closed_at` (se concluída) ou `created_at` (se ainda aberta) — `old_value_display` = diagnóstico, `new_value_display` = serviço executado (ou "Em aberto" se ainda não concluída).
- Bloco `higienizacao`: uma entrada por `Cleaning`, timestamp em `performed_at`.

*(Nuance registrada, não bloqueante: diferente dos outros três blocos — que já nascem como um evento imutável de ponto único no tempo — `Maintenance` tem dois momentos relevantes, abertura e fechamento. A proposta acima simplifica para uma única entrada na timeline por manutenção. Se quiser granularidade de "abriu em X, fechou em Y" como duas linhas, é um ajuste pequeno depois.)*

### Permissões

Nenhuma constante nova é estritamente necessária — o projeto já reservou isso:

```python
CAN_REGISTER_OPERATIONS = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL)
# manutenção/higienização/movimentação — Fase 2
```

Esse comentário já existe hoje em `apps/accounts/permissions.py`, escrito antes desta etapa começar — confirma que abrir/fechar `Maintenance`/`Cleaning` deve usar exatamente essa constante, sem inventar uma nova. Para consulta/visualização, o padrão já usado por `Movement` também se aplica: `CAN_VIEW_MOVEMENTS = (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA)` — reaproveitar (ou criar uma constante irmã `CAN_VIEW_MAINTENANCE` com os mesmos 4 perfis, se preferir nomear separado). Fotos: `CAN_ADD_PHOTOS` já existe com os 3 perfis certos e já cita explicitamente esta futura necessidade.

### Notificações futuras

Fora de escopo desta etapa (você pediu para não avançar). O único gancho que a proposta deixa pronto para isso, sem construir nada agora: `next_due_at` em `Maintenance`/`Cleaning` já é o dado que um futuro job de notificação/dashboard leria — nenhuma estrutura adicional precisa existir hoje só para permitir isso depois.

### Estados e transições

```
Maintenance:  ABERTA ──(close_maintenance)──> CONCLUIDA
                 │
                 └──(cancel_maintenance)──> CANCELADA

Cleaning:     sem estado — nasce completo (como Movement); "desfazer" é is_active=False
```

Dois serviços novos, seguindo a disciplina já usada (`create_movement()`, `change_status()`): `open_maintenance()`, `close_maintenance()`, `cancel_maintenance()` — nunca `Maintenance.objects.create()`/`.save()` direto em view. `Cleaning` ganha só `create_cleaning()`.

### Histórico imutável

- `Maintenance`: mutável entre `ABERTA`→`CONCLUIDA`/`CANCELADA`, com `HistoricalRecords()` capturando cada mudança automaticamente (mesmo padrão de `Client`/`Location`).
- `Cleaning`: imutável após criado, mesmo espírito de `Movement` — nenhum campo é editado depois (correção de erro = `is_active=False` + novo registro correto, nunca `UPDATE` do existente).
- Em nenhum dos dois casos existe exclusão física — `SoftDeleteModel` cobre os dois.

### Testes propostos (mesma cobertura que `Movement`/`Location` já têm hoje)

- Criação/fechamento/cancelamento de `Maintenance` via serviço (nunca direto no model).
- `CheckConstraint` de fechamento sem `service_performed`.
- Integração opcional com `Movement` (com e sem `departure_movement`/`return_movement`).
- Integração com `change_status()`/`change_condition()` nos dois cenários (com/sem movimentação associada).
- Idempotência/double-submit nas telas de abrir/fechar manutenção e registrar higienização (mesmo `SubmissionGuard` já usado em `Location`/`Movement`).
- Timeline — os dois blocos novos aparecem corretamente combinados com os quatro já existentes.
- Permissões — os 4 perfis testados contra as views novas.
- Fotos — upload, associação correta, nenhuma foto órfã sobrevive à exclusão em cascata da manutenção.

### Migrations previstas

Uma migration `0001_initial` no novo app `apps.maintenance` (ou dentro de `apps.operations`, se a decisão de app for essa) criando `Maintenance`, `MaintenancePhoto`, `Cleaning`, `CleaningPhoto`, `HistoricalMaintenance`. Nenhuma migration de dados necessária — não há dado legado de manutenção/higienização para migrar.

### Riscos

- **Maior risco**: o ponto de integração com `status`/`condition` (acima) é o único lugar onde `Maintenance` passa a poder mudar `Equipment.status`, que hoje é território exclusivo de `Movement`. Se a regra não for bem isolada nos dois serviços (`open_maintenance()`/`close_maintenance()`), existe risco real de o status divergir da movimentação física (ex.: equipamento marcado `MANUTENCAO` por uma `Maintenance` em campo, mas nunca revertido se `close_maintenance()` não for chamada). Mitigação proposta: `close_maintenance()` deveria ser **obrigatória** para toda `Maintenance` aberta sem `departure_movement` antes de permitir qualquer nova movimentação do equipamento — regra a validar com você.
- Risco menor: telas de fotos exigem armazenamento de arquivo (`MEDIA_ROOT`/S3/etc.) — verificar se já existe alguma configuração de storage no projeto ou se isso é uma decisão de infraestrutura nova.
- Risco menor: `apps.attachments` ficar permanentemente órfão se `MaintenancePhoto`/`CleaningPhoto` nunca migrarem para lá — aceitável por ora, mas vale decidir o destino de `apps.attachments` em algum momento (não agora).

---

## Decisões em aberto que precisam da sua aprovação

1. **App novo `apps.maintenance` vs. encaixar em `apps.operations`/`apps.equipment`** — recomendo app novo (separação por domínio), mas é uma decisão sua.
2. **Integração com `status`/`condition`** — se `open_maintenance()`/`close_maintenance()` podem chamar `change_status()`/`change_condition()` diretamente (proposta acima), e a regra de "toda manutenção aberta sem movimentação precisa ser fechada antes de nova movimentação do equipamento".
3. **`MaintenancePhoto`/`CleaningPhoto` como models dedicados agora, vs. esperar `apps.attachments` ganhar forma** — recomendo models dedicados agora.
4. **Granularidade da timeline de `Maintenance`** — uma entrada por manutenção (proposta) vs. duas (abertura + fechamento).
5. **Nome da constante de visualização** — reaproveitar `CAN_VIEW_MOVEMENTS` ou criar `CAN_VIEW_MAINTENANCE` (mesmos 4 perfis nos dois casos).
6. **`Cleaning` sem estado (proposta) vs. com o mesmo ciclo `ABERTA`/`CONCLUIDA` de `Maintenance`** — recomendo sem estado, pelo raciocínio de assimetria acima.

Nenhuma dessas decisões foi implementada. Aguardando sua confirmação antes de qualquer código novo desta etapa.
