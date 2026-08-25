# Fase 2 — Operação: v1.1, delta de aprovação

Status: **proposta, aguardando aprovação — nada abaixo foi implementado.** Complementa `docs/arquitetura-fase2-operacao.md` (v1.0); não repete o que já foi aprovado sem mudança (seções 12–15 do seu retorno: CompanyLookupService, endereço fiscal×operacional, importação futura, permissões — todas mantidas exatamente como na v1.0).

---

## 1. Alterações em relação à v1.0

| # | v1.0 | v1.1 |
|---|---|---|
| 1 | `current_client`/`current_location` tratados como equivalentes | `current_location` é a fonte canônica; `current_client` é campo derivado, `editable=False`, só escrito por `create_movement()` |
| 2 | `Movement.client` denormalizado de `destination_location.client` | **Removido.** Sem razão técnica forte para mantê-lo (ver seção 3) |
| 3 | Sem snapshot de nome | `Movement` ganha 4 campos de snapshot imutável (seção 4) |
| 4 | `Address` com `on_delete=CASCADE` | `on_delete=PROTECT` em `fiscal_address` e `Location.address` |
| 5 | `Movement.reason` obrigatório sempre | `blank=True`, exceto `movement_type=OUTRO` (validado no service + `CheckConstraint`) |
| 6 | Não especificado | `Client.document` editável depois da criação, com validação completa + auditoria |
| 7 | Em aberto | `django-simple-history` aprovado em `Client`, `Location` **e `Address`** (ver seção 5) |
| 10 | Regras descritas em texto | Duas regras viram `CheckConstraint` real; as demais ficam documentadas como invariantes de service (justificativa seção 6) |
| 11 | Não detalhado | `select_for_update()` + pseudofluxo transacional final (seção 8/9) |

---

## 2. Model final: `Movement`

```python
class MovementType(models.TextChoices):
    INSTALACAO = "INSTALACAO", "Instalação"
    RETIRADA = "RETIRADA", "Retirada"
    TRANSFERENCIA = "TRANSFERENCIA", "Transferência"
    RETORNO_ESTOQUE = "RETORNO_ESTOQUE", "Retorno ao estoque"
    ENVIO_MANUTENCAO = "ENVIO_MANUTENCAO", "Envio para manutenção"
    RETORNO_MANUTENCAO = "RETORNO_MANUTENCAO", "Retorno da manutenção"
    OUTRO = "OUTRO", "Outro"


class Movement(models.Model):
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=20, choices=MovementType.choices)

    # Navegação/integridade — FKs vivas, para joins e para os links da timeline.
    origin_location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.PROTECT, related_name="movements_from")
    destination_location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.PROTECT, related_name="movements_to")

    # Snapshot histórico imutável — ver seção 4. Preenchidos SÓ por
    # create_movement(), nunca recalculados depois.
    origin_location_name = models.CharField(max_length=150, blank=True)
    destination_location_name = models.CharField(max_length=150, blank=True)
    origin_client_name = models.CharField(max_length=200, blank=True)
    destination_client_name = models.CharField(max_length=200, blank=True)

    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="movements_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                check=~models.Q(movement_type="OUTRO") | ~models.Q(reason=""),
                name="movement_outro_requires_reason",
            ),
        ]
```

`origin_location`/`destination_location` usam `on_delete=PROTECT` (não `CASCADE`, não `SET_NULL`): uma `Location` referenciada por qualquer `Movement` não pode ser excluída fisicamente — mesma filosofia de preservação histórica já usada em `created_by` em todo o projeto. Isso não conflita com "unidade fica inativa" (`Location.is_active=False`, soft delete já existente via `SoftDeleteModel`), só impede exclusão física de uma unidade com histórico.

`Movement.client` **removido** — ver justificativa abaixo.

---

## 3. `Movement.client`: removido, sem substituto denormalizado

Concordo com o seu exemplo — `destination_location.client` significa coisas diferentes dependendo do tipo de movimentação (em "Retirada" o destino tipicamente não tem cliente, mas o evento é *sobre* o cliente de origem), então um único campo `client` seria ambíguo por natureza, não só um detalhe de implementação.

