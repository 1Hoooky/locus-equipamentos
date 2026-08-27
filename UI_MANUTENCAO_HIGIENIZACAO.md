# UI Operacional de Manutenção e Higienização — Relatório Final

**Data:** 27/08/2026
**Escopo:** camada de UI sobre `apps.maintenance`, sem alterar a camada de domínio (fechada e estável desde a auditoria de vínculos aprovada). Nenhuma regra de negócio foi redesenhada ou replicada em forms/views — todas as escritas passam exclusivamente por `open_maintenance()`, `close_maintenance()`, `cancel_maintenance()`, `create_cleaning()`, `cancel_cleaning()`.

---

## 1. Arquivos criados

**Domínio (leitura only, sem novas regras):**
- `apps/maintenance/services.py` — adicionada `get_equipment_maintenance_summary(equipment, limit=5)`: resumo compacto (manutenção em aberto + últimas N manutenções/higienizações) para a ficha do equipamento, deliberadamente distinto da timeline completa. Duas queries fixas, sem N+1.

**UI:**
- `apps/maintenance/filters.py` — `filter_maintenance_queryset()` / `filter_cleaning_queryset()` (busca por patrimônio/modelo, filtros de status/tipo).
- `apps/maintenance/forms.py` — formulários que espelham campo a campo o contrato real de cada service (nenhum campo inventado, nenhum snapshot interno exposto).
- `apps/maintenance/views.py` — 10 views (listagem, detalhe, abrir, concluir, cancelar de Manutenção; listagem, registrar, detalhe, cancelar de Higienização; endpoint htmx de opções de movimentação de envio).
- `apps/maintenance/urls.py` — rotas sob `manutencao/`.
- `templates/maintenance/` — 10 templates: `maintenance_list.html`, `maintenance_open_form.html`, `_departure_movement_options.html` (fragmento htmx), `maintenance_detail.html`, `maintenance_close_form.html`, `maintenance_cancel_confirm.html`, `cleaning_list.html`, `cleaning_form.html`, `cleaning_detail.html`, `cleaning_cancel_confirm.html`.

**Testes (5 arquivos, 107 testes novos):**
- `apps/maintenance/tests/test_maintenance_views_permissions.py`
- `apps/maintenance/tests/test_maintenance_open_close_cancel_views.py`
- `apps/maintenance/tests/test_cleaning_views.py`
- `apps/maintenance/tests/test_equipment_ficha_and_timeline.py`
- `apps/maintenance/tests/test_maintenance_lists_filters_pagination_queries.py`

## 2. Arquivos alterados

- `config/urls.py` — inclusão de `apps.maintenance.urls` em `manutencao/`.
- `apps/equipment/services.py` — `get_equipment_history_timeline()` estendida com blocos de eventos de Manutenção (aberta / concluída / cancelada) e Higienização (realizada). Nenhum evento histórico existente (Status/Condition/Movement) foi alterado; apenas acréscimo ao final, antes do `sort()` — exatamente como a função já previa desde a Fase 1.
- `apps/equipment/views.py` — `EquipmentDetailView` passa a calcular `can_view_maintenance` e `maintenance_summary` no contexto, condicionado à permissão `CAN_VIEW_MAINTENANCE`.
- `templates/equipment/detail_private.html` — ações "Abrir manutenção" / "Registrar higienização" (visíveis apenas para quem tem `CAN_REGISTER_OPERATIONS`, via `user.is_operacional_ou_superior`) e nova seção resumida "Manutenção e higienização" (não duplica a timeline completa).
- `templates/base.html` — reescrito para aplicar a identidade visual da Locus (ver seção 6) e adicionar os links "Manutenções"/"Higienizações" na navegação.
- `apps/operations/tests/test_duplicate_locations_report.py` — 2 testes pré-existentes ajustados como efeito colateral direto e esperado da mudança global de `base.html` (ver seção 6.4).

