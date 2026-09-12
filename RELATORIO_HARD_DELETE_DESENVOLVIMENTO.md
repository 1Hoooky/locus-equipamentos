# Relatório — Exclusão definitiva (hard delete) restrita à autoridade máxima

**Rodada:** "AMBIENTE EM DESENVOLVIMENTO / HARD DELETE DURANTE DESENVOLVIMENTO / NÃO FAZER CASCADE CEGO"
**Data:** 11/09/2026
**Branch:** `master` (commit local — sem push, sem deploy, por instrução explícita)

## 1. O pedido, em uma frase

Permitir que a "autoridade máxima" apague de verdade (não `is_active=False`) registros de teste de Cliente, Equipamento e Oportunidade — incluindo os dependentes que só existem em função deles — **sem** nunca cascatear às cegas para dentro de um registro compartilhado.

## 2. Autoridade máxima = `is_superuser` puro

O sistema já tinha exatamente este conceito, usado hoje só para a gestão de Cargos/Permissões (`apps.accounts.permissions.SuperuserRequiredMixin`, categoria "Nível C — ações de segurança do próprio sistema" do `permission_catalog.py`): `is_superuser` **puro**, nunca `Role.ADMIN` nem nenhuma `Permission` concedível — de propósito, para que nenhum Cargo comum possa se auto-conceder a capacidade de apagar dado de verdade.

Hard delete reusa esse mesmo mixin, sem criar nada novo, e adiciona uma segunda camada (defesa em profundidade, sem precedente direto no projeto até agora, mas justificada pela severidade — irreversível): cada `hard_delete_*()` **também** confere `actor.is_superuser` dentro do próprio `services.py`, levantando `HardDeleteAuthorizationError` se não for. A view continua sendo a primeira barreira (403 antes de qualquer query rodar); o service nunca confia só nela.

Nenhuma `Permission` nova foi adicionada ao catálogo — nenhum Cargo pode ganhar esta capacidade pela tela de gestão de cargos.

## 3. Mapa de relações (CASCADE / PROTECT / SET_NULL) — auditoria completa antes de codar

| Entidade | Relação | `on_delete` hoje | Classificação | Tratamento |
|---|---|---|---|---|
| **Client** | `fiscal_address` → `Address` (1:1) | `PROTECT` | **Dependente exclusivo** — nunca compartilhado com outro Client/Location | Removido explicitamente, DEPOIS do Client (o `PROTECT` só protege a direção "excluir Address com Client vivo") |
| | `Equipment.current_client` → Client | `SET_NULL` | **Compartilhado** | Django zera sozinho — Equipment nunca tocado |
| | `Location.client` → Client | `PROTECT` | **Compartilhado** (histórico operacional próprio, Movements apontam pra ela) | Bloqueia a exclusão (não é excesso — o impacto de apagar Locations não seria "conhecido e controlado") |
| | `Opportunity.client` → Client | `PROTECT` | **Compartilhado** | Bloqueia a exclusão |
| **Equipment** | `StatusHistory.equipment` / `ConditionHistory.equipment` | `CASCADE` | **Dependente exclusivo** | Automático (schema já cuida) |
| | `Cleaning.equipment` | `PROTECT` (conservador demais p/ hard delete) | **Dependente exclusivo** (evento atômico de 1 equipamento) | Removido explicitamente |
| | `Maintenance.equipment` | `PROTECT` | **Dependente exclusivo** | Removido explicitamente |
| | `Movement.equipment` | `PROTECT` | **Dependente exclusivo** (mesmo espírito de StatusHistory/ConditionHistory) | Removido explicitamente, **por último** (ver ordem abaixo) |
| | `EquipmentModel`/`Category`/`EquipmentBatch` | `PROTECT`/`SET_NULL` | **Compartilhado** | Nunca tocado |
| | `Location`/`Client` (current_*) | `SET_NULL` | **Compartilhado** | Django zera sozinho |
| | `superseded_by` (self) | `SET_NULL` | **Compartilhado** (o outro equipamento) | Django zera sozinho — outro equipamento nunca excluído |
| **Opportunity** | `OpportunityStageChange.opportunity` / `CommercialActivity.opportunity` | `CASCADE` | **Dependente exclusivo** | Automático (schema já cuida — exatamente o exemplo do próprio pedido) |
| | `client`/`stage`/`source`/`loss_reason`/`owner`/`created_by` | `PROTECT` | **Compartilhado** | Opportunity é quem tem a FK — excluí-la nunca dispara o `on_delete` do outro lado |

**Ordem de remoção no Equipment (a parte arquiteturalmente sensível):** `Cleaning` → `Maintenance` → `Movement` → `Equipment`. Motivo: `Maintenance.departure_movement`/`return_movement` (OneToOne, PROTECT) e `Cleaning.movement` (PROTECT) apontam **para** `Movement` — excluir Movement primeiro levantaria `ProtectedError`. Todas as três consultas filtram por `equipment=equipment` (a FK direta), nunca "todo Movement referenciado por alguma Maintenance daqui" — um eventual cross-link anômalo para outro equipamento nunca é tocado por engano.

## 4. O que NUNCA acontece (garantias verificadas por teste)

