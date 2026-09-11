# LocusHub — CRM Etapa 1: Fundação Comercial + Segurança/Permissões por Padrão

Relatório final de entrega — 10/09/2026. Commit local: `2c7748b` (branch `master`, não enviado ao remoto — sem `git push`, sem deploy).

---

## 1. Auditoria inicial

Antes de codar, o repositório real foi auditado (não uma auditoria anterior reaproveitada): `apps/accounts/models.py` (User, RoleProfile, `user.cargo`), `apps/accounts/permissions.py` (RoleRequiredMixin, CAN_*), `apps/accounts/permission_catalog.py` (PermissionSpec, PERMISSION_CATALOG, MODULE_LABELS), `apps/accounts/services.py` (`_validate_codenames`, criação/edição de cargo), `apps/accounts/migrations/0003_seed_cargos.py` e `0004_backfill_user_cargos.py`, `apps/core/models.py` (TimeStampedModel, SoftDeleteModel, Address), `apps/clients/models.py`/`views.py`/`forms.py`/`urls.py` (padrão dataclass+service), `apps/operations/models.py`/`services.py` (Location, Movement, `select_for_update()`, CheckConstraint, `_TransitionRule`), `apps/equipment/models.py` (StatusHistory/ConditionHistory, `history = HistoricalRecords()`), `apps/catalog/views.py`/`forms.py` + templates (`CategoryListView`/`CreateView`/`UpdateView`, padrão ModelForm simples), `config/settings/base.py`, `config/urls.py`, `templates/base.html` (sidebar/drawer), `apps/operations/tests/test_movement_concurrency.py` (padrão de teste de concorrência real).

**Único conflito arquitetural real encontrado**: `PermissionSpec.legacy_constant`/`legacy_admin_only` eram campos obrigatórios (sem default), e `codenames_for_role()` (migration `0003_seed_cargos.py`) fazia `getattr(legacy_permissions, spec.legacy_constant)` para TODA entrada do catálogo — incompatível com permissões novas do CRM, que não têm CAN_* equivalente por design. Não era um conflito estrutural sério (arquitetura core intacta), então a implementação seguiu na mesma rodada, com o conserto descrito no item 2 abaixo.

---

## 2. Arquitetura implementada

- **Autorização 100% nova**: toda view do CRM usa `LoginRequiredMixin` + `PermissionRequiredMixin` (nativos do Django) — nunca `RoleRequiredMixin`/`CAN_*`/`role` legado. `AccessMixin.handle_no_permission()` já reproduz exatamente o comportamento do mixin legado (403 para autenticado-sem-permissão, redirect para login se anônimo), e `ModelBackend.has_perm()` dá bypass automático a `is_superuser=True` — Administrador/superusuário continuam com acesso irrestrito sem nenhuma Permission concedida.
- **Conserto do catálogo**: `PermissionSpec.legacy_constant: str | None = None` e `legacy_admin_only: bool = False` ganharam default; `codenames_for_role()` (`0003_seed_cargos.py`) pula (`continue`) qualquer entrada com `legacy_constant is None` — nenhuma das 7 permissões do CRM é espelhada para os 4 Cargos legados (Administrador/Administrativo/Operacional/Consulta). Seguro editar a migration já aplicada: Django rastreia migrations por nome, não por conteúdo — só uma migração de banco do ZERO (como a suíte de testes) reexecuta o corpo atualizado.
- **`Client` reutilizado como está**: `Opportunity.client` é uma FK comum para `apps.clients.models.Client` — nenhuma cópia (`CRMClient`/etc.) foi criada, nada no CRM escreve em `Client`/`Address`.
- **Reuso de padrões existentes**: `TimeStampedModel`/`SoftDeleteModel` (config), `HistoricalRecords()` (snapshot genérico) + histórico estruturado à parte (`OpportunityStageChange`, mesmo espírito de `StatusHistory`/`ConditionHistory`), `select_for_update()` + `transaction.atomic()` (mesmo padrão de `create_movement()`), `CheckConstraint` como defesa em profundidade (mesmo padrão de `Location`/`Movement`).
- **Nenhuma estrutura legada tocada**: `Role`, `CAN_*`, `RoleRequiredMixin` permanecem exatamente como estavam — zero linhas alteradas nesses arquivos.

