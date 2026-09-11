# Relatório — Auditoria Global de Navegação / Remoção de Links e Botões Redundantes com a Sidebar

**Data:** 11/09/2026
**Escopo:** Auditoria completa dos templates do LocusHub, para remover atalhos de navegação cuja única função é levar a uma página já representada diretamente na sidebar/drawer (aprovada na tarefa anterior de reorganização da navegação).
**Tipo de mudança:** Somente templates (HTML). Nenhum model, migration, service, regra de negócio ou lógica de permissão foi alterado.

---

## 1. Metodologia

Cada ocorrência de link/botão de navegação encontrada nos templates foi classificada antes de qualquer remoção, seguindo a taxonomia definida no pedido:

| Tipo | Significado | Decisão padrão |
|---|---|---|
| A | Navegação redundante — leva só a uma página já com entrada direta na sidebar, sem filtro/contexto extra | Remover |
| B | Ação da própria página (criar, editar, salvar, cancelar, excluir, importar, exportar, gerar etc.) | Manter |
| C | Navegação contextual — leva a uma entidade específica (ex.: "Abrir cliente X") que a sidebar não representa | Manter |
| D | Voltar/Cancelar de formulário ou de fluxo de drill-down | Manter (analisado caso a caso) |
| E | Breadcrumb | Manter quando indica hierarquia/contexto real |

Pergunta-guia aplicada em cada ocorrência: **"Este elemento permite executar alguma ação ou acessar algum CONTEXTO que a sidebar não consegue representar? Se sim, mantém. Se não, e o destino já está na sidebar, remove."**

Não foi feita nenhuma substituição cega por palavra-chave ("Ver", "Voltar", "Configurações"): cada ocorrência foi lida em contexto antes da decisão.

### Varredura realizada

Buscas em todo `templates/` por: todas as 16 rotas que hoje têm entrada direta na sidebar; padrões de texto `>Ver `, `>Ir para`, `>Abrir `, `Ver todos`, `Ver todas`; `breadcrumb` (nenhum componente de breadcrumb existe no projeto); cards clicáveis (`card-pad` com link); botões com ícone de engrenagem (`cog-6-tooth`) dentro de `<a>`; todas as ocorrências de `class="link"`. Além disso, leitura completa de `templates/dashboard/home.html`, `templates/crm/opportunity_detail.html`, das páginas de erro (`403.html`, `404.html`, `500.html`) e dos templates de formulário de cada módulo.

---

## 2. Tabela completa — elementos removidos (Tipo A)

