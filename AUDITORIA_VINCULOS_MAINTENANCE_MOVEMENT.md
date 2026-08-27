# Auditoria/fortalecimento dos vínculos Maintenance/Cleaning × Movement (27/08/2026)

Escopo: só os vínculos `departure_movement`/`return_movement`/`Cleaning.movement`. Nenhuma UI, view, template ou foto foi criada. Nenhum signal foi introduzido.

---

## 1. `departure_movement` — validações (`_validate_departure_movement()`)

Já eram garantidas antes desta auditoria: pertence ao mesmo `Equipment`; é do tipo `ENVIO_MANUTENCAO`; não está vinculado a outra `Maintenance`.

Adicionado nesta auditoria:

1. `movement.pk is not None` — rejeita um Movement em memória, não salvo (nunca confiar só no `OneToOneField`, que só protege depois de já ter chegado ao banco).
2. `equipment.status == MANUTENCAO` no momento da abertura — coerência cronológica. Se o status já não é mais MANUTENCAO, a viagem física daquele Movement já foi encerrada por um retorno (via `RETORNO_MANUTENCAO`/`RETORNO_ESTOQUE`, dentro ou fora de outra ficha); vincular esse `departure_movement` "velho" a uma ficha nova seria registrar uma manutenção sobre uma viagem que já terminou.

Ordem completa hoje: pk registrado → mesmo equipamento → tipo `ENVIO_MANUTENCAO` → não reclamado por outra ficha → `equipment.status == MANUTENCAO`.

## 2. `return_movement` — validações (`_validate_return_movement()`)

Já eram garantidas antes: pertence ao mesmo `Equipment`; tipo em `{RETORNO_MANUTENCAO, RETORNO_ESTOQUE}`; não vinculado a outra `Maintenance`.

**Sobre manter os dois tipos**: não restringi a só `RETORNO_MANUTENCAO`. `_TRANSITION_RULES` (`apps.operations.services`) já aceita `MANUTENCAO` como status de origem para os dois, e existe um cenário real de negócio em que o time decide levar o equipamento consertado direto ao estoque em vez de "devolvê-lo" pela mesma via — já coberto desde a revisão anterior (Matriz 2). Restringir quebraria esse caminho legítimo sem nenhuma razão de domínio para isso.

Adicionado nesta auditoria:

3. `movement.pk is not None`.
4. `movement.created_at > maintenance.created_at` — o retorno precisa ter acontecido depois da abertura desta ficha.
5. Quando `departure_movement` existe: `movement.created_at > departure_movement.created_at` — o retorno precisa vir depois do envio, nunca antes ou simultâneo.
6. Quando `departure_movement` é `None` e o tipo é `RETORNO_MANUTENCAO`: **rejeitado**. "Retorno da manutenção" pressupõe um envio físico prévio que, nessa ficha (manutenção em campo, sem `departure_movement`), nunca aconteceu. `RETORNO_ESTOQUE` continua aceito nesse caso — não presume nenhuma viagem específica, só que o equipamento foi levado ao estoque, o que é uma combinação real e coerente mesmo para manutenção só em campo.

Ordem completa hoje: pk registrado → mesmo equipamento → tipo válido → não reclamado por outra ficha → posterior à abertura → (se houver envio) posterior ao envio → (se não houver envio) tipo não pode ser `RETORNO_MANUTENCAO`.

## 3. Maintenance sem Movement

Confirmado, sem necessidade de alteração de código:

- `departure_movement=None` já significava "manutenção feita sem envio físico" — comportamento inalterado (Matriz 1, linhas A/B).
- O cenário "`return_movement` sozinho, conceitualmente impossível" tinha exatamente UMA combinação incoerente — `RETORNO_MANUTENCAO` sem `departure_movement` — agora bloqueada pelo item 6 acima. `RETORNO_ESTOQUE` sem `departure_movement` é coerente e continua permitido (com teste novo de confirmação, não regressão).
- `status_before` já só era usado para restauração quando `departure_movement_id is None` (`_restore_status_if_owned()`, curto-circuita na primeira linha) — não precisou de nenhuma mudança; só confirmação.

## 4. `Cleaning` × `Movement`

Já garantido: quando `Cleaning.movement` é informado, precisa pertencer ao mesmo `Equipment` (`create_cleaning()` já rejeitava um Movement de outro equipamento).