---

## 3. Models criados (`apps/crm/models.py`)

| Model | Base | Observações |
|---|---|---|
| `CommercialSource` | TimeStampedModel, SoftDeleteModel | `name` (único), `order`. Nunca hard-delete. |
| `OpportunityStage` | TimeStampedModel, SoftDeleteModel | `name`, `order`, `is_won`, `is_lost`. CheckConstraint: nunca as duas `True` na mesma etapa. |
| `LossReason` | TimeStampedModel, SoftDeleteModel | `name`, `order`. |
| `BusinessType` | TextChoices | LOCACAO / VENDA / SERVICO — só um campo informativo/filtro nesta etapa. |
| `Opportunity` | TimeStampedModel (**não** SoftDeleteModel) | Entidade principal — `client`, `title`, `owner`, `source`, `business_type`, `stage`, `expected_close_date`, `estimated_value` (Decimal 12,2), `notes`, `loss_reason`, `loss_notes`, `won_at`, `lost_at`, `closed_value` (Decimal 12,2), `created_by`, `history = HistoricalRecords()`. 3 CheckConstraints (ganho×perda simultâneos; `estimated_value`/`closed_value` nunca negativos). |
| `OpportunityStageChange` | Model simples | Histórico estruturado append-only: `opportunity`, `from_stage` (nulo só na 1ª linha), `to_stage`, `changed_by`, `changed_at`, `reason`. |
| `ActivityType` | TextChoices | LIGACAO/WHATSAPP/EMAIL/REUNIAO/VISITA/OBSERVACAO/FOLLOW_UP/OUTRO. |
| `CommercialActivity` | Model simples | `opportunity`, `activity_type`, `description`, `occurred_at`, `scheduled_for` (alimenta a futura Agenda Central), `completed_at`, `created_by`, `created_at`, `updated_at`. |

Não existe `accepted_proposal` nem qualquer campo antecipando `Proposal` — essa FK só nasce quando a entidade existir de verdade, numa etapa futura.

---

## 4. Migrations criadas

- `apps/crm/migrations/0001_initial.py` — cria as 7 tabelas (incluindo `HistoricalOpportunity`), os 3 campos FK adicionados em 2 passos (auto-gerado pelo Django por causa das referências circulares entre `Opportunity`/`OpportunityStage`), e as 4 constraints. **Não destrutiva** (só CREATE), reversível (`migrations.CreateModel`/`AddField`/`AddConstraint` têm reverso automático).
- `apps/accounts/migrations/0003_seed_cargos.py` — **editada** (não uma nova migration): adicionado um `continue` em `codenames_for_role()` para pular entradas sem `legacy_constant`. Sem efeito em bancos já migrados (Django não reexecuta `RunPython` de uma migration já aplicada); só muda o comportamento de uma migração do zero (banco de teste, ou um ambiente novo).

`python manage.py makemigrations --check --dry-run` → **"No changes detected"** (verificado após todas as alterações de model/catálogo).

---

## 5. Permissões criadas

7 nas 3 ações mínimas exigidas + config, todas com codename plural/distinto do automático do Django (convenção já usada em `view_clients`, não `view_client`):

| Codename | Model (`Meta.permissions`) | Cobre |
|---|---|---|
| `crm.view_opportunities` | Opportunity | Ver oportunidades (lista/detalhe/PK direto) |
| `crm.add_opportunities` | Opportunity | Criar oportunidade |
| `crm.change_opportunities` | Opportunity | Editar campos cadastrais |
| `crm.change_opportunity_stage` | Opportunity | Mudar etapa (inclui ganhar/perder) |
| `crm.view_commercial_activities` | CommercialActivity | Ver atividades comerciais |
| `crm.add_commercial_activities` | CommercialActivity | Registrar atividade |
| `crm.manage_commercial_settings` | CommercialSource | Gerenciar origens/etapas/motivos de perda (1 permissão cobre as 3 entidades — mesmo raciocínio de `register_operations`, que cobre mais de uma entidade) |