| # | Arquivo | Tela | Elemento encontrado | Destino | Classificação | Decisão | Justificativa |
|---|---|---|---|---|---|---|---|
| 1 | `templates/crm/opportunity_stage_list.html` | Etapas do funil | Link "Config. comerciais" (topo) | `crm:commercial_source_list` (Origens) | A | Removido | Origens já é item direto do grupo CRM na sidebar; o link "pulava" para uma tela irmã sem nenhum contexto adicional. |
| 2 | `templates/crm/opportunity_stage_list.html` | Etapas do funil | "Ver origens →" / "Ver motivos de perda →" (rodapé) | `crm:commercial_source_list` / `crm:loss_reason_list` | A | Removido | **Exemplo literal citado no pedido.** As 3 telas de configuração comercial já estão diretamente na sidebar. |
| 3 | `templates/crm/commercial_source_list.html` | Origens comerciais | Link "Config. comerciais" (topo, self-link para a própria página) | `crm:commercial_source_list` (a própria tela) | A | Removido | Link apontava para a página em que o usuário já está; vestígio do antigo submenu de texto, sem função após a sidebar ganhar itens diretos. |
| 4 | `templates/crm/commercial_source_list.html` | Origens comerciais | "Ver etapas →" / "Ver motivos de perda →" (rodapé) | `crm:opportunity_stage_list` / `crm:loss_reason_list` | A | Removido | Mesmo raciocínio do item 2, aplicado à tela de Origens. |
| 5 | `templates/crm/loss_reason_list.html` | Motivos de perda | Link "Config. comerciais" (topo) | `crm:commercial_source_list` (Origens) | A | Removido | Mesmo raciocínio do item 1, aplicado à tela de Motivos de perda. |
| 6 | `templates/crm/loss_reason_list.html` | Motivos de perda | "Ver origens →" / "Ver etapas →" (rodapé) | `crm:commercial_source_list` / `crm:opportunity_stage_list` | A | Removido | Mesmo raciocínio do item 2, aplicado à tela de Motivos de perda. |
| 7 | `templates/crm/opportunity_list.html` | Funil (Kanban) | Botão "Configurações comerciais" | `crm:commercial_source_list` (Origens) | A | Removido | Levava só a Origens, sem nenhum filtro/contexto do Kanban. **Reversão de decisão anterior**: na rodada de reorganização da sidebar este botão havia sido mantido como "conveniência de contexto"; esta auditoria pediu explicitamente para reconsiderá-lo, e à luz da regra principal ele não passa mais no critério (a sidebar já cobre as 3 telas de configuração comercial). `can_manage_settings` permanece disponível no contexto da view (não é mais lido pelo template — nenhuma lógica de permissão foi alterada). |
| 8 | `templates/catalog/category_list.html` | Categorias | "Ver modelos de equipamento →" (rodapé) | `catalog:model_list` (Modelos) | A | Removido | Modelos já é item direto do grupo Cadastros na sidebar. |
| 9 | `templates/catalog/model_list.html` | Modelos de equipamento | "Ver categorias" (rodapé) | `catalog:category_list` (Categorias) | A | Removido | Categorias já é item direto do grupo Cadastros na sidebar. |
| 10 | `templates/equipment/import_summary.html` | Resumo de importação de equipamentos | "Ver equipamentos" (rodapé) | `equipment:list` (Equipamentos) | A | Removido | Equipamentos já é item direto do grupo Operação na sidebar. Os links individuais para cada patrimônio recém-criado (Tipo C) foram mantidos. |
| 11 | `templates/clients/import_summary.html` | Resumo de importação de clientes | "Ver clientes" (rodapé) | `clients:list` (Clientes) | A | Removido | Clientes já é item direto do grupo Cadastros na sidebar. Os links individuais para cada cliente recém-criado (Tipo C) foram mantidos. |

**Total de elementos Tipo A removidos: 11**, em **8 arquivos**.

---

## 3. Amostra representativa de elementos mantidos (com justificativa)

| Arquivo | Tela | Elemento | Classificação | Decisão | Justificativa |
|---|---|---|---|---|---|
| `templates/crm/opportunity_detail.html` | Detalhe de oportunidade | "Abrir cliente" → `clients:detail` do cliente específico da oportunidade | C | Mantido | **Exemplo literal do pedido.** Leva a uma entidade específica; a entrada genérica "Clientes" da sidebar não substitui isso. |
| `templates/crm/opportunity_detail.html` | Detalhe de oportunidade | "Voltar" → `crm:opportunity_list` (Funil) | D (drill-down) | Mantido | Padrão universal de retorno de uma tela de detalhe para a listagem de origem, presente em todo o sistema; o pedido pede explicitamente para NÃO remover automaticamente só porque a listagem também está na sidebar. |
| `templates/crm/opportunity_detail.html` | Detalhe de oportunidade | "Editar" / botões de mudança de etapa / registrar atividade | B | Mantido | Ações da própria página. |
| Todas as telas de listagem (Origens, Etapas, Motivos de perda, Categorias, Modelos, Clientes, Equipamentos etc.) | — | Botões "Nova origem", "Nova etapa", "Novo motivo", "Nova categoria", "Novo modelo", "Novo cliente", "Novo equipamento" | B | Mantido | Ações da própria página (criar). |
| `templates/dashboard/home.html` | Início | Cards "Disponíveis", "Em uso", "Em manutenção", "Higienização" → `equipment:list?status=...` / `maintenance:*` com filtro de status | C | Mantido | Levam a uma listagem **filtrada** por status — contexto que a sidebar (entrada genérica) não representa. Esta é, inclusive, a função central da Home (já documentada em `AUDITORIA_UX_HOME_NAVEGACAO_QR.md`, de tarefa anterior). |
| `templates/equipment/import_summary.html`, `templates/clients/import_summary.html` | Resumo de importação | Links individuais por patrimônio/cliente recém-criado | C | Mantido | Levam à entidade específica recém-criada; a sidebar não tem como representar isso. |
| `templates/equipment/reclassify.html` | Reclassificação de patrimônio | "Reemitir patrimônio" → `equipment:supersede` do mesmo equipamento | C | Mantido | Ação/navegação sobre a mesma entidade em contexto, não é atalho para uma tela da sidebar. |
| `templates/accounts/password_reset_complete.html` | Recuperação de senha concluída | "Entrar" → `accounts:login` | Fora de escopo | Mantido | Fluxo anônimo, sem sidebar (usuário ainda não está autenticado). |
| `templates/403.html`, `404.html`, `500.html` | Páginas de erro | "Voltar ao início" | Fora de escopo | Mantido | Essas páginas deliberadamente NÃO estendem `base.html` (sem sidebar), por resiliência — não há nada para ser redundante com elas. |
| Todos os formulários de criação/edição (oportunidade, cliente, equipamento, categoria, modelo, unidade, usuário, cargo etc.) | — | "Cancelar" / "Voltar" | D | Mantido | Necessário para retornar ao contexto anterior do fluxo de formulário; não removido "só porque a listagem também existe na sidebar" (instrução explícita do pedido). |

