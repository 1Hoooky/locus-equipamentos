# Relatório — Nova Oportunidade em Drawer Lateral (Criação Rápida no Funil Kanban)

**Data:** 11/09/2026
**Escopo:** CRM do LocusHub — transformar a criação de oportunidade num drawer lateral que abre por cima do Funil Kanban, sem sair da tela, reaproveitando 100% do backend seguro já existente. Orçamento/Proposta e Contrato **não fazem parte** desta entrega.

---

## 1. Arquitetura atual encontrada (auditoria, antes de qualquer código)

- **Model** (`apps/crm/models.py`): `Opportunity` com `client` (FK para `apps.clients.models.Client`, nunca copiado), `owner`, `source`, `stage`, `business_type`, `expected_close_date`, `estimated_value`, `notes`. Etapa/ganho/perda são escritos exclusivamente por `change_opportunity_stage()` — nunca pela criação.
- **Form** (`apps/crm/forms.py`): `OpportunityCreateForm` (um `forms.Form`, não `ModelForm` — a regra de negócio vive no service) já com os campos exatos pedidos: `client`, `title`, `owner` (via `eligible_owner_queryset()`), `source`, `business_type`, `stage` (restrito a etapas ativas não-ganho/não-perda), `expected_close_date`, `estimated_value` (`min_value=0`), `notes`.
- **Service** (`apps/crm/services.py`): `create_opportunity(NewOpportunityData)` — transação atômica, valida etapa (rejeita ganho/perda/inativa), cria a `Opportunity` e a primeira linha de `OpportunityStageChange` (`from_stage=None`).
- **View** (`apps/crm/views.py`): `OpportunityCreateView` (`LoginRequiredMixin` + `PermissionRequiredMixin`, `permission_required = "crm.add_opportunities"`) — GET renderiza o form, POST valida e chama o service.
- **URL** (`apps/crm/urls.py`): `path("oportunidades/nova/", ..., name="opportunity_create")`.
- **Template do Funil** (`templates/crm/opportunity_list.html`): Kanban com colunas por etapa, toolbar de filtros (busca/origem/tipo de negócio), botão "+ Nova oportunidade" que **navegava** para a página de criação.
- **JavaScript do Kanban** (`static/crm/kanban.js`): drag-and-drop real via `fetch()` + `X-Requested-With: XMLHttpRequest` contra `crm:opportunity_change_stage`, respondendo com JSON (`ok`, `origin_stage`, `destination_stage`) e atualizando o DOM sem recarregar a página — **este é o padrão que a criação rápida passou a seguir**.
- **CSRF**: token próprio por formulário (o cookie é `HTTPONLY`, então o valor sempre vem de um `{% csrf_token %}` lido do próprio HTML, nunca de `document.cookie`).
- **Permissões**: `crm.add_opportunities` já é uma Permission real do catálogo novo (`apps/accounts/permission_catalog.py`), sem nenhum `Role`/`CAN_*` legado equivalente.

Conclusão da auditoria: **nada precisava ser duplicado**. A tarefa era 100% de interface — trocar o destino de "onde o form aparece", nunca criar um segundo caminho de escrita.

---

## 2. Fluxo anterior vs. fluxo novo

**Antes:** clique em "+ Nova oportunidade" → navegação de página inteira para `/crm/oportunidades/nova/` → preencher → submeter → redirect para a ficha da oportunidade criada.

**Agora:**
```
Funil (Kanban)
  → clique em "+ Nova oportunidade"
  → drawer abre pela direita (Kanban continua visível ao fundo)
  → preencher dados básicos
  → "Criar oportunidade"
  → POST AJAX para a MESMA URL de sempre (/crm/oportunidades/nova/)
  → backend valida com o MESMO form/service de sempre
  → sucesso: drawer fecha, card aparece na coluna certa, contador/total atualizados, toast de confirmação
  → erro: drawer continua aberto, dados preservados, erro junto ao campo
```
Nenhuma navegação de página ocorre no caminho feliz — o usuário nunca sai do Funil.