Nenhuma foi seedada em nenhum Cargo existente — um Administrador precisa concedê-las manualmente pela tela de gestão de cargos já existente, ou usar o bypass de superusuário.

---

## 6. Matriz Permissão → Ação → Endpoint/View

| Ação | Método | URL | Permissão exigida | View |
|---|---|---|---|---|
| Listar oportunidades | GET | `/crm/oportunidades/` | `view_opportunities` | `OpportunityListView` |
| Ver detalhe / PK direto | GET | `/crm/oportunidades/<pk>/` | `view_opportunities` | `OpportunityDetailView` |
| Ver atividades (dentro do detalhe) | — | (mesma URL) | `view_commercial_activities` (checada em separado, no backend) | `OpportunityDetailView` |
| Criar oportunidade | GET/POST | `/crm/oportunidades/nova/` | `add_opportunities` | `OpportunityCreateView` |
| Editar oportunidade | GET/POST | `/crm/oportunidades/<pk>/editar/` | `change_opportunities` | `OpportunityUpdateView` |
| Mudar etapa / ganhar / perder | POST only | `/crm/oportunidades/<pk>/etapa/` | `view_opportunities` **e** `change_opportunity_stage` | `OpportunityStageChangeView` |
| Registrar atividade | POST only | `/crm/oportunidades/<pk>/atividades/nova/` | `view_opportunities` **e** `add_commercial_activities` | `CommercialActivityCreateView` |
| Gerenciar origens | GET/POST | `/crm/configuracoes/origens/...` | `manage_commercial_settings` | `CommercialSource{List,Create,Update}View` |
| Gerenciar etapas | GET/POST | `/crm/configuracoes/etapas/...` | `manage_commercial_settings` | `OpportunityStage{List,Create,Update}View` |
| Gerenciar motivos de perda | GET/POST | `/crm/configuracoes/motivos-perda/...` | `manage_commercial_settings` | `LossReason{List,Create,Update}View` |

---

## 7. URLs adicionadas

`config/urls.py`: `path("crm/", include("apps.crm.urls"))`. Namespace `crm`, todas as rotas em `apps/crm/urls.py` (14 rotas — ver seção 6).

---

## 8. Templates adicionados/alterados

Adicionados (`templates/crm/`): `opportunity_list.html`, `opportunity_detail.html`, `opportunity_form.html`, `commercial_source_list.html`, `commercial_source_form.html`, `opportunity_stage_list.html`, `opportunity_stage_form.html`, `loss_reason_list.html`, `loss_reason_form.html`.

Alterado: `templates/base.html` — novo grupo de menu **"CRM"** (sidebar desktop + drawer mobile), com dois itens: "Oportunidades" (gated por `perms.crm.view_opportunities`) e "Config. comerciais" (gated por `perms.crm.manage_commercial_settings`). O grupo inteiro some (nem o título aparece) para quem não tem nenhuma das duas.

**Decisão de nomenclatura do menu, conforme pedido**: rótulo **"CRM"** (não "Comercial") — mesmo padrão curto de "Equipamentos"/"Clientes" já usado no resto do menu, e é o nome que o próprio pedido desta etapa usa ("LocusHub — CRM Etapa 1"). Prefixo de URL também `crm/` pelo mesmo motivo (os demais prefixos são palavras em português — `crm` foge um pouco dessa convenção, mas é a sigla que o próprio produto usa).

---

## 9. Services adicionados (`apps/crm/services.py`)

- `eligible_owner_queryset()` — usuários ativos com `is_superuser=True` OU permissão `crm.add_opportunities` (via Cargo ou direta).
- `create_opportunity(NewOpportunityData)` — valida título/valor, bloqueia criação direta em etapa de ganho/perda ou desativada, cria a 1ª linha de `OpportunityStageChange`.
- `update_opportunity(*, opportunity, data, changed_by)` — nunca toca `client`/`stage`/`won_at`/`lost_at`/`loss_reason`/`loss_notes`/`closed_value`.
- `change_opportunity_stage(*, opportunity_id, new_stage, changed_by, ...)` — **único** caminho que escreve etapa/ganho/perda. `select_for_update()` + `transaction.atomic()`; exige motivo de perda; limpa estado incompatível (ganhar limpa perda e vice-versa; reabrir para etapa intermediária limpa os dois); rejeita mover para a mesma etapa ou para etapa desativada.
- `create_activity(NewActivityData)` — valida `activity_type`, cria o registro.