- Excluir uma Oportunidade **não** exclui o Cliente (`test_client_is_never_deleted_when_opportunity_is_hard_deleted`).
- Excluir um Cliente **não** exclui um Equipamento que teve relação com ele — só zera `current_client` (`test_equipment_with_relation_to_client_is_never_deleted_only_unlinked`).
- Excluir um Cliente com Location/Oportunidade ainda vinculada é **bloqueado**, nunca cascateado (`test_active_location_blocks_client_hard_delete`, `test_opportunity_still_linked_blocks_client_hard_delete`).
- Configuração compartilhada (EquipmentModel, Category, EquipmentBatch, CommercialSource, OpportunityStage) nunca é tocada.
- Um usuário sem `is_superuser` é bloqueado tanto na view (403) quanto no service (`HardDeleteAuthorizationError`), mesmo tendo `Role.ADMIN` ou a Permission de escrita da entidade.

## 5. Decisões explícitas (para não silenciar nenhuma escolha)

1. **`django-simple-history`**: as linhas `Historical<Model>` não têm FK viva (não bloqueiam nem cascateiam sozinhas). Decisão: purgadas junto, por entidade (`Client.history.filter(id=...).delete()` etc.) — para uma "limpeza definitiva" de dado de teste ser definitiva de verdade, sem snapshot fantasma sobrando.
2. **Bloqueio em vez de cascata para Location/Opportunity em relação a Client**: mantido `PROTECT` como está. Não é o "bloqueio excessivo" que o pedido pediu para evitar — é justamente o oposto do cascade cego: o Administrador decide o destino desses registros primeiro.
3. **Movement/Maintenance/Cleaning tratados como dependentes exclusivos do Equipment**, apesar de hoje serem `PROTECT` no schema (não `CASCADE`): o `on_delete` do model não foi alterado (continua protegendo contra um `.delete()` solto e acidental fora deste fluxo) — só o `hard_delete_equipment()` sabe remover os três, na ordem certa, dentro de uma transação.

## 6. Onde a capacidade aparece

Um link/botão **"Excluir definitivamente"**, visível só para `user.is_superuser`, foi adicionado às 3 fichas:
- Cliente (`/clientes/<pk>/`) → `/clientes/<pk>/excluir-definitivamente/`
- Equipamento (`/equipamentos/<patrimonio>/`) → `/equipamentos/<patrimonio>/excluir-definitivamente/`
- Oportunidade (`/crm/oportunidades/<pk>/`) → `/crm/oportunidades/<pk>/excluir-definitivamente/`

Cada tela mostra uma **prévia de impacto** (o que será removido junto) antes de um checkbox de confirmação único — nunca um `window.confirm()`, nunca "digite o nome para confirmar" (a prévia já é informação suficiente).

**Achado colateral corrigido:** a ficha de Equipamento (`detail_private.html`) tinha toda a seção "Ações" (incluindo "Administração") condicionada a `user.is_operacional_ou_superior`, que não inclui `is_superuser` puro — um superusuário sem `role` operacional nunca via a seção inteira. Corrigido (`or user.is_superuser`) para o botão ficar realmente acessível à autoridade máxima; coberto pela suíte existente (`test_ficha_action_tiers.py`, 5/5 ainda passando).

## 7. Testes

40 testes novos, todos passando:
- `apps/core/tests/test_hard_delete.py` (3) — infraestrutura compartilhada (`describe_protected_error`, `HardDeleteImpact`).
- `apps/clients/tests/test_client_hard_delete.py` (11) — service + bloqueio + view.
- `apps/equipment/tests/test_equipment_hard_delete.py` (12) — o caso mais denso (Movement/Maintenance/Cleaning, superseded_by, batch).
- `apps/crm/tests/test_opportunity_hard_delete.py` (9) — service + view.

```
python manage.py check                          → System check identified no issues (0 silenced)
python manage.py makemigrations --check --dry-run → No changes detected
python -m pytest -q                              → 1057 passed, 1 failed
```

O único teste falho é `MojibakeRegressionTest.test_no_mojibake_in_tracked_repository_files` — falha **pré-existente e autorreferencial** (o teste varre todo o repositório procurando "marcadores de mojibake" e encontra os próprios exemplos usados no corpo do teste/documentação, já sinalizado em rodadas anteriores). Não relacionado a esta rodada; nenhum arquivo desta entrega contém os marcadores.

## 8. Padrão seguido (nada novo inventado)

- `@transaction.atomic` + `select_for_update()` na linha do registro-alvo — mesmo padrão de `change_opportunity_stage()`/`create_equipment()`.
- Serviço único por entidade em `apps/*/services.py` — nenhuma escrita de exclusão fora daí.
- View GET (prévia + confirmação) / POST (executa + redirect + `messages`) — mesmo padrão de `EquipmentSupersedeView`/`supersede.html`.
- Ícone `trash` novo (Heroicons outline) adicionado ao vendorizado `apps/core/templatetags/icons.py`, coberto automaticamente pelo teste existente que itera todos os ícones.

## 9. Nota para o futuro (não uma ação desta rodada)

O próprio pedido do usuário já registrou isto: em ambiente de produção, esta política pode ser endurecida (ex.: exigir uma segunda confirmação por texto, um período de carência, ou desativar a capacidade inteiramente). Nada nesta implementação impede isso depois — a "válvula" é só o `SuperuserRequiredMixin`/`actor.is_superuser`, fácil de substituir ou remover sem tocar no resto da arquitetura.

---

**Escopo respeitado:** nenhum push, nenhum deploy — commit local apenas, conforme instrução do usuário reiterada em toda esta sessão.