Nenhum breadcrumb foi encontrado no projeto (Tipo E não se aplica — não há componente desse tipo implementado no LocusHub).

---

## 4. Números finais

- **Telas auditadas:** 15 (as mesmas do checklist manual, seção 6) + Home/Início + páginas de erro + formulários de criação/edição de todos os módulos.
- **Elementos de navegação analisados individualmente:** 27 (11 removidos + 16 documentados na amostra representativa da seção 3; os demais elementos do tipo B — botões de ação — seguem o mesmo padrão em cada tela e não foram listados um a um por serem repetitivos, mas foram conferidos em cada arquivo tocado e em cada tela do checklist).
- **Elementos removidos (Tipo A):** 11
- **Elementos mantidos:** todos os demais (Tipo B, C, D e os fora de escopo listados acima) — nenhum foi removido.
- **Arquivos alterados:** 8 templates + 1 arquivo de teste novo (não conta como alteração funcional).

### Arquivos alterados

```
templates/catalog/category_list.html
templates/catalog/model_list.html
templates/clients/import_summary.html
templates/crm/commercial_source_list.html
templates/crm/loss_reason_list.html
templates/crm/opportunity_list.html
templates/crm/opportunity_stage_list.html
templates/equipment/import_summary.html
```

Arquivo novo (teste de regressão, não é mudança funcional):
```
apps/core/tests/test_navigation_redundancy_audit.py
```

---

## 5. Confirmações exigidas

**5.1 — Nenhuma rota ficou órfã.** Todas as 16 URLs que possuem entrada direta na sidebar continuam acessíveis por ela; o teste `test_sidebar_still_links_directly_to_every_audited_destination` (novo) confirma programaticamente que a sidebar contém `href` para as 15 rotas do checklist manual, sempre que a página é renderizada. Nenhuma `view`, `url` ou rota foi removida ou alterada — apenas links de conteúdo de página foram removidos, nunca as próprias rotas.

**5.2 — Permissões inalteradas.** Nenhum `RoleRequiredMixin`, `allowed_roles`, verificação `has_perm`, ou lógica de exibição condicional de itens da sidebar foi tocada. O único contexto de view que deixou de ser *lido* por um template foi `can_manage_settings` (em `opportunity_list.html`) — a variável continua sendo calculada e passada pela view exatamente como antes; apenas o template parou de usá-la, porque o botão que a consumia foi removido. Isso não amplia nem restringe acesso de ninguém: quem via o botão antes só o via porque já tinha a mesma permissão que hoje dá acesso ao item "Origens" na sidebar (mesma regra de exibição, aplicada agora só pela sidebar).

**5.3 — Nenhum link interno era a ÚNICA forma de acesso a uma funcionalidade.** Todos os 11 elementos removidos apontavam para páginas que já têm entrada direta e incondicional na sidebar (para quem tem permissão de ver aquele grupo/página) — não havia nenhum caso de "atalho que aparecia para um perfil que não tinha o item equivalente na sidebar", porque a sidebar usa exatamente as mesmas checagens de permissão que protegiam as páginas de destino.

---

## 6. Checklist manual de homologação (15 telas)

Validado via o novo teste automatizado `apps/core/tests/test_navigation_redundancy_audit.py` (19 testes, executando como usuário admin/superuser contra o app real), reproduzindo o roteiro pedido para cada tela:

| # | Tela | Sem atalho redundante para item já na sidebar | Ações próprias da tela presentes | Navegação contextual (quando necessária) presente | Sidebar leva corretamente ao destino |
|---|---|---|---|---|---|
| 1 | Funil | ✅ ("Configurações comerciais" removido) | ✅ "Nova oportunidade", "Filtrar" | ✅ (dentro do detalhe: "Abrir cliente") | ✅ |
| 2 | Origens | ✅ ("Config. comerciais", "Ver etapas", "Ver motivos de perda" removidos) | ✅ "Nova origem" | — | ✅ |
| 3 | Etapas | ✅ ("Config. comerciais", "Ver origens", "Ver motivos de perda" removidos) | ✅ "Nova etapa" | — | ✅ |
| 4 | Motivos de perda | ✅ ("Config. comerciais", "Ver origens", "Ver etapas" removidos) | ✅ "Novo motivo" | — | ✅ |
| 5 | Equipamentos | ✅ (nada a remover) | ✅ "Novo equipamento" | — | ✅ |
| 6 | Manutenções | ✅ (nada a remover) | ✅ (renderiza 200, ações intactas) | — | ✅ |
| 7 | Higienizações | ✅ (nada a remover) | ✅ (renderiza 200) | — | ✅ |
| 8 | Clientes | ✅ (nada a remover) | ✅ "Novo cliente" | — | ✅ |
| 9 | Colaboradores | ✅ (nada a remover) | ✅ (renderiza 200) | — | ✅ |
| 10 | Unidades | ✅ (nada a remover) | ✅ (renderiza 200) | — | ✅ |
| 11 | Categorias | ✅ ("Ver modelos de equipamento" removido) | ✅ "Nova categoria" | — | ✅ |
| 12 | Modelos | ✅ ("Ver categorias" removido) | ✅ "Novo modelo" | — | ✅ |
| 13 | Cargos | ✅ (nada a remover) | ✅ (renderiza 200) | — | ✅ |
| 14 | Diagnóstico de unidades | ✅ (nada apontava para cá — nada a remover) | ✅ (renderiza 200) | — | ✅ |
| 15 | Importações (equipamentos e clientes) | ✅ ("Ver equipamentos"/"Ver clientes" removidos dos resumos) | ✅ upload/wizard intactos | ✅ (links individuais por item importado mantidos) | ✅ |

---

## 7. Testes e checks

### 7.1 Novo teste de regressão

`apps/core/tests/test_navigation_redundancy_audit.py` — 19 testes cobrindo as 15 telas do checklist:

```
19 passed in 9.18s
```

### 7.2 Suíte completa do projeto

```
999 passed, 1 failed in 329.95s (0:05:29)
```

A única falha é `apps.core.tests.test_i18n_encoding_audit.MojibakeRegressionTest.test_no_mojibake_in_tracked_repository_files` — um teste **pré-existente e não relacionado** a esta auditoria: ele varre o repositório por marcadores de mojibake e encontra os próprios marcadores de exemplo dentro do texto do seu arquivo de teste e de um relatório de auditoria de idioma anterior (`AUDITORIA_IDIOMA_LOCALIZACAO_UTF8.md`) — um falso positivo do próprio teste sobre si mesmo, já presente antes desta tarefa e fora do escopo desta auditoria de navegação. Nenhum arquivo tocado nesta auditoria aparece na lista de ofensores.

Antes desta rodada de mudanças, a mesma suíte já apresentava exatamente essa mesma falha isolada (confirmado na tarefa anterior, "980 passed / 1 pre-existing unrelated failure"); com os 19 testes novos desta auditoria, o total sobe para 999 passados + a mesma 1 falha pré-existente — **zero regressões**.

### 7.3 `manage.py check`

```
System check identified no issues (0 silenced).
```

### 7.4 `makemigrations --check --dry-run`

```
No changes detected
```

Confirma que nenhuma alteração de model/banco de dados foi introduzida — consistente com o escopo estritamente de templates desta tarefa.

---

## 8. Observações finais

- Nenhuma exceção que exigisse alteração de backend foi encontrada. Todo o trabalho ficou restrito a templates (`.html`), conforme exigido.
- Nenhum model, migration, service, regra de negócio de CRM, lógica de drag-and-drop do Kanban, transição de etapas ou histórico foi tocado.
- Nenhuma permissão foi criada, ampliada, restringida ou de qualquer forma alterada.
- **Nenhum push, nenhum deploy foi realizado** — todas as mudanças estão apenas commitadas localmente neste ambiente de trabalho, exatamente como nas entregas anteriores.