## 3. Rotas criadas

| Rota | View | Método(s) |
|---|---|---|
| `manutencao/manutencoes/` | `MaintenanceListView` | GET |
| `manutencao/manutencoes/abrir/` | `MaintenanceOpenView` | GET/POST |
| `manutencao/manutencoes/abrir/movimentos-envio/` | `DepartureMovementOptionsView` | GET (fragmento htmx) |
| `manutencao/manutencoes/<pk>/` | `MaintenanceDetailView` | GET |
| `manutencao/manutencoes/<pk>/concluir/` | `MaintenanceCloseView` | GET/POST |
| `manutencao/manutencoes/<pk>/cancelar/` | `MaintenanceCancelView` | GET/POST |
| `manutencao/higienizacoes/` | `CleaningListView` | GET |
| `manutencao/higienizacoes/registrar/` | `CleaningCreateView` | GET/POST |
| `manutencao/higienizacoes/<pk>/` | `CleaningDetailView` | GET |
| `manutencao/higienizacoes/<pk>/cancelar/` | `CleaningCancelView` | GET/POST |

## 4. Telas e fluxos implementados

**Manutenção**
- Listagem: patrimônio/modelo, tipo, status, responsável, abertura, encerramento, próxima manutenção; busca por patrimônio/modelo; filtros de status e tipo; paginação preservando filtros (`pagination_tags.url_replace`, o mesmo mecanismo já corrigido em `equipment/list.html`).
- Abrir: equipamento (busca incremental client-side, restrição real no `__init__` do form), tipo, diagnóstico, responsável, observações, movimentação de envio opcional. `next_due_at` **não** foi incluído — confirmado por leitura direta que `NewMaintenanceData` não tem esse campo; nenhum campo inventado. `status_before` não é exposto em nenhum lugar do form — é calculado inteiramente dentro do service.
- Detalhe: equipamento, patrimônio, tipo, status, diagnóstico, serviço realizado, condição antes/depois, responsável, abertura, encerramento, observações, próxima manutenção, e Movement de envio/retorno mostrados com origem, destino e data (usando os campos denormalizados do próprio Movement — sem query extra).
- Concluir: apenas para Manutenção ABERTA, exclusivamente via `close_maintenance()`. Campos: serviço executado, condição após, `return_movement` opcional. `observations` **não** foi incluído — confirmado que `CloseMaintenanceData` não tem esse campo. Erros de domínio (`ValueError`) chegam à tela como mensagem compreensível, nunca 500.
- Cancelar: apenas para Manutenção ABERTA, via `cancel_maintenance()`, POST-only, exige confirmação explícita (`confirm`) e motivo (mínimo 3 caracteres) — nunca hard delete, nunca edição direta de status.

**Higienização**
- Listagem, formulário "Registrar higienização" (exclusivamente `create_cleaning()`), detalhe. Campos: equipamento, responsável, observações, movimentação opcional. Não altera status/condition/localização/cliente; não há ciclo ABERTA/CONCLUIDA para Cleaning — cada registro já nasce como um evento concluído.
- Cancelamento apenas via `cancel_cleaning()`, com confirmação explícita, POST-only, inativação (não hard delete).

**Entrada pela ficha do equipamento**
- Links "Abrir manutenção"/"Registrar higienização" na ficha privada, com pré-seleção do equipamento via querystring (`?equipment=<pk>`) quando iniciados dali — confirmado por teste (`MaintenanceOpenPreSelectionTest`).
- Seção "Manutenção e higienização": banner de manutenção em aberto (se houver) + lista resumida dos eventos técnicos recentes com link "Ver" para o detalhe. Distinta da timeline completa.

## 5. Permissões

