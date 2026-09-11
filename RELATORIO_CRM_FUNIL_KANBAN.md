# LocusHub — Funil Kanban de Oportunidades (CRM)

**Data:** 11/09/2026
**Módulo:** `apps/crm` (Etapa 1 — fundação comercial, já em produção interna)
**Tipo de mudança:** só apresentação/interação da listagem de oportunidades — nenhum model, migration, permissão ou regra de negócio nova.

---

## 1. Contexto e pedido

Foi anexada uma captura de tela de um CRM de terceiro (`crmlocus.unionsystem.com.br`) como **referência de UX/estrutura**, com instrução explícita sobre o que observar (organização horizontal das etapas, cards, contagem/valor consolidado por coluna, filtros acima do funil, movimentação visual entre colunas) e o que **não** copiar (identidade visual, cores, logotipo, tipografia, ícones, fundo azul das colunas, estrutura pixel a pixel). O pedido foi reproduzir a **experiência e a lógica de uso**, não o design — o resultado deveria parecer um produto próprio (LocusHub, identidade preto + branco + cinza + dourado Locus), com o código atual do LocusHub continuando como fonte da verdade para arquitetura, permissões, dados e regras de negócio.

Antes de codar, três decisões de escopo foram confirmadas com você (perguntas de esclarecimento, já que era uma feature grande e ambígua):

1. **Interação de mover card:** drag-and-drop real entre colunas (não um clique que abre formulário).
2. **Relação com a listagem antiga:** o Kanban **substitui por completo** a listagem em tabela — mesma URL/view de sempre (`crm:opportunity_list`, `/crm/oportunidades/`), sem alternância entre os dois modos.
3. **Filtros acima do funil:** os mesmos que já existiam na listagem (busca por título/cliente, Origem, Tipo de negócio) — **não** o conjunto da imagem de referência (Setor/Usuário/Situação/Status/Cliente/Período não existem como conceito no LocusHub hoje, e inventar esses conceitos estava fora de escopo). Consequência direta: o filtro de **Etapa** foi removido — no Kanban a própria coluna já é a etapa, um filtro por etapa não faz sentido estrutural ao lado dele.

## 2. O que foi construído

### 2.1 Backend (`apps/crm/views.py`)

- **`_filtered_opportunities_queryset(params)`** — função nova, fonte única de "quais oportunidades entram na conta". Filtra por `owner`/`source`/`business_type`/`client`/`q` (os mesmos filtros de sempre, com a mesma proteção contra FK inválida em querystring adulterada — `.isdigit()` antes de filtrar por PK, igual ao padrão já usado em `apps.equipment.filters`). **Sem filtro por `stage`** — decisão 3 acima.
- **`_stage_summary(stage, params)`** — conta e soma o valor consolidado de uma etapa respeitando os filtros ativos; usada pelo endpoint AJAX para devolver os totais atualizados de origem/destino depois de um arraste.
- **`OpportunityListView`** — deixou de ser uma `ListView` paginada e virou a view do Kanban: agrupa as oportunidades (respeitando os filtros) por etapa ativa, calcula contagem e valor total por coluna, e passa a lista de motivos de perda ativos para o modal de arraste.
- **`OpportunityStageChangeView`** — o **mesmo endpoint de sempre** (`POST /crm/oportunidades/<pk>/etapa/`) ganhou um branch novo: quando a requisição chega com o cabeçalho `X-Requested-With: XMLHttpRequest` (só o `fetch()` do Kanban envia isso — o formulário HTML normal da ficha da oportunidade nunca envia), a resposta vira JSON (`{"ok": true/false, ...}`) em vez de redirect + `messages`. A **validação e a regra de negócio são exatamente as mesmas** nos dois casos — os dois caminhos chamam o mesmo `OpportunityStageChangeForm` e o mesmo `apps.crm.services.change_opportunity_stage()` (a única função que já existia, e continua sendo a única, para gravar etapa/ganho/perda). Não existe nenhum caminho de escrita "mais permissivo" pelo Kanban: mesma permission_required, mesma validação de motivo de perda obrigatório em etapa de perda, mesmo `select_for_update()` contra corrida entre duas mudanças simultâneas.

### 2.2 `apps/core/templatetags/currency.py`

Pequeno refactor: a lógica de formatação (`"R$ 1.234,56"`) virou uma função pura `format_brl(value)`, com o filtro de template `brl` como um wrapper fino dela. Isso permitiu ao backend do Kanban formatar os totais de coluna e das respostas JSON com a **mesma** função usada em todo o resto do sistema — nenhuma duplicação de lógica de formatação de dinheiro no JavaScript.

### 2.3 Template (`templates/crm/opportunity_list.html`)

Reescrito por completo: cabeçalho + filtros (busca/Origem/Tipo de negócio, sem Etapa) + quadro Kanban com rolagem horizontal (todas as colunas lado a lado) e rolagem vertical própria por coluna (cabeçalho da coluna sempre visível). Cada card mostra título, cliente, responsável e valor, com um botão "ver" (ícone de olho, mesmo padrão do resto do sistema) para ir à ficha completa sem precisar arrastar. Cards só são arrastáveis para quem tem a permissão `crm.change_opportunity_stage` — sem essa permissão, o Kanban continua 100% funcional como visualização, só sem a possibilidade de arrastar.