---

## 10. Decisões de transação/locking

- Toda escrita passa por `@transaction.atomic` (criação, edição, mudança de etapa).
- `change_opportunity_stage()` usa `Opportunity.objects.select_for_update().get(pk=...)` — mesmo padrão de `apps.operations.services.create_movement()` em `Equipment`. Duas requisições concorrentes na MESMA oportunidade serializam: a segunda só enxerga o estado já gravado pela primeira.
- `OpportunityStageChange` é sempre criado na MESMA transação que atualiza `Opportunity` — nunca uma sem a outra (testado explicitamente: `test_a_failed_transition_leaves_no_partial_state`).
- Teste de concorrência real (`TransactionTestCase` + threads) prova que o estado final nunca é ganho+perdido simultâneo e que o histórico nunca fica com um "buraco" (`to_stage` de uma linha sempre bate com o `from_stage` da próxima).

---

## 11. Decisões de `on_delete`

| Campo | on_delete | Por quê |
|---|---|---|
| `Opportunity.client/source/stage/loss_reason/owner/created_by` | `PROTECT` | Nenhuma FK "viva" pode arrastar dado comercial numa exclusão acidental do lado configuração/usuário. |
| `OpportunityStageChange.from_stage/to_stage/changed_by` | `PROTECT` | Idem — histórico nunca perde a referência à etapa/usuário. |
| `OpportunityStageChange.opportunity` | `CASCADE` | Pertence inteiramente à Oportunidade dona (mesmo padrão de `StatusHistory.equipment`). |
| `CommercialActivity.opportunity` | `CASCADE` | Idem. |
| `CommercialActivity.created_by` | `PROTECT` | — |

Nenhum fluxo de exclusão de `Opportunity` foi implementado nesta etapa — a CASCADE documentada acima nunca é exercitada no uso normal do sistema; é só a mesma rede de segurança que o resto do projeto já usa para esse relacionamento pai/detalhe.

---

## 12. Proteções contra IDOR

- `get_object_or_404(Opportunity, pk=pk)` sem filtro adicional por dono é **deliberado**: a permissão é a fronteira, não a posse — um usuário com `view_opportunities` pode ver qualquer oportunidade, mesmo sem ser `owner`. Quem **não** tem a permissão nunca alcança a view (bloqueado por `PermissionRequiredMixin` antes de qualquer query rodar), então PK sequencial não vaza nada.
- Testado explicitamente (`test_security.py::IDORTest`): usuário sem permissão bloqueado em detalhe/edição/mudança de etapa/atividade nas duas oportunidades (PK 10 e 11 do teste); PK inexistente retorna 404 (não 500); usuário COM permissão pode ver qualquer PK por design (documentado no teste para não ser confundido com falha).

---

## 13. Proteções contra vazamento

- Nenhuma exportação/CSV/Excel/PDF/API foi implementada para o CRM nesta etapa (requisito explícito).
- Listagem/busca/filtros só operam dentro da queryset já protegida por `view_opportunities`; busca (`q`) usa `icontains` sobre título/cliente, sem vazar registros fora do filtro.
- Atividades comerciais exigem `view_commercial_activities` **separada** — mesmo um usuário com `view_opportunities` (chega à página de detalhe) não recebe o conteúdo de atividades no contexto se não tiver essa permissão extra (checado no backend, não só escondido no template).
- Filtros por PK (`stage`/`owner`/`source`/`client`) ignoram silenciosamente valor não numérico (corrigido durante a 2ª passada de segurança — ver seção 21) em vez de derrubar a página com 500.

---

## 14. Auditoria/histórico