- Leitura (listagens, detalhes) exige `CAN_VIEW_MAINTENANCE` (ADMIN, ADMINISTRATIVO, OPERACIONAL, CONSULTA).
- Escrita (abrir/concluir/cancelar Manutenção, registrar/cancelar Higienização) exige `CAN_REGISTER_OPERATIONS` (ADMIN, ADMINISTRATIVO, OPERACIONAL) — CONSULTA vê, mas não escreve.
- Aplicado via `RoleRequiredMixin` em toda view (backend), não apenas escondendo botões no template — confirmado por `WriteViewsRoleMatrixTest`/`ReadViewsAllRolesTest`, que fazem requisições reais como cada papel e checam o `status_code` (403 quando negado).

## 6. Identidade visual

### 6.1 O que foi extraído do site institucional (locuslocacoes.com.br)
Inspeção ao vivo dos estilos computados do site: fundo escuro quase preto na navegação/hero, destaque em dourado/amarelo para ações e elementos de marca, tipografia sem serifa de alto contraste, botões com cantos discretamente arredondados. Esses elementos foram traduzidos para `tailwind.config` em `base.html` como `brand.black` (#0a0a0a), `brand.charcoal` (#171717), `brand.gold` (#eab308), `brand.gold-dark` (#b45309), `brand.gold-light` (#fef3c7).

**Adaptação deliberada, documentada no próprio `base.html`:** o dourado do site é praticamente puro (~#ffd700); no sistema interno foi ajustado para #eab308 porque esse tom mantém contraste adequado quando usado como preenchimento de botão com texto escuro sobre ele, o que o tom mais claro do site não garante em uma ferramenta usada o dia inteiro. A área de conteúdo principal (tabelas, formulários) permanece clara — não se copiou o fundo escuro do site inteiro, porque o site é vitrine comercial e o sistema é ferramenta operacional de uso intenso. A identidade preto+dourado foi aplicada ao cabeçalho, navegação, ações primárias e estados de foco; leitura de dados no dia a dia continua em fundo claro de alto contraste.

### 6.2 Componentes reutilizáveis criados em `base.html`
Bloco `<style type="text/tailwindcss">@layer components{...}` com classes centralizadas (evita repetir dezenas de classes Tailwind em cada template):
- Botões: `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-neutral`, `.btn-danger`, `.btn-sm`.
- Links: `.link`.
- Cards: `.card`, `.card-pad`.
- Cabeçalho de página: `.page-header`, `.page-title`, `.page-subtitle`.
- Badges de status: `.badge`, `.badge-success`, `.badge-warning`, `.badge-danger`, `.badge-info`, `.badge-neutral`.
- Formulários: `.field-label`, `.field-hint`, `.field-error`, `.field-input`, `.filter-input`.
- Tabelas: `.table-wrap`, `.table-base` (+ regras de thead/th/td/linha).
- Estado vazio: `.empty-state`.
- Timeline: `.timeline-item`.
- Alertas/mensagens: `.alert`, `.alert-success`, `.alert-error`, `.alert-warning`, `.alert-info`.

Todas as telas novas de Manutenção/Higienização usam exclusivamente essas classes — nenhuma delas tem CSS ad hoc próprio.

### 6.3 O que mudou em `base.html`
- Cabeçalho: `bg-brand-black text-white`, logo "LOCUS Equipamentos" com destaque em dourado.
- Navegação: adicionados os links "Manutenções"/"Higienizações"; menu mobile com botão hamburger (`#nav-toggle`, acessível via `aria-expanded`/`aria-controls`) e JS vanilla mínimo — sem framework novo.
- Mensagens do sistema (`django.contrib.messages`) passam a usar `.alert-*` conforme a tag (error/warning/success/info), em vez de um estilo único genérico.
- Biblioteca de componentes `@layer components` descrita acima.
- Rodapé e script do htmx preservados sem alteração de comportamento.

### 6.4 Telas antigas afetadas indiretamente
Por serem mudanças em `base.html` (compartilhado por todas as páginas autenticadas), **toda tela existente do sistema herda automaticamente** o novo cabeçalho preto/dourado, o menu mobile e o novo estilo de mensagens — sem que nenhuma tela antiga tenha sido redesenhada individualmente nesta etapa, conforme solicitado. Essa herança foi confirmada de forma concreta: dois testes pré-existentes em `apps/operations/tests/test_duplicate_locations_report.py` quebraram como efeito colateral direto e precisaram de ajuste:
1. Um teste que verificava a ausência da string `bg-red-100` na página inteira — essa string agora aparece legitimamente no `<head>` de toda página, como parte do CSS de `.badge-danger`/`.alert-error`. Corrigido restringindo a verificação ao conteúdo após `<main`.
2. Um teste que esperava exatamente 1 `<button>` na página — o novo botão de menu mobile é o segundo `<button>` legítimo em toda página autenticada. Corrigido atualizando a contagem esperada para 2.

Nenhuma outra tela foi alterada nesta etapa; Equipamentos, Clientes, Unidades e Movimentações continuam com seus templates próprios, agora prontos para adotar as classes `.card`/`.btn-*`/`.table-*`/`.badge-*` numa etapa futura sem retrabalho de infraestrutura.

### 6.5 Confirmação de responsividade
Testado em viewport mobile (390×844) via Playwright headless: o menu hamburger abre/fecha corretamente (`aria-expanded` alterna, `#main-nav` alterna `.hidden`), e a listagem de Manutenções permanece legível e utilizável em largura reduzida.

**Limitação honesta sobre a verificação visual automatizada:** este ambiente de sandbox bloqueia o acesso de rede de saída ao CDN do Tailwind (`cdn.tailwindcss.com` — confirmado via `curl`, retorna `403` no proxy da sandbox). Por isso, as capturas de tela headless feitas aqui mostram o HTML **estruturalmente correto** (todos os campos, links, badges como texto, o toggle de menu funcionando via JS), mas **sem o CSS aplicado**, já que o navegador headless também não conseguiu buscar o CDN. Confirmei, lendo o HTML servido diretamente (`curl` no dev server local), que a tag `<script src="https://cdn.tailwindcss.com">`, o `tailwind.config` e o bloco `@layer components` estão corretos e presentes no HTML gerado. Em qualquer ambiente com acesso normal à internet — incluindo o Render — o CDN carrega normalmente e o layout renderiza como projetado. Essa é uma restrição deste sandbox de desenvolvimento, não um defeito no código, mas por isso a confirmação visual final (cores, espaçamento, cards) depende do checklist manual abaixo, a ser feito no Render.

## 7. Timeline

`get_equipment_history_timeline()` agora produz eventos distintos: `manutencao_aberta`, `manutencao_concluida`, `manutencao_cancelada`, `higienizacao`. Nenhum evento histórico de Status/Condition/Movement foi alterado — os novos blocos apenas se somam à lista antes do `sort()` final por `changed_at`. Cobertura de N+1: `select_related("responsible")` em ambas as queries (Maintenance/Cleaning), confirmado sem crescimento de query count por `EquipmentFichaSummaryQueryCountTest`.

## 8. Idempotência

Reaproveitado integralmente `apps.core.submission.SubmissionGuard` — nenhum mecanismo novo. Escopos: `maintenance_open` e `cleaning_create` (flat, um formulário por vez); `maintenance_close:<pk>`, `maintenance_cancel:<pk>`, `cleaning_cancel:<pk>` (por objeto). Confirmado por testes de duplo-submit em todos os 5 fluxos de escrita — nenhum cria/cancela duas vezes.

## 9. Otimização de queries (N+1)

- `MaintenanceListView`/`CleaningListView`: `select_related("equipment", "equipment__model", "responsible")`. Query count comparado entre poucos e muitos registros (mesma técnica de `test_duplicate_locations_report.py`) — confirmado que não cresce.
- `get_equipment_maintenance_summary()`: duas queries fixas (uma por model), independentemente do volume de eventos do equipamento.
- Nenhuma otimização foi aplicada fora das telas novas, conforme escopo.

## 10. Migrations

Nenhuma migration nova nesta etapa. `apps/maintenance/migrations/` permanece com `0001_initial.py`, `0002_maintenance_aberta_ativa_constraint.py`, `0003_alter_cleaning_movement_and_more.py` — inalteradas. A nova função de leitura em `services.py` não introduz nenhum campo/model novo.

## 11. Resultado final de verificação

- **Suíte completa:** 486/486 testes passando (379 pré-existentes + 107 novos), rodada contra PostgreSQL real.
- **`manage.py check`:** nenhum problema identificado.
- **`manage.py makemigrations --check --dry-run`:** nenhuma mudança pendente.
- **Cobertura dos testes obrigatórios:** permissões dos 4 papéis (leitura/escrita); abrir/concluir/cancelar Manutenção; erros de domínio sem 500; duplo-submit em todos os fluxos; Manutenção com/sem Movement de envio e retorno; Movement manipulado de outro equipamento rejeitado sem 500 (tanto em Manutenção quanto em Higienização); Higienização com/sem Movement; cancelamento de Higienização; pré-seleção a partir da ficha; timeline; filtros; paginação preservando filtros; ausência de N+1 nas listagens e na ficha do equipamento.

## 12. Checklist manual para validação visual no Render

1. Login: cabeçalho preto com logo "LOCUS Equipamentos" em dourado.
2. Navegação desktop: links "Manutenções" e "Higienizações" visíveis e funcionais.
3. Navegação mobile (largura reduzida): menu recolhe atrás do botão hamburger; abrir/fechar funciona.
4. Listagem de Manutenções: badges de status coloridos (aberta/concluída/cancelada), filtros e busca funcionando, paginação mantendo os filtros na URL ao trocar de página.
5. Abrir manutenção: campo de equipamento com busca incremental; seleção de equipamento atualiza a lista de movimentações de envio via htmx (sem recarregar a página).
6. Detalhe de manutenção: origem/destino/data do Movement de envio e retorno legíveis (não apenas IDs).
7. Concluir manutenção: só aparece para Manutenção ABERTA; tentar submeter com `return_movement` incompatível mostra mensagem de erro em português, não uma tela de erro 500.
8. Cancelar manutenção: exige marcar confirmação e informar motivo; tentar reenviar o mesmo formulário (duplo clique) não duplica o cancelamento.
9. Higienizações: registrar e cancelar seguem o mesmo padrão visual e de confirmação.
10. Ficha do equipamento: ações "Abrir manutenção"/"Registrar higienização" pré-selecionam o equipamento; seção "Manutenção e higienização" mostra o resumo (não a timeline inteira).
11. Timeline do equipamento: eventos de manutenção/higienização aparecem intercalados corretamente por data com os eventos antigos de Status/Movement/Condition.
12. Login como usuário CONSULTA: consegue ver as telas de Manutenção/Higienização mas não vê os botões de ação; tentar acessar a URL de abrir/concluir/cancelar diretamente retorna 403.
13. Conferir em pelo menos uma tela antiga (ex.: lista de Equipamentos) que o novo cabeçalho/menu aparece corretamente e nada quebrou visualmente.

## 13. Fora de escopo (confirmado, nada implementado)

Fotos/anexos, S3/storage, notificações, calendário, dashboard, jobs, recorrência automática, IA, alterações de deploy. Nenhum deploy foi realizado.

## 14. Git

Commit criado localmente (`Add operational UI for Maintenance and Cleaning`). `git push origin master` foi tentado e falhou com 403 — o proxy da sandbox não tem credencial autorizada para este repositório (`1hoooky/locus-equipamentos`), comportamento esperado e não bloqueante, consistente com o padrão já observado nas etapas anteriores.