O CSRF token é exposto num campo oculto (`{% csrf_token %}` dentro de um `<form>` escondido) para o JavaScript ler — o cookie `csrftoken` deste projeto é `HTTPONLY` (decisão de segurança já existente), então não dá para lê-lo via `document.cookie` no JS; o valor precisa vir de um campo, e é isso que o script faz.

A lista de motivos de perda ativos é embutida via `json_script` (mecanismo seguro do próprio Django contra XSS — nunca interpolação crua).

### 2.4 `static/crm/kanban.js` (novo)

JavaScript puro (sem lib nova — mesma convenção do resto do projeto), usando a API nativa de Drag and Drop do HTML5. Fluxo:

1. Ao soltar um card numa coluna diferente da atual, o script decide: se a coluna de destino é uma etapa de **perda** (`is_lost`), abre um modal pedindo o motivo (campo obrigatório — a mesma regra que já existe no backend); caso contrário, envia a mudança direto.
2. **Nunca move o card na tela antes da confirmação do backend** — o `fetch()` é sempre enviado primeiro; só em caso de sucesso o card é de fato movido de coluna e os totais das duas colunas (origem e destino) são atualizados com os números que o próprio backend devolveu. Em caso de erro (ex.: outra pessoa já mudou a etapa dessa oportunidade, ou a etapa de destino foi desativada nesse meio tempo), o card permanece onde estava e um aviso aparece na tela.
3. Os filtros ativos no momento do arraste (a querystring da própria URL do Kanban) são enviados junto na URL do `POST`, para que os totais devolvidos pelo backend reflitam os mesmos filtros que você está vendo na tela.

### 2.5 `templates/_design_tokens.html`

Componentes CSS novos, todos dentro do `@layer components` já existente (mesmo arquivo compartilhado entre a aplicação interna e a landing pública) e seguindo os tokens de marca já definidos (`brand-black`/`brand-charcoal`/`brand-gold`) — nenhuma cor nova. Famílias de classe: `.kanban-board`/`.kanban-column-*`/`.kanban-card-*` (o quadro em si) e `.kanban-modal-*` (o modal de motivo de perda, com a mesma estrutura de `.label-theme-modal-*` já usado no modal de tema claro/escuro das etiquetas, mas como família própria — semântica diferente).

## 3. O que foi deliberadamente reduzido de escopo

- **Nenhum modal ao arrastar para uma etapa de ganho.** O backend aceita `closed_value` opcional ao marcar como ganha, mas capturar esse valor no meio do arraste (com um segundo modal) não estava nas 3 decisões confirmadas e foi tratado como escopo futuro — hoje, arrastar para "Ganho" move a oportunidade sem valor de fechamento definido (fica `None`, igual a hoje quando não informado), e o valor pode continuar sendo definido pela tela de detalhe (`crm:opportunity_detail`, formulário "Mudar etapa" já existente, que continua funcionando exatamente como antes).
- **Filtros de Responsável e Cliente não ganharam campo na tela** — o backend já os suportava (e continua suportando, no `_filtered_opportunities_queryset`), mas eles nunca tiveram um `<select>` na listagem antiga; a decisão 3 foi manter os filtros que **já existiam na tela**, não os que o backend aceitava silenciosamente.
- **Sem alternativa "empilhada" para mobile.** Diferente de outras listagens do sistema (que viram cards empilhados abaixo de `sm:`), um Kanban não tem uma variante mobile sensata que não seja a rolagem horizontal — é a própria estrutura pedida ("organização horizontal das etapas"), então o quadro rola horizontalmente em qualquer tamanho de tela.
- **Sem "carregar mais" por coluna.** Todas as oportunidades do filtro corrente aparecem de uma vez, agrupadas por etapa (paginação não é um conceito que existe num funil). Em volume muito grande isso pode significar uma coluna com scroll interno longo.
- **Arraste é só por mouse/touch (API nativa HTML5 Drag and Drop)** — sem um caminho alternativo por teclado nesta rodada. Quem não tem a permissão de mudar etapa não vê os cards como arrastáveis (e o próprio script de arraste sequer é carregado na página nesse caso).

Nenhuma dessas reduções envolveu decisão de produto ambígua — são todas consequência direta das 3 decisões já confirmadas com você.

## 4. Segurança e integridade — nada mudou na regra, só no transporte

- Mesma dupla permissão de sempre no endpoint de mudança de etapa (`crm.view_opportunities` + `crm.change_opportunity_stage`).
- Mesma função de serviço (`apps.crm.services.change_opportunity_stage`) como único caminho de escrita — com `select_for_update()` (duas mudanças simultâneas na mesma oportunidade continuam serializando, nunca corrompendo estado) e a mesma regra "motivo de perda obrigatório para etapa de perda".
- O formulário HTML normal da ficha da oportunidade (`opportunity_detail.html`) não foi tocado e continua se comportando exatamente como antes (testado explicitamente — ver seção 5).
- Autoescape do Django continua ativo, sem nenhum `|safe` novo; a lista de motivos de perda embutida na página usa `json_script` (mecanismo seguro nativo do Django), não interpolação crua.