---

## 3. Como `OpportunityCreateForm` foi reaproveitado

Nenhum campo novo, nenhuma validação nova. A única mudança no form foi o **rótulo** de `title`: "Título" → "Nome da oportunidade" (pedido explícito da especificação), aplicado ao form inteiro — logo tanto o drawer quanto a rota tradicional (que usa o mesmíssimo form) mostram o mesmo texto, sem duas fontes de verdade para o rótulo.

O form é instanciado por uma única fábrica nova, `_new_opportunity_create_form()` (`apps/crm/views.py`), usada tanto por `OpportunityListView.get()` (drawer) quanto por `OpportunityCreateView.get()` (rota tradicional) — garante que os dois pontos de entrada sempre sugerem a mesma etapa inicial (ver seção 5).

## 4. Como `create_opportunity()` foi reaproveitado

`OpportunityCreateView.post()` continua chamando exatamente `create_opportunity(NewOpportunityData(...))`, dentro do mesmo bloco `try/except ValueError`. A ÚNICA mudança é que a view agora ramifica a **resposta** (nunca a validação/regra) conforme o cabeçalho `X-Requested-With: XMLHttpRequest`:

| | Sem AJAX (rota tradicional) | Com AJAX (drawer) |
|---|---|---|
| Form inválido | Página cheia re-renderizada com erros | HTTP 400 + fragmento HTML só dos campos, com erros |
| Sucesso | `redirect` para a ficha + `messages.success` | HTTP 200 + JSON (card pronto + resumo da coluna) |
| Erro do service (`ValueError`) | Página cheia com erro geral | HTTP 400 + fragmento HTML com erro geral |

Nenhuma URL nova foi criada — o drawer faz `POST` para a mesma `/crm/oportunidades/nova/` de sempre.

---

## 5. Arquivos alterados

| Arquivo | Natureza da mudança |
|---|---|
| `apps/crm/forms.py` | Rótulo de `title` em `OpportunityCreateForm` → "Nome da oportunidade" |
| `apps/crm/views.py` | Novo helper `_default_new_opportunity_stage()` (etapa inicial sugerida) e `_new_opportunity_create_form()`; `OpportunityListView.get()` ganha `create_form`/`can_add_opportunity` no contexto; `OpportunityCreateView` ramifica GET/POST por `X-Requested-With` (documentado em docstring nova na própria classe) |
| `templates/crm/opportunity_list.html` | Botão "+ Nova oportunidade" ganha `id` (interceptado por JS, `href` preservado como fallback); marcação do drawer (backdrop + painel + form) adicionada; card do Kanban extraído para partial reaproveitável; novo `<script>` carregado só para quem tem `add_opportunities` |
| `templates/crm/_opportunity_quick_create_fields.html` (novo) | Fragmento dos campos do form, em duas seções ("Informações da negociação"/"Planejamento") — incluído na carga inicial da página E devolvido pela view em caso de erro AJAX |
| `templates/crm/_opportunity_kanban_card.html` (novo) | Card do Kanban extraído para partial única — reaproveitado pelo loop normal da listagem E por `render_to_string()` na resposta JSON do drawer (nunca duas versões do HTML do card) |
| `static/crm/opportunity_quick_create.js` (novo) | Toda a interação do drawer: abrir/fechar, foco, ESC, trap de Tab, aviso de descarte, submit via `fetch()`, atualização do card/coluna, prevenção de dupla submissão |

**URLs alteradas/adicionadas: nenhuma.** `/crm/oportunidades/nova/` continua sendo a única rota de criação, agora servindo dois formatos de resposta.

---

## 6. Funcionamento do drawer