- `django-simple-history` (`HistoricalRecords()`) em `Opportunity` — mesmo mecanismo já usado em `Client`/`Location`/`EquipmentModel`/`Address`, nenhum sistema paralelo.
- `OpportunityStageChange` — histórico estruturado à parte, sempre criado por `change_opportunity_stage()`, nunca editável por nenhuma view/usuário comum (não existe nenhum endpoint de edição/exclusão dele).

---

## 15. Testes criados — 64 novos, 4 arquivos

- `apps/crm/tests/test_services.py` (30 testes) — regras de negócio: criação/edição, Decimal não-float, transições ganho/perda/reabertura, elegibilidade de owner, atividades.
- `apps/crm/tests/test_permission_matrix.py` (13 testes) — matriz obrigatória 4 perfis (A sem permissão, B só `view_opportunities`, C permissão específica da ação, D superusuário) × 13 ações, comportamento HTTP real.
- `apps/crm/tests/test_security.py` (20 testes) — IDOR, GET nunca muda estado, CSRF ativo, integridade de banco (CheckConstraint), histórico correto, `Client` nunca alterado, desativação preserva histórico, nenhuma cascata destrutiva, nenhum vazamento por listagem/busca.
- `apps/crm/tests/test_stage_change_concurrency.py` (1 teste) — concorrência real (`TransactionTestCase` + threads), prova estado final coerente e histórico sem buracos.

Mais 2 arquivos **editados** (não novos) por necessidade direta da mudança no catálogo: `apps/accounts/tests/test_roles_foundation.py` — os testes que assumiam "catálogo tem exatamente 18 entradas" foram atualizados para 25 (18 legadas + 7 CRM), com uma classe nova (`CrmCatalogEntriesTest`) verificando as 7 entradas do CRM especificamente; nenhum teste de accounts foi enfraquecido, só ajustado ao crescimento real e esperado do catálogo.

---

## 16. Resultado específico dos testes do CRM

```
apps.crm.tests.*        64 testes — OK (0 falhas, 0 erros)
apps.accounts + apps.crm 151 testes — OK
```

Concorrência: `test_two_simultaneous_stage_changes_never_produce_an_incoherent_final_state` — OK (2 threads reais, Postgres, `select_for_update()`).

---

## 17. Resultado da suíte completa

```
Ran 917 tests in ~258s
OK (0 falhas, 0 erros)
```

853 testes pré-existentes (Equipamentos, QR Codes, Etiquetas, exportação de QR puro, Clientes, Auvo, Manutenções, Higienizações, Operações, Cargos, Usuários, permissões legadas) + 64 novos do CRM — **nenhuma regressão**.

---

## 18. `manage.py check`

```
System check identified no issues (0 silenced).
```

---

## 19. `makemigrations --check --dry-run`

```
No changes detected
```

(Verificado tanto logo após criar `apps/crm/migrations/0001_initial.py` quanto no final, depois de todas as edições de catálogo/testes.)

---

## 20. Decisões de produto pendentes (relatadas, não assumidas)

1. **"Exatamente uma etapa de ganho e uma de perda?"** — **não imposto**. O sistema garante só o mínimo seguro (nenhuma etapa é as duas coisas ao mesmo tempo, via CheckConstraint + `clean()`). Zero, uma ou várias etapas `is_won=True`/`is_lost=True` são permitidas — útil, por exemplo, se a Locus quiser "Ganho — Locação" e "Ganho — Venda" separados no futuro. **Pendente de decisão do usuário**, sem impacto de segurança (a integridade real está garantida em outro nível: uma Oportunidade nunca fica ganha+perdida ao mesmo tempo, isso sim é imposto).
2. **`manage_commercial_settings` deveria ser restrito só a Administrador (superusuário), e não uma Permission concedível a qualquer Cargo?** — implementado como Permission concedível normal (mesmo padrão de todo o catálogo), não hardcoded a `is_superuser`. Esta é uma ação de alto impacto (define o vocabulário de todo o funil comercial), então **fica como pergunta em aberto**: se a resposta for "sim, só Administrador", a mudança é pequena (trocar `PermissionRequiredMixin` pelas 3 config views para checar `is_superuser` direto, ou simplesmente nunca conceder essa Permission a nenhum Cargo não-Administrador pela tela já existente — o que já é possível fazer HOJE sem mudança de código).
3. **Seed inicial de Origens/Etapas/Motivos de perda** — **nenhum dado foi criado**. As 3 tabelas nascem vazias; um Administrador precisa cadastrar ao menos uma Etapa antes do CRM ficar utilizável (a tela de criação de Oportunidade não terá nenhuma opção de etapa inicial até isso acontecer — comportamento esperado, mensagem "Nenhuma etapa cadastrada" aparece na listagem de config). Decisão explícita: preferir a infraestrutura de configuração a inventar nomes de etapas/origens que poderiam não bater com o vocabulário real da Locus.
4. **Nenhum Cargo existente foi seedado com as 7 permissões novas do CRM** — inclusive o Cargo "Administrador" (que já tem bypass total via `is_superuser`, então isso não bloqueia ninguém que já seja superusuário). Um Administrador humano precisa conceder as permissões pela tela de gestão de cargos já existente para qualquer outro Cargo usar o CRM.