Não vejo razão técnica forte para manter um campo denormalizado aqui. As duas necessidades que ele resolveria são cobertas de outra forma:
- **Consulta "todas as movimentações do Cliente X"**: `Movement.objects.filter(Q(origin_location__client=X) | Q(destination_location__client=X))` — um filtro com OR sobre FK, não um JOIN caro o suficiente para justificar denormalização numa tabela deste volume (movimentações, não milhões de linhas).
- **Exibição histórica correta mesmo se o cliente for renomeado**: resolvida pelos snapshots (seção 4), não por uma FK.

Se no futuro esse filtro se mostrar genuinamente lento em produção, a resposta correta é um índice composto, não reintroduzir o campo ambíguo.

---

## 4. Snapshots históricos — campos e justificativa

Campos: `origin_location_name`, `destination_location_name`, `origin_client_name`, `destination_client_name` — todos `CharField`, preenchidos uma única vez por `create_movement()`, nunca recalculados.

**Por que só nome, não endereço completo:** o requisito é a timeline continuar legível/correta depois de uma renomeação (seu exemplo: "Unidade Maringá" renomeada em 2027). Endereço, telefone etc. não aparecem na linha da timeline hoje (`event_type_label` / `old_value_display` / `new_value_display` / `reason`) — copiar mais que o nome seria dado sem uso concreto, o que você mesmo pediu para evitar.

**Qual nome de cliente usar — decisão explícita:** `trade_name or company_name` (nome fantasia se existir, senão razão social). Esta é exatamente a mesma regra que `Client.__str__()` já usa hoje (`apps/clients/models.py`) — reaproveito a função/propriedade existente (`Client.__str__()` ou uma extração dela para `Client.display_name`, para não duplicar a regra em dois lugares) em vez de inventar uma segunda convenção de "nome de exibição". Assim o snapshot da timeline sempre bate com o que aparece em qualquer outro lugar do sistema no mesmo instante.

Nome da localização é só `Location.name`, sem fallback — é um único campo, não há ambiguidade.

Quando origem/destino não têm cliente (ex.: estoque), o respectivo `*_client_name` fica `""` (string vazia, não nulo) — consistente com o restante do projeto usando `blank=True` sem `null=True` em campos de texto.

---

## 5. Política final de `Address` e auditoria

`fiscal_address` (em `Client`) e `address` (em `Location`) passam a `on_delete=models.PROTECT`. Direção importa: esse `on_delete` controla o que acontece com o `Client`/`Location` **quando o `Address` referenciado é excluído** — com `PROTECT`, excluir um `Address` que ainda tem um `Client`/`Location` apontando para ele levanta `ProtectedError` e a exclusão é bloqueada, em vez de arrastar o cliente/unidade junto (o risco que você apontou). Edição de endereço continua funcionando normalmente — é `address.cep = "..."; address.save()`, não um `DELETE` seguido de `INSERT`, então `PROTECT` nunca atrapalha o fluxo normal de correção de endereço.

**Particularidade do Django que vale registrar:** como é uma relação `OneToOneField` de "posse" (cada `Address` pertence exclusivamente a um `Client` ou a uma `Location`, nunca compartilhado — ver v1.0 seção 6), `CASCADE` seria o padrão "natural" do Django para esse tipo de relação de composição. Estou me afastando desse padrão aqui deliberadamente, seguindo sua instrução — o trade-off é que uma exclusão física de `Address` feita por engano (ex.: via Django admin) passa a falhar ruidosamente (bom, é o que você quer) em vez de silenciosamente arrastar o cliente. Nenhum fluxo do sistema precisa excluir um `Address` diretamente, então não há efeito colateral prático.

**Auditoria do `Address`:** confirmado — histórico em `Client`/`Location` via `simple_history` **não** captura edições feitas diretamente no objeto `Address` relacionado, porque o `Client`/`Location` em si não muda de linha quando só o `Address` apontado é editado (a FK continua igual; só os campos do outro lado mudam). Solução mínima: `Address` ganha seu próprio `history = HistoricalRecords()`, exatamente como `EquipmentModel` e `Equipment` já têm históricos independentes e paralelos hoje (não um histórico "unificado" cobrindo os dois) — mesmo padrão já validado na Fase 1, não é arquitetura nova. `django-simple-history` já é dependência do projeto; isso é só wiring, sem settings novos.