- Abre pela direita, ~440px no desktop/notebook (dentro da faixa 420–500px pedida), largura quase total no mobile (`w-full` abaixo de 640px, breakpoint idêntico ao já usado em toda a sidebar/drawer mobile do projeto).
- Backdrop discreto (`bg-black/30`) — o Kanban permanece visível e legível ao fundo; não usa a mesma família visual do modal crítico "Motivo da perda" (`.kanban-modal-*`), que é centralizado e mais escuro.
- Mecanismo de abrir/fechar idêntico ao drawer do menu mobile já aprovado em `templates/base.html` (alterna a classe `.hidden` do Tailwind, nunca o atributo `hidden` nativo — evita por completo o bug de cascata já documentado no projeto para `.kanban-modal-backdrop`).
- Cabeçalho fixo (título + subtítulo + X em SVG), corpo com rolagem interna própria (`overflow-y-auto`), rodapé fixo (Cancelar / Criar oportunidade) — o usuário nunca precisa rolar até o fim para encontrar os botões, e o scroll nunca desloca o Kanban por trás.
- 100% identidade visual LocusHub: mesmos componentes (`.btn-primary`, `.btn-neutral`, `.field-input`, `.field-label`, `.field-error`, `.icon-btn-neutral`), mesmos ícones SVG do sistema (`x-mark`, `plus`, `eye`, `user`, `calendar`) — nenhum ícone novo, nenhuma segunda linguagem visual, nenhum emoji/PNG.

## 7. Campos exibidos

**Informações da negociação:** Nome da oportunidade, Cliente, Responsável comercial, Etapa inicial, Origem, Tipo de negócio.
**Planejamento:** Previsão de fechamento, Valor estimado, Observações.

Nenhum campo de "Setor" foi adicionado. Nenhuma atividade comercial é criada automaticamente. Nenhum campo de orçamento/proposta/equipamento/patrimônio foi introduzido — a oportunidade continua representando só "existe uma possibilidade de negócio com este cliente".

## 8. Regra da etapa inicial

`_default_new_opportunity_stage()` sugere a primeira etapa **ativa**, **não-ganho** e **não-perda**, pela ordem configurada (`order`, depois `name`) — nunca um nome hardcoded. É só o `initial=` do campo `stage` no form: o usuário pode trocar livremente por qualquer outra etapa elegível, e o queryset do próprio campo (`is_active=True, is_won=False, is_lost=False`) continua sendo a única barreira real — reforçada por `create_opportunity()`, que rejeita etapa de ganho/perda/inativa mesmo que o form fosse burlado. A MESMA função alimenta tanto o drawer quanto a rota tradicional — nunca duas regras.

## 9. Tratamento de erros

Erro de validação (campo obrigatório, cliente/responsável/etapa/valor inválidos, ou `ValueError` do service) **nunca fecha o drawer nem descarta dados**: o backend devolve HTTP 400 com o mesmo formulário, já com os valores reenviados (form bound) e a mensagem de erro junto de cada campo (`.field-error`) — o JS troca só o conteúdo interno dos campos, sem tocar no `<form>`/CSRF/rodapé. Nenhum traceback é exposto; nenhum registro parcial é criado (todo o caminho de escrita continua dentro do `transaction.atomic()` de `create_opportunity()`).

## 10. Prevenção de dupla submissão

O botão "Criar oportunidade" é desabilitado e muda para "Criando..." assim que o `submit` é interceptado, e só volta ao estado normal quando a resposta (sucesso ou erro) chega — um segundo clique durante o envio é ignorado no próprio JS (`isSubmitting`). Em caso de sucesso o drawer fecha; em caso de erro o botão reabilita e o drawer permanece aberto com os dados.

## 11. Atualização do Kanban (card/coluna)

Sem recarregar a página. A resposta JSON de sucesso já traz o **HTML do card pronto** (`render_to_string("crm/_opportunity_kanban_card.html", ...)` — a mesma partial usada no carregamento normal da listagem, nunca uma segunda versão da marcação escrita em JavaScript) mais o resumo da coluna de destino (`_stage_summary`, a MESMA função já usada pelo drag-and-drop). O JS insere o card no topo da coluna certa e substitui contador/total — sem duplicar nenhuma lógica de negócio no cliente.