---

## 21. Riscos conhecidos

- **CRM inutilizável até configuração mínima**: sem nenhuma `OpportunityStage` ativa não-ganho/não-perda cadastrada, ninguém consegue criar uma Oportunidade (o formulário de criação simplesmente não tem opção de etapa inicial). Não é um bug — é a consequência direta da decisão #3 acima.
- **Segunda passada de segurança encontrou e corrigiu 1 item**: `OpportunityListView.get_queryset()` filtrava `stage`/`owner`/`source`/`client` por PK sem validar que o valor da querystring é numérico — um `?owner=abc` adulterado à mão derrubaria a listagem com um 500 (não uma falha de autorização, mas uma falha de robustez/DoS trivial). Corrigido espelhando o mesmo tratamento já usado em `apps.equipment.filters.filter_equipment_queryset` (ignora silenciosamente valor não numérico). Suíte completa re-executada depois da correção — 917/917 OK.
- **Nenhum registro em `apps/crm/admin.py`** — decisão deliberada: registrar os models no Django admin abriria um caminho de escrita paralelo checado pelas permissões AUTOMÁTICAS do Django (`crm.add_opportunity`, singular, geradas por padrão para todo model) em vez das 7 permissões customizadas (`crm.add_opportunities`, plural) que este relatório documenta — um Administrador poderia se confundir achando que concedeu acesso ao CRM quando na verdade concedeu só acesso ao Django admin. Se o Django admin for desejado como ferramenta técnica/contingência para o CRM (mesmo papel que já tem para outros apps), é um adendo pequeno e separado.
- **`eligible_owner_queryset()` não é re-validada dentro do service** — a elegibilidade de `owner` é garantida pelo `ModelChoiceField` do formulário (Django rejeita qualquer PK fora da queryset permitida antes mesmo de chegar ao service), não por uma segunda checagem dentro de `create_opportunity()`/`update_opportunity()`. Mesmo padrão já usado no resto do projeto (o service confia num valor já resolvido e validado pelo form/view chamador) — não é uma lacuna nova, mas fica registrado para quem for auditar depois.

---

## 22. Checklist manual de homologação (4 perfis)

Sugestão de execução: criar 4 usuários de teste (ou reutilizar existentes), um por perfil, e percorrer a lista abaixo logado como cada um.

### Perfil SEM CRM (nenhuma permissão `crm.*`)
- [ ] Menu lateral/drawer **não mostra** nenhum item "CRM".
- [ ] Acessar `/crm/oportunidades/` direto na URL → página de erro 403 (não uma tela em branco, não redireciona silenciosamente).
- [ ] Acessar `/crm/oportunidades/1/` (ou qualquer PK existente) direto na URL → 403.
- [ ] Acessar `/crm/configuracoes/origens/` direto na URL → 403.