---

## 6. Constraints de banco propostas

Regra geral aplicada: um `CheckConstraint` do PostgreSQL só pode expressar uma condição sobre colunas da MESMA linha/tabela — não pode fazer join. Isso decide o que vira constraint de banco e o que fica só no service.

**Viram `CheckConstraint` (mesma linha, genuinamente aplicável):**

1. `Location`: `type = 'CLIENTE' ⟺ client_id IS NOT NULL` — cobre as duas regras da sua lista ("`type=CLIENTE` deve ter `client`" e "`ESTOQUE`/`MANUTENCAO`/`TRANSPORTE` não deve ter `client`") como uma única constraint, já que são as duas metades da mesma implicação bicondicional.
2. `Movement`: `movement_type != 'OUTRO' OR reason != ''` — motivo obrigatório só para `OUTRO` (seção 5 do seu pedido).

**Ficam só no service (não são expressáveis como `CheckConstraint` de uma linha):**

3. "Destino de uma instalação precisa ser `Location(type=CLIENTE)`" — depende do `type` de uma linha *diferente* (a `Location` referenciada), não uma coluna própria do `Movement`. Alternativa seria denormalizar `destination_location_type` no próprio `Movement` só para viabilizar a constraint — rejeitei por ser exatamente o tipo de cópia desnecessária que você pediu para evitar (seção 3 do seu retorno). Fica como validação em `create_movement()`.
4. "Origem deve corresponder à localização atual do equipamento imediatamente antes da movimentação" — não é uma regra de estado, é uma regra procedural/temporal (compara com o estado no momento exato da transação). Resolvida arquiteturalmente, não por constraint: `create_movement()` **nunca aceita `origin_location` como entrada do chamador** — ele é sempre lido de `equipment.current_location` depois do lock (`select_for_update()`, seção 9). Isso elimina a possibilidade de origem divergente por construção, não por validação a posteriori.
5. `current_client` coerente com `current_location.client` — cross-table (`Equipment.current_client` vs `Equipment.current_location.client`, que é uma tabela diferente), não expressável como `CheckConstraint`. Fica garantido por `create_movement()` sempre derivar os dois no mesmo `save()` (nunca escritos em passos separados) + teste de invariante dedicado (seção 10). Considerei um `CheckConstraint` comparando `current_client_id` a algo — não é possível em Postgres sem uma função/trigger, o que seria a arquitetura excessiva que você pediu para evitar.

---

## 7. Invariantes garantidos pelo service (`create_movement()`)

- Equipamento é lido sob `select_for_update()` antes de qualquer validação (seção 9).
- `origin_location` é sempre derivado do estado bloqueado, nunca aceito como parâmetro confiável.
- Transição rejeitada explicitamente (`ValueError`, sem alteração parcial) se o `status`/`current_location` atuais não permitirem o `movement_type` pedido (tabela da seção 10).
- `destination_location.type == CLIENTE` exigido para `INSTALACAO` (regra 3 da seção 6 acima).
- `reason` obrigatório quando `movement_type == OUTRO` (reforça a constraint da seção 6, mesmo padrão de dupla camada já usado em `change_status()`/`change_condition()`).
- `current_location`/`current_client` sempre escritos juntos, no mesmo `save()`, nunca em passos separados — nenhuma janela onde um dos dois reflete o movimento e o outro não.
- Retorno de manutenção direto para cliente **não é uma operação atômica única** — o service não oferece esse caminho; são duas chamadas a `create_movement()` (retorno + nova instalação), cada uma com sua própria validação de transição.
- `INATIVO` nunca é um destino de `create_movement()` — fica fora do enum `MovementType` inteiramente; inativação continua exclusiva de `supersede_equipment()`.

---

## 8. Pseudofluxo transacional final de `create_movement()`