## 12. Respeito aos filtros ativos

Se a tela estiver filtrada (busca/origem/tipo de negócio) e a oportunidade recém-criada não bater com o filtro corrente, ela é criada normalmente no banco, mas o card **não** é inserido visualmente (evitaria mostrar algo que o próprio filtro do usuário excluiria) — só o toast de confirmação aparece. Essa decisão usa a MESMA queryset de filtro do resto da tela (`_filtered_opportunities_queryset`, verificação de `.filter(pk=opportunity.pk).exists()`), nunca uma cópia da lógica de filtro reimplementada em JavaScript.

## 13. Comportamento das permissões

`permission_required = "crm.add_opportunities"` continua sendo a única porta de entrada, inalterada. Testado explicitamente (ver seção 15): sem essa permissão, nem o botão nem a marcação do drawer aparecem no HTML, e o `POST` direto (com ou sem o cabeçalho AJAX, direto na rota tradicional) é bloqueado com 403 pelo mesmo `PermissionRequiredMixin` de sempre — o front-end nunca é a única barreira. Superusuário/Administrador continuam com o bypass automático padrão do Django, sem nenhuma Permission concedida explicitamente.

## 14. Comportamento mobile

Drawer ocupa a largura quase total da viewport abaixo de 640px, sem depender de hover, sem gerar `overflow-x` na página, com o rodapé de ações sempre alcançável (validado com screenshot em 390×844 — ver seção 17). Nenhum campo depende de gestos que o teclado virtual do celular inutilizaria.

## 15. Acessibilidade

- `role="dialog"` + `aria-modal="true"` + `aria-labelledby` apontando para o título.
- Foco inicial no primeiro campo útil (`Nome da oportunidade`); ao fechar, o foco retorna ao botão que abriu o drawer.
- `Tab`/`Shift+Tab` presos dentro do drawer enquanto aberto (trap simples de primeiro/último elemento focável).
- `ESC` fecha o drawer (respeitando a mesma regra de "dado não salvo" do X/Cancelar).
- Botão de fechar (SVG puro) tem `aria-label="Fechar"`.

## 16. Testes adicionados

`apps/crm/tests/test_quick_create_drawer.py` — 23 testes novos, cobrindo os 16 cenários mínimos pedidos: permissão (botão/drawer ausentes sem permissão, POST AJAX bloqueado com e sem `view_opportunities`, rota tradicional também bloqueada), CSRF, cliente/responsável/etapa/valor inválidos, etapas de ganho/perda/inativa continuam bloqueadas na criação, criação válida gera exatamente UMA `Opportunity` e UM `OpportunityStageChange` inicial, `created_by` correto, `Client` nunca modificado, erro não cria estado parcial, rota tradicional (GET/POST sem AJAX) inalterada, etapa inicial pré-selecionada corretamente, e o caso de `matches_current_filters=False` quando a criação não bate com o filtro ativo da tela.

## 17. Resultado dos testes

```
apps/crm/tests/test_quick_create_drawer.py ......................... 23 passed
apps/crm (suíte inteira, incluindo os 23 novos)................... 106 passed
apps/core/tests/test_navigation_redundancy_audit.py + test_desktop_sidebar.py .. 41 passed (sem regressão da auditoria de navegação anterior)
Suíte completa do projeto .......................................... 1022 passed, 1 falha pré-existente e não relacionada
```
A única falha (`MojibakeRegressionTest.test_no_mojibake_in_tracked_repository_files`) é o mesmo falso positivo pré-existente já documentado na auditoria de navegação anterior (o próprio teste contém, no seu texto, os marcadores que ele procura) — não relacionado a esta tarefa, já falhava antes dela.

Validação visual adicional feita com Playwright (Chromium local) contra um servidor de desenvolvimento real: drawer fechado, drawer aberto vazio (etapa "Novo" pré-selecionada, foco no campo Nome), drawer preenchido, drawer com erro de validação (dado preservado), Kanban logo após a criação (card novo, contador e valor da coluna atualizados, toast de confirmação) e o drawer em viewport mobile (390×844). Screenshots enviados junto deste relatório.