## 5. Testes

Arquivo novo: `apps/crm/tests/test_kanban_view.py` (15 testes), cobrindo o que é **novo** nesta rodada (a matriz de permissão genérica de cada ação já é coberta por `test_permission_matrix.py`, e a integridade da transição de etapa em si já é coberta por `test_services.py`/`test_security.py`):

- Agrupamento por etapa ativa, etapa desativada nunca vira coluna.
- Contagem e valor total consolidado por coluna (incluindo o caso "nenhum valor informado" → soma zero, nunca erro).
- Filtros de busca/Origem/Tipo de negócio continuam funcionando; o filtro de Etapa não existe mais na tela.
- Cards só ficam `draggable="true"` para quem tem a permissão de mudar etapa.
- Endpoint AJAX: sucesso (JSON com totais de origem/destino), erro de validação (motivo de perda ausente → 400, sem mudar nada), mesma etapa → 400, sem permissão → 403, e os totais devolvidos respeitando os filtros ativos no momento do arraste.
- O form-POST normal (não-AJAX) continua se comportando exatamente como antes — redirect + `messages`, nunca JSON.

**Resultado da suíte completa** (via `pytest`, que é o executor correto deste projeto — `pytest.ini` aponta para `config.settings.test`, que desliga o `django-axes` só para os testes; rodar com `manage.py test` sem essa configuração de settings gera centenas de falhas espúrias de autenticação, não relacionadas a nenhuma mudança de código):

```
950 passed, 1 failed in ~5min
```

A única falha (`MojibakeRegressionTest.test_no_mojibake_in_tracked_repository_files`) é **pré-existente e não relacionada a este trabalho** — confirmado rodando a mesma suíte no commit anterior (`0fa2f7e`, antes de qualquer mudança desta rodada), onde a mesma falha já ocorre. É um bug no próprio teste: ele varre todos os arquivos rastreados do repositório procurando sequências de mojibake, mas os marcadores que ele procura estão definidos como literais de string dentro do próprio arquivo de teste (`test_i18n_encoding_audit.py`) e citados como exemplo no relatório da auditoria de idioma (`AUDITORIA_IDIOMA_LOCALIZACAO_UTF8.md`) — o teste acaba encontrando a si mesmo. Não mexi nesse teste porque está fora do escopo deste pedido (Kanban), mas fica registrado aqui para você decidir se quer que eu corrija numa próxima rodada (a correção seria simples: excluir os dois arquivos da varredura, ou não usar os marcadores como literais de string diretos no próprio arquivo de teste).

Também rodados e limpos: `python manage.py check` (nenhum problema) e `python manage.py makemigrations --check --dry-run` (nenhuma migration pendente — confirma que nada nesta rodada mexeu em model).

## 6. Arquivos alterados/criados

```
M  apps/core/templatetags/currency.py       (refactor: format_brl() extraída)
M  apps/crm/views.py                        (Kanban + endpoint AJAX)
M  templates/_design_tokens.html            (componentes .kanban-*)
M  templates/crm/opportunity_list.html      (reescrita completa — Kanban)
A  static/crm/kanban.js                     (novo)
A  apps/crm/tests/test_kanban_view.py       (novo — 15 testes)
A  RELATORIO_CRM_FUNIL_KANBAN.md            (este relatório)
```

Nenhuma migration nova, nenhum model alterado, nenhuma permissão nova.

## 7. Como testar manualmente

1. Acesse `/crm/oportunidades/` — deve aparecer o funil em colunas (uma por etapa ativa), cada uma com nome, contagem e valor total no cabeçalho.
2. Com um usuário que tenha `crm.change_opportunity_stage`: arraste um card para outra coluna intermediária — deve mover na hora e os dois totais (origem/destino) devem atualizar.
3. Arraste um card para uma coluna de etapa de **perda** — deve abrir o modal pedindo motivo; sem selecionar motivo, "Confirmar perda" deve mostrar erro e não fechar; com motivo selecionado, deve mover e atualizar os totais.
4. Solte um card na própria coluna de origem — nada deve acontecer (sem chamada de rede).
5. Com um usuário que só tenha `crm.view_opportunities` (sem `change_opportunity_stage`): os cards não devem ser arrastáveis (cursor normal, sem efeito de arraste).
6. Filtre por busca/Origem/Tipo de negócio e confirme que só as oportunidades correspondentes aparecem nas colunas certas.
7. Abra a ficha de uma oportunidade (`/crm/oportunidades/<id>/`) e use o formulário "Mudar etapa" de lá (não o Kanban) — deve continuar funcionando exatamente como antes (redirect + mensagem de sucesso/erro).

---

Como de costume, nada foi commitado no controle remoto nem implantado — só commit local, sem `push`/deploy, conforme sua instrução permanente.