```python
@transaction.atomic
def create_movement(data: NewMovementData) -> Movement:
    equipment = Equipment.objects.select_for_update().get(pk=data.equipment_id)

    # Origem NUNCA vem do chamador — sempre o estado já bloqueado.
    origin_location = equipment.current_location

    new_status = _validate_transition(
        equipment=equipment,
        movement_type=data.movement_type,
        destination_location=data.destination_location,
    )  # levanta ValueError com mensagem clara se a transição não for permitida;
       # nenhuma escrita acontece antes desta validação passar.

    if data.movement_type == MovementType.OUTRO and not data.reason.strip():
        raise ValueError("Movimentação do tipo 'Outro' exige motivo/observação.")

    movement = Movement.objects.create(
        equipment=equipment,
        movement_type=data.movement_type,
        origin_location=origin_location,
        destination_location=data.destination_location,
        origin_location_name=origin_location.name if origin_location else "",
        destination_location_name=data.destination_location.name if data.destination_location else "",
        origin_client_name=_client_display_name(origin_location.client) if origin_location and origin_location.client else "",
        destination_client_name=_client_display_name(data.destination_location.client) if data.destination_location and data.destination_location.client else "",
        reason=data.reason,
        created_by=data.created_by,
    )

    if new_status is not None and new_status != equipment.status:
        # Reaproveita change_status() já existente — não duplica gravação de StatusHistory.
        change_status(
            equipment=equipment,
            new_status=new_status,
            reason=f"Alterado automaticamente por movimentação: {movement.get_movement_type_display()}.",
            changed_by=data.created_by,
        )

    equipment.current_location = data.destination_location
    equipment.current_client = data.destination_location.client if data.destination_location else None
    equipment.save(update_fields=["current_location", "current_client", "updated_at"])

    return movement
```

Qualquer exceção em qualquer ponto (validação, `Movement.objects.create()`, `change_status()`, `save()` final) desfaz a transação inteira — nenhum `Movement` órfão, nenhum status alterado sem `current_location` correspondente, nenhuma escrita parcial.

---

## 9. `select_for_update()` e concorrência

Mesma estratégia já validada em `create_equipment()`/`create_equipment_batch()` (Fase 1), agora sobre a linha do `Equipment` em vez da linha do `EquipmentModel`: `select_for_update()` serializa duas movimentações concorrentes do MESMO equipamento — a segunda thread só obtém o lock depois que a primeira transação commita (ou sofre rollback), e nesse momento já lê o `current_location`/`status` **pós-primeira-movimentação**, não o estado de antes. Se a segunda operação não for mais válida contra esse novo estado, é rejeitada — nunca aplicada sobre uma premissa desatualizada.

Teste de concorrência planejado (mesmo rigor de `test_patrimonio_generation.py`/`test_batch_creation.py`, `TransactionTestCase` com threads e conexões reais contra PostgreSQL): equipamento em `DISPONIVEL`/estoque; duas threads disparadas ao mesmo tempo — uma tentando `INSTALACAO` no Cliente A, outra tentando `INSTALACAO` no Cliente B. Exatamente uma deve suceder; a outra deve falhar com `ValueError` claro (porque, quando finalmente obtém o lock, o equipamento já está `EM_OPERACAO`, não mais `DISPONIVEL`); o estado final (`current_location`/`current_client`/`status`) deve corresponder inteiramente à movimentação que venceu a corrida, sem mistura.

---

## 10. Regras finais status × movimentação

| Movimentação | Status exigido | Novo status | Efeito em local/cliente |
|---|---|---|---|
| Instalação | `DISPONIVEL` | `EM_OPERACAO` | destino deve ser `Location(type=CLIENTE)` |
| Retirada | `EM_OPERACAO` | `DISPONIVEL` | destino = estoque |
| Transferência | `EM_OPERACAO` | *(sem mudança)* | novo destino, `current_client` deriva do novo destino |
| Retorno ao estoque | `EM_OPERACAO` ou `MANUTENCAO` | `DISPONIVEL` | destino = estoque |
| Envio para manutenção | `DISPONIVEL` ou `EM_OPERACAO` | `MANUTENCAO` | destino = local de manutenção |
| Retorno da manutenção | `MANUTENCAO` | `DISPONIVEL` | destino = estoque, **sempre** — nunca direto a cliente |