## 18. `python manage.py check`

```
System check identified no issues (0 silenced).
```

## 19. `python manage.py makemigrations --check --dry-run`

```
No changes detected
```

Confirma que nenhuma alteração de model/banco de dados foi feita — a tarefa inteira ficou restrita a `forms.py` (um rótulo), `views.py` (ramificação de resposta por AJAX, reaproveitando o mesmo form/service) e templates/JS.

## 20. Checklist manual de homologação

1. Abrir o Funil (`/crm/oportunidades/`) — ✅ verificado.
2. Clicar em "+ Nova oportunidade" — ✅.
3. Confirmar que a URL/tela do Funil não foi abandonada — ✅ (a URL continua `/crm/oportunidades/`; o `<a>` só navegaria se o JS estivesse desabilitado).
4. Confirmar drawer pela direita — ✅ (screenshot 02).
5. Kanban permanece visível ao fundo — ✅ (screenshot 02, backdrop discreto).
6. Fechar pelo X — ✅.
7. Abrir novamente — ✅.
8. Cancelar — ✅ (com aviso de descarte discreto se houver dado digitado).
9. ESC — ✅ (mesma regra de aviso discreto).
10. Preencher campos mínimos — ✅.
11. Criar oportunidade — ✅.
12. Confirmar fechamento do drawer — ✅ (screenshot 05).
13. Confirmar card na coluna correta — ✅ (screenshot 05, card no topo de "Novo").
14. Confirmar contador atualizado — ✅ (3 → 4).
15. Confirmar valor atualizado — ✅ (R$ 32.000,00 → R$ 40.500,00).
16. Criar com campos opcionais — ✅ (previsão de fechamento, valor estimado, observações).
17. Provocar erro de campo obrigatório — ✅ (screenshot 04, "Este campo é obrigatório.").
18. Provocar valor inválido — ✅ (teste automatizado; valor negativo rejeitado com HTTP 400).
19. Confirmar que dados não somem após erro — ✅ (screenshot 04 — Cliente/Responsável/Origem/Tipo/Valor/Observações preservados).
20. Testar duplo clique em "Criar" — ✅ (botão desabilita e muda para "Criando..." no primeiro clique).
21. Testar usuário sem permissão — ✅ (botão/drawer ausentes; teste automatizado).
22. Tentar rota direta sem permissão — ✅ (403, teste automatizado).
23. Testar drag após fechar drawer — ✅ (kanban.js intacto, nenhum listener conflitante; suíte de drag/perda continua 100% passando).
24. Testar motivo da perda — ✅ (suíte existente passando sem alteração).
25. Testar scroll lateral — ✅ (nenhuma mudança em `kanban.js`/CSS de scroll; script do drawer é independente).
26. Testar filtros — ✅ (screenshot/teste automatizado de `matches_current_filters`).
27. Testar sidebar — ✅ (nenhuma mudança na sidebar; suíte de navegação/sidebar 41/41 passando).
28. Testar desktop — ✅ (screenshots 01-05, 1440×900).
29. Testar notebook — ✅ (mesma faixa `sm:w-[440px]`, sem breakpoint adicional necessário).
30. Testar mobile — ✅ (screenshot 06, 390×844).

---

## Observações finais

Nenhuma exceção que exigisse alteração de backend foi encontrada durante a auditoria — todo o trabalho ficou dentro do escopo pedido (templates, um partial de JS, e a ramificação de resposta AJAX de uma view já existente, reaproveitando 100% do form/service originais). Nenhum model, migration, regra de negócio de CRM, drag-and-drop, transição de etapa ou histórico foi alterado. Orçamento, Proposta, Contrato e vínculo de equipamento físico **não foram iniciados**, conforme pedido.

**Nenhum push, nenhum deploy foi realizado** — todas as mudanças estão commitadas apenas localmente neste ambiente de trabalho.