Não há razão de domínio para restringir o `MovementType` aceito por `Cleaning.movement` — higienizar antes de instalar, ao retirar, ao transferir, ao voltar ao estoque ou da manutenção, ou até um `OUTRO` anotado são todas combinações reais. Por isso, mantido sem restrição de tipo, e essa decisão foi documentada explicitamente (não deixada implícita): no `help_text` do campo em `models.py` e no docstring de `create_cleaning()`.

## 5. Defesa no backend

Todas as checagens novas e antigas vivem nos services (`_validate_departure_movement()`, `_validate_return_movement()`, `create_cleaning()`), nunca em UI/formulário. Todas levantam `ValueError` (mesmo padrão de exceção de domínio do resto do projeto). `open_maintenance()`/`close_maintenance()` seguem `@transaction.atomic` — qualquer `ValueError` levantado no meio reverte 100% da transação (nenhuma escrita parcial), confirmado por teste em cada caso novo (`_assert_sem_alteracao_parcial()`).

Nenhum signal foi introduzido. Nenhum dado foi duplicado no banco só para viabilizar as checagens — todas comparam campos já existentes (`equipment_id`, `movement_type`, `created_at`, `equipment.status`) ou usam consultas de existência (`Maintenance.objects.filter(...).exists()`), nunca um novo campo espelhado.

Um POST manipulado tentando forçar um `departure_movement`/`return_movement`/`Cleaning.movement` inválido é rejeitado pelo service independentemente do que a UI (futura) filtrar ou deixar de filtrar — a validação nunca dependeu de dropdown filtrado, porque a UI ainda nem existe.

## 6. Concorrência

**Nenhum novo `select_for_update()` em `Movement` foi necessário.** Análise:

Todo `Movement` pertence a exatamente um `Equipment`. A única forma de duas transações disputarem o mesmo `departure_movement`/`return_movement` é as duas operarem sobre o MESMO `Equipment` — e esse já é o lock que `open_maintenance()`/`close_maintenance()`/`create_movement()` tomam primeiro (`select_for_update()`, sempre a primeira operação de banco de cada função, mesma ordem nas três). Sob READ COMMITTED (padrão PostgreSQL/Django), a transação que perde a corrida pelo lock de `Equipment` só chega a ler `Maintenance`/`Movement` depois que a vencedora já comitou — vê o vínculo já reivindicado e falha com mensagem clara, nunca com condição de corrida real.

Para `return_movement` a garantia é ainda mais forte: só pode existir uma `Maintenance` `ABERTA` (e ativa) por equipamento (`UniqueConstraint`), então nunca há duas fichas do mesmo equipamento disputando fechamento ao mesmo tempo.

Ordem de locks documentada e inalterada nesta auditoria (sem risco de deadlock, pois nenhuma das funções segura um segundo lock esperando a outra):

| Função | Ordem de locks |
|---|---|
| `open_maintenance()` | `Equipment` (único) |
| `close_maintenance()` / `cancel_maintenance()` | `Maintenance` → `Equipment` |
| `create_movement()` | `Equipment` (único) |

**Defesa em profundidade adicionada mesmo assim**: `open_maintenance()` e `close_maintenance()` agora capturam `IntegrityError` ao salvar e convertem para `ValueError` com mensagem de domínio. Não porque a corrida analisada acima seja alcançável hoje pelos caminhos públicos existentes, mas para nunca deixar um `IntegrityError` cru vazar até uma view futura — por exemplo, se algum caminho de chamada novo for adicionado sem preservar a mesma ordem de locks. Tratamento previsível no service, como pedido.

Teste de corrida real (`TransactionTestCase` + threads + PostgreSQL real) cobrindo exatamente o cenário pedido: duas tentativas simultâneas de `open_maintenance()` reivindicando o MESMO `departure_movement` — confirma exatamente um vencedor, exatamente um perdedor com `ValueError`, nunca as duas sucedendo nem um `IntegrityError` cru.

## 7. Testes novos

Arquivo novo: `apps/maintenance/tests/test_maintenance_movement_vinculos_auditoria.py` — **7 testes novos**:

| Teste | Cobre |
|---|---|
| `test_return_movement_de_outro_equipamento_rejeitado` | return de outro equipamento |
| `test_return_anterior_ao_departure_rejeitado` | return anterior ao departure |
| `test_return_anterior_a_abertura_sem_departure_rejeitado` | return anterior à própria abertura (sem departure) |
| `test_return_movement_ja_vinculado_a_outra_maintenance_rejeitado` | Movement de retorno já usado por outra Maintenance |
| `test_retorno_manutencao_sem_departure_movement_rejeitado` | cenário conceitualmente impossível — RETORNO_MANUTENCAO sem envio |
| `test_retorno_estoque_sem_departure_movement_aceito` | confirmação (não regressão) — RETORNO_ESTOQUE sem envio continua válido |
| `test_corrida_por_mesmo_departure_movement_termina_com_exatamente_um_vencedor` | corrida de duas tentativas reivindicando o mesmo Movement |

Casos já cobertos por testes existentes (não duplicados): departure de outro equipamento e departure de tipo errado (`test_maintenance_services.py`, `LinhaCComEnvioManutencaoTest`); return de tipo errado (`test_maintenance_movement_compatibility.py`); Cleaning apontando para Movement de outro equipamento (`test_cleaning_services.py`). Cada teste de rejeição novo confirma rollback integral (`Maintenance` continua `ABERTA`, sem `return_movement`, sem `closed_at`, sem `service_performed`).

**Total final de testes**:

- `apps.maintenance`: **54/54** (47 anteriores + 7 novos).
- Suíte completa do projeto: **433/433** passando contra PostgreSQL real (426 anteriores + 7 novos).
- `manage.py check`: limpo.
- `makemigrations --check --dry-run`: `No changes detected` (após aplicar a migration `0003_alter_cleaning_movement_and_more`, gerada só pelas mudanças de `help_text` — nenhuma mudança de schema/coluna/constraint).

---

## Invariantes finais (resumo)

1. `departure_movement`, quando presente, sempre pertence ao mesmo equipamento, é sempre `ENVIO_MANUTENCAO`, está sempre registrado no banco (`pk` não nulo), nunca está vinculado a outra `Maintenance`, e o equipamento está sempre em `MANUTENCAO` no instante da abertura.
2. `return_movement`, quando presente, sempre pertence ao mesmo equipamento, é sempre `RETORNO_MANUTENCAO` ou `RETORNO_ESTOQUE`, está sempre registrado no banco, nunca está vinculado a outra `Maintenance`, sempre ocorre depois da abertura da ficha e (quando há `departure_movement`) sempre depois dele, e nunca é `RETORNO_MANUTENCAO` numa ficha sem `departure_movement`.
3. `status_before` só é usado para restauração quando a própria `Maintenance` foi responsável pela transição para `MANUTENCAO` (`departure_movement is None`) — nunca quando um Movement já fez a mudança.
4. `Cleaning.movement`, quando presente, sempre pertence ao mesmo equipamento; qualquer `MovementType` é aceito, por decisão documentada.
5. Toda validação de vínculo vive no service, nunca depende de UI, sempre levanta `ValueError`, sempre roda dentro de `@transaction.atomic` com rollback integral.
6. Nenhum lock novo em `Movement` é necessário — o lock de `Equipment`, já tomado primeiro em todas as funções relevantes, serializa toda disputa possível pelos vínculos; `IntegrityError` nunca vaza cru — sempre convertido para `ValueError` de domínio.

## Arquivos alterados

- `apps/maintenance/services.py` — docstring do módulo (Matriz 1 e nova seção "AUDITORIA DE VÍNCULOS"); `_validate_departure_movement()` com 2 checagens novas; `_validate_return_movement()` com parâmetro `maintenance` novo e 4 checagens novas; `open_maintenance()`/`close_maintenance()` com captura de `IntegrityError`→`ValueError`; comentário reforçado em `create_cleaning()`.
- `apps/maintenance/models.py` — `help_text` de `departure_movement`, `return_movement` e `Cleaning.movement` reforçados, documentando a divisão de responsabilidade entre o campo (integridade referencial) e o service (integridade de domínio).
- `apps/maintenance/migrations/0003_alter_cleaning_movement_and_more.py` — nova (só `help_text`, sem mudança de schema).
- `apps/maintenance/tests/test_maintenance_movement_vinculos_auditoria.py` — novo, 7 testes.

Nenhum deploy foi feito. Nenhuma UI, view, template ou foto foi implementada.