Confirmado: retorno da manutenção direto para cliente é sempre 2 eventos (retorno + instalação nova), nunca 1. `INATIVO` fora do enum. Transição fora da tabela → `ValueError`, zero escrita parcial.

**Nota arquitetural registrada, não implementada agora:** `RETORNO_MANUTENCAO → DISPONIVEL` assume que sair fisicamente da manutenção equivale a estar liberado para uso. Quando o fluxo completo de manutenção existir, isso pode precisar de um estado intermediário (ex.: "aguardando inspeção final"). Não resolvido nesta fundação, por decisão sua.

---

## 11. Testes adicionais introduzidos por estas decisões

- Invariante `current_client == current_location.client` (ou `None`) após toda sequência de movimentações — incluindo depois de `TRANSFERENCIA` para uma `Location` sem cliente e para uma com cliente.
- `current_client` nunca editável isoladamente (tentativa direta via form/serviço fora de `create_movement()` não deve existir — teste negativo de superfície).
- Renomear uma `Location` ou um `Client` depois de um `Movement` não altera os campos de snapshot (`*_name`) já gravados — teste literal: cria movimentação, renomeia, relê o `Movement`, compara com o snapshot original.
- `CheckConstraint` de `Location` rejeita `type=CLIENTE` sem `client` e `type=ESTOQUE` com `client` — via `IntegrityError` direto no banco, não só via formulário.
- `CheckConstraint` de `Movement` rejeita `movement_type=OUTRO` com `reason=""` no nível de banco.
- `INSTALACAO` com destino que não é `Location(type=CLIENTE)` é rejeitada pelo service.
- Transição inválida (ex.: instalar equipamento já `EM_OPERACAO`) rejeitada, sem nenhuma escrita — nem `Movement`, nem `StatusHistory`, nem mudança de `current_location`.
- Retorno de manutenção direto a cliente exige duas chamadas — uma chamada tentando "pular" direto não existe como caminho de API a ser testado negativamente (não há parâmetro que permita isso).
- Concorrência real (seção 9) — duas threads, mesmo equipamento, `TransactionTestCase`, PostgreSQL.
- Edição de `Address` isoladamente (sem editar `Client`/`Location`) aparece no histórico do próprio `Address`.
- `Client.document`: edição pós-criação com normalização/checksum/unicidade idênticos à criação, e alteração registrada em `Client.history`.
- `on_delete=PROTECT`: tentar excluir um `Address` referenciado por `Client`/`Location` levanta `ProtectedError`; tentar excluir uma `Location` referenciada por `Movement` também.

---

## 12. Conflitos reais encontrados com código/schema existente

Nenhum conflito bloqueante. Pontos de atenção:

- `Equipment.current_client`/`current_location` já existem como `ForeignKey` simples (`editable=True` implícito, embora nunca exposto em nenhum form hoje — confirmado em `EquipmentUpdateForm`). Vou formalizar `current_client` como `editable=False` na migration desta etapa — mudança segura, não há form atual que dependa de `editable=True` nesses campos.
- Este é o primeiro uso de `CheckConstraint` no projeto (até aqui só havia `UniqueConstraint`, em `Equipment`). Nenhum conflito técnico, só registro de que é um padrão novo sendo introduzido.
- `django-simple-history` já é dependência instalada e já configurado globalmente (`SIMPLE_HISTORY_HISTORY_CHANGE_REASON_USE_TEXT_FIELD`) — adicionar a `Client`/`Location`/`Address` não exige mudança de settings.
- Nenhuma migration da v1.0 chegou a ser gerada (a rodada anterior foi só documento) — não há nada para desfazer; o plano de migrations da v1.0 (seção 13) já nasce substituído por este delta, sem custo de retrabalho.

---

Nenhum código foi escrito, nenhuma migration foi gerada. Aguardando sua aprovação para começar a implementação.