### Perfil SOMENTE LEITURA (`view_opportunities`)
- [ ] Vê "Oportunidades" no menu; **não** vê "Config. comerciais".
- [ ] Lista, filtra e busca oportunidades normalmente.
- [ ] Abre o detalhe de uma oportunidade — vê os dados principais, **não vê** a seção de atividades comerciais (sem `view_commercial_activities`) nem o formulário de mudança de etapa.
- [ ] Tenta acessar `/crm/oportunidades/nova/` direto → 403.
- [ ] Tenta enviar POST para `/crm/oportunidades/<pk>/etapa/` (via ferramenta externa ou adulterando um formulário salvo) → 403, nada muda.

### Perfil COMERCIAL (permissões típicas: `view_opportunities` + `add_opportunities` + `change_opportunities` + `change_opportunity_stage` + `view_commercial_activities` + `add_commercial_activities`, **sem** `manage_commercial_settings`)
- [ ] Cria uma oportunidade nova (cliente já existente, sem dados opcionais) — salva sem erro.
- [ ] Edita a oportunidade — título/valor/observações mudam; **cliente permanece o mesmo** (campo não aparece no formulário de edição).
- [ ] Muda a etapa para uma intermediária — some da lista de "ganho/perdido", histórico de etapas mostra a transição com o nome do usuário e data/hora.
- [ ] Marca como GANHA (etapa de ganho) sem preencher valor de fechamento — funciona (campo opcional).
- [ ] Marca outra oportunidade como PERDIDA sem escolher motivo de perda — formulário rejeita com mensagem clara.
- [ ] Marca como PERDIDA escolhendo o motivo — funciona, aparece no detalhe.
- [ ] Registra uma atividade comercial (ligação/e-mail/etc.) — aparece na lista de atividades da oportunidade.
- [ ] Tenta acessar `/crm/configuracoes/origens/` direto → 403 (não tem `manage_commercial_settings`).

### Perfil ADMINISTRADOR (superusuário)
- [ ] Vê os dois itens do menu "CRM".
- [ ] Acessa "Config. comerciais" — cadastra uma nova Origem, uma nova Etapa (testar marcar `is_won`+`is_lost` juntos — deve ser rejeitado com mensagem clara) e um novo Motivo de perda.
- [ ] Desativa (não exclui) uma Origem já usada por uma oportunidade existente — a oportunidade continua mostrando a origem normalmente; a origem some das opções de criação de NOVA oportunidade.
- [ ] Executa todo o fluxo do perfil COMERCIAL acima sem restrição nenhuma.

### Checks genéricos (qualquer perfil com acesso)
- [ ] Cliente já cadastrado aparece corretamente no seletor de criação de oportunidade.
- [ ] Oportunidade sem nenhum dado opcional (sem previsão de fechamento, sem valor estimado, sem observações) salva e exibe "—" nos campos vazios, sem erro.
- [ ] Valores monetários aparecem formatados como `R$ 1234.56` (nunca `1234.5600000001` ou notação científica — confirma que é Decimal, não float).
- [ ] Filtros (etapa/origem/tipo de negócio) e busca por título/cliente funcionam e persistem na paginação.
- [ ] Testado em tela de celular (largura estreita) — listagem vira cartões empilhados, formulários não estouram a largura da tela.
- [ ] Tentar trocar manualmente o número da URL de uma oportunidade (`/crm/oportunidades/10/` → `/crm/oportunidades/11/`) — comportamento correto é: 403 se não tiver permissão, 200 com os dados CORRETOS da oportunidade 11 se tiver permissão (nunca uma mistura/vazamento parcial).
- [ ] Atualizar a página (F5) depois de um POST (criar/editar/mudar etapa) — nunca reenvia o formulário nem duplica o registro (Django redireciona após POST — padrão PRG já usado no resto do sistema).
- [ ] Botão "Voltar" do navegador depois de criar uma oportunidade — não duplica nada ao navegar de volta e para frente.
- [ ] Mensagens de sucesso/erro aparecem no topo da página em todas as ações (criar, editar, mudar etapa, registrar atividade, gerenciar configuração).

---

**Commit local**: `2c7748b` — "LocusHub — CRM Etapa 1: fundação comercial [...]" (branch `master`). Nada foi enviado ao remoto nem implantado em produção.
