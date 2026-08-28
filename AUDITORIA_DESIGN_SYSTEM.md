# Auditoria visual e funcional da UI — pré-requisito para padronização

**Data:** 28/08/2026
**Natureza:** só auditoria. Nenhum template, form, view, model, migration, service ou permissão foi alterado nesta etapa. Nenhum teste foi rodado a partir de mudanças (não houve mudanças) — a suíte permanece no estado já confirmado (486/486, `check` e `makemigrations --check` limpos).

---

## 1. Inventário dos componentes já existentes em `base.html`

`base.html` (240 linhas) já tem uma biblioteca de componentes centralizada via `@layer components`, construída na etapa da UI de Manutenção/Higienização:

- **Botões:** `.btn` (base), `.btn-primary` (dourado, texto preto), `.btn-secondary` (contorno dourado), `.btn-neutral` (contorno cinza), `.btn-danger` (contorno vermelho), `.btn-sm` (variante compacta).
- **Links:** `.link` (dourado-escuro, sublinhado no hover).
- **Superfícies:** `.card`, `.card-pad` (card + padding responsivo).
- **Cabeçalho de página:** `.page-header`, `.page-title`, `.page-subtitle`.
- **Badges de status:** `.badge` (base) + `.badge-success` (verde), `.badge-warning` (âmbar), `.badge-danger` (vermelho), `.badge-info` (azul), `.badge-neutral` (cinza). O dourado é deliberadamente excluído das badges — reservado para marca/ação, nunca para status.
- **Formulários:** `.field-label`, `.field-hint`, `.field-error`, `.field-input` (input/select/textarea), `.filter-input` (variante compacta para barras de filtro).
- **Tabelas:** `.table-wrap`, `.table-base` (+ regras de thead/th/td/hover de linha).
- **Estado vazio:** `.empty-state`.
- **Timeline:** `.timeline-item`.
- **Alertas (`django.contrib.messages`):** `.alert`, `.alert-success`, `.alert-error`, `.alert-warning`, `.alert-info` — já aplicados **globalmente**, porque o loop de mensagens está no próprio `base.html`. Ou seja: todas as telas do sistema, antigas ou novas, já herdam esse componente sem nenhuma ação adicional.
- **Cores de marca:** `brand.black` (#0a0a0a), `brand.charcoal` (#171717), `brand.gold` (#eab308), `brand.gold-dark` (#b45309), `brand.gold-light` (#fef3c7), extraídas do site institucional e ajustadas para contraste em uso administrativo prolongado (comentário já documentado no próprio arquivo).
- **Estrutura global:** cabeçalho preto/dourado com navegação (agora incluindo "Manutenções"/"Higienizações"), menu mobile via `#nav-toggle` (JS vanilla, sem framework novo), rodapé, `<main>` com largura máxima `max-w-6xl`.

## 2. Quais telas já seguem o novo padrão

Apenas as **10 telas de `templates/maintenance/`** (Manutenção/Higienização) usam as classes do design system. Contei ocorrências reais nesses arquivos: 20× `field-label`, 18× `field-error`, 13× `link`, 9× `page-title`/`page-subtitle`, 8× `card-pad`, 7× `btn-neutral`, 6× `btn-primary`, 4× `btn-danger`, badges (`badge-success`, `badge-neutral`, `badge-warning`), `table-wrap`/`table-base`, `empty-state`, `alert-error`/`alert-warning`. As únicas classes "fora do catálogo" nesses arquivos são utilitárias de layout puro (`flex`, `grid`, `gap-*`, `mt-4`) — o que é esperado e correto, não é duplicação de componente.

Todas as demais telas (ver seção 3) usam **zero** classes do design system — confirmei isso varrendo cada pasta de app por qualquer uma das classes centrais (`btn-primary`, `card-pad`, `page-header`, `badge-success`, `field-label`, `table-wrap`): 0 de 38 arquivos correspondem.

*Exceção parcial:* `templates/equipment/detail_private.html` foi tocado nesta última etapa (para adicionar as ações "Abrir manutenção"/"Registrar higienização" e a seção-resumo), mas propositalmente usando as classes ad hoc antigas (`bg-white border border-gray-200 rounded-lg p-4`, `text-blue-600 hover:underline`) para não misturar dois padrões visuais na mesma página no meio da entrega anterior. É a primeira tela candidata natural a uma migração completa.

## 3. Quais telas ainda usam padrões antigos

Todas as 38 telas fora de `maintenance/`, por app:

- **accounts (7):** `login.html`, `password_reset*.html` (4 telas), `user_form.html`, `user_list.html`.
- **catalog (4):** `category_list.html`, `category_form.html`, `model_list.html`, `model_form.html`.
- **clients (5):** `client_list.html`, `client_detail.html`, `client_form.html`, `client_update_form.html`, `client_fiscal_address_form.html`.
- **equipment (14):** `list.html`, `detail_private.html`, `detail_public.html`, `equipment_form.html`, `batch_create.html`, `batch_confirm.html`, `batch_result.html`, `change_status.html`, `change_condition.html`, `reclassify.html`, `supersede.html`, `import_upload.html`, `import_review.html`, `import_summary.html`.
- **operations (7):** `location_list.html`, `location_detail.html`, `location_form.html`, `location_update_form.html`, `location_address_form.html`, `movement_form.html`, `duplicate_locations_report.html`.
- **qrcodes (1):** `label.html` (é um template de impressão/PDF — tratamento à parte, ver seção 9).

## 4. Inconsistências encontradas

Levantamento quantitativo direto no HTML (`grep` nas 38 telas antigas):

| Padrão | O que existe hoje | Ocorrências |
|---|---|---|
| Botão primário | `bg-blue-600 ... hover:bg-blue-700` (azul) em vez de `.btn-primary` (dourado) | 29 lugares com `bg-blue-600`, 29 com `bg-blue-700` (hover) |
| Links | `text-blue-600 hover:underline` em vez de `.link` | 54 ocorrências de `text-blue-600` |
| Botão de filtro | **Três variações diferentes** para a mesma função: `bg-gray-800 text-white` (Equipamentos), `bg-gray-100 border ... hover:bg-gray-200` (Unidades), e nenhum botão de filtro em Clientes (busca dispara só no submit do form, sem botão visível) | inconsistência estrutural, não só de cor |
| Badges de status | Só existem de fato (pílula colorida) nas telas de Manutenção/Higienização. Em Equipamentos, status/condição aparecem como **texto puro**, sem cor alguma (`{{ equipment.get_status_display }}` cru, em `list.html` e `detail_private.html`). Em Modelos, ativo/inativo usa `<span class="text-green-700">`/`<span class="text-gray-400">` — texto colorido, não badge | 0 badges reais fora de `maintenance/` |
| Inputs/selects | Toda a base usa uma constante Python `TEXT_INPUT_CLASS = "border border-gray-300 rounded-md px-3 py-1.5 text-sm w-full"`, **duplicada literalmente em 6 arquivos** (`apps/core/forms.py`, `apps/accounts/forms.py`, `apps/equipment/forms.py`, `apps/clients/forms.py`, `apps/operations/forms.py`, `apps/catalog/forms.py`) em vez do `.field-input` centralizado | 6 duplicações do mesmo literal |
| Tabelas | Estrutura idêntica em todo lugar (`bg-white border border-gray-200 rounded-lg overflow-hidden` + `<table class="w-full text-sm">` + `thead.bg-gray-100`) — já é visualmente "quase" `.table-wrap`/`.table-base`, só falta trocar as classes | alta uniformidade = migração de baixo risco |
| Cards/formulários | Mesmo padrão em 100% dos formulários antigos: `bg-white border border-gray-200 rounded-lg p-6 max-w-lg space-y-4` — idêntico em `equipment_form`, `batch_create`, `change_status`, `change_condition`, `movement_form`, `client_form`, `location_form`, `user_form`, `category_form`, `model_form` | alta uniformidade = migração de baixo risco |
| Paginação | **Dois mecanismos diferentes**: `equipment/list.html` já usa `{% load pagination_tags %}` + `url_replace` (mecanismo genérico corrigido em etapa anterior). `clients/client_list.html` ainda monta a querystring manualmente (`?page=N&q=...`), que silenciosamente perderia qualquer filtro futuro além de `q`. Demais telas com listagem (Unidades, Categorias, Modelos, Usuários) **não paginam** | risco funcional latente em `client_list.html`, não só visual |
| Estados vazios | Linha de tabela com `<td class="px-3 py-4 text-gray-500">` em vez de `.empty-state` — mesma ideia, classe diferente | uniforme, baixo risco |
| Mensagens (`django.contrib.messages`) | **Já unificado** — o bloco de mensagens vive só em `base.html`, então toda tela já herda `.alert-*` automaticamente, sem trabalho adicional | 0 inconsistência |
| Ações destrutivas | Não existe hard delete em nenhuma tela antiga (confirmei: nenhuma ocorrência de "Excluir"/"Remover"/"Deletar" em todo `templates/`). O que existe como "Cancelar" nos formulários antigos é sempre **navegação de saída** (link cinza discreto para voltar), não uma ação destrutiva — padrão correto, só precisa manter a cor neutra. As únicas ações destrutivas reais (cancelar Manutenção/Higienização) já usam `.btn-danger` + confirmação explícita, feitas na etapa anterior | sem risco, já correto |
| Título de página | `<h1 class="text-xl font-semibold">` (antigo) vs `.page-title` = `text-xl sm:text-2xl font-bold tracking-tight text-brand-charcoal` (novo, maior e com a cor de marca) | inconsistência de hierarquia tipográfica |
| Estilos inline | **Nenhum** `style="..."` em nenhuma das 47 templates — checei explicitamente | positivo, nenhum risco aqui |

## 5. Proposta do design system final

Adotar exatamente a direção que você descreveu, formalizando como regra:

- **Dourado (`.btn-primary`)** — a única ação primária por tela (criar, salvar, confirmar, registrar). Nunca mais de uma por tela.
- **Preto/chumbo** — não como botão preenchido (ficaria pesado demais repetido em várias telas), mas como acento de identidade: cabeçalho, títulos (`.page-title` já usa `text-brand-charcoal`), foco em inputs. Para ações secundárias "importantes" (ex.: "Editar dados", "Reclassificar modelo"), proponho `.btn-secondary` (contorno dourado) ou `.btn-neutral` (contorno cinza) — dourado sólido reservado só à ação primária evita "tudo dourado".
- **Azul** — restrito a `badge-info` (status neutro/informativo) e, quando fizer sentido, links de navegação contextual dentro de conteúdo (ex.: um link para outro registro dentro de uma célula de tabela) — mas como `.link` (dourado) já cobre esse caso no padrão novo, minha recomendação é **não reintroduzir azul como cor de link geral**; reservá-lo só para badges informativos e, se necessário, para estados de foco/seleção que não usam dourado (ex.: um item já selecionado numa lista).
- **Vermelho** — só `.btn-danger`, `.badge-danger`, `.alert-error`, `.field-error`. Nunca decorativo.
- **Verde** — só `.badge-success`, `.alert-success`. Mesmo critério.
- **Badges por domínio** — proponho fixar o mapeamento semântico (não é código ainda, é a convenção a aprovar):
  - Equipamento: DISPONÍVEL → `badge-success`; EM_OPERACAO → `badge-info`; MANUTENÇÃO → `badge-warning`; INATIVO/BAIXADO → `badge-neutral`.
  - Condição: BOM → `badge-success`; REGULAR → `badge-warning`; RUIM → `badge-danger`.
  - Modelo ativo/inativo: ativo → `badge-success`; inativo → `badge-neutral`.
  - (Manutenção/Higienização já têm seu mapeamento definido na etapa anterior — não muda.)
- **Tabelas e formulários** — mesma receita já usada em `maintenance/`: `.table-wrap`/`.table-base` para listagens, `.card-pad` + `.field-label`/`.field-input`/`.field-error` para formulários, sem inventar nada novo.
- **Consistência mobile** — já resolvida estruturalmente pelo `#nav-toggle` global; a única atenção adicional na migração é confirmar que tabelas largas (ex.: Equipamentos com coluna QR) mantêm `overflow-x-auto` (já é o comportamento de `.table-wrap`) em vez de forçar layout de cards no mobile.

## 6. Proposta específica para a tela de Equipamentos

Equipamentos é o maior e mais crítico conjunto (14 templates). Tratamento proposto, tela a tela, preservando 100% das URLs/comportamentos/permissões atuais:

- **`list.html`:** trocar contêiner da tabela para `.table-wrap`/`.table-base`; botão "Filtrar" (hoje `bg-gray-800`) vira `.btn-neutral` (ele não é a ação primária da tela); "Novo equipamento" (hoje azul) vira `.btn-primary`; os 5 links de exportação/lote (hoje `text-blue-600`) viram `.link`; adicionar `.badge-*` para Status e Condição nas colunas correspondentes (hoje texto puro) — essa é a mudança de maior impacto de usabilidade, exatamente o "status rapidamente identificável" que você já pediu para Manutenção; célula vazia vira `.empty-state`. Busca e os 5 selects de filtro viram `.filter-input`. Paginação mantém `url_replace` (já correto), só troca a cor dos links "Anterior/Próxima" para `.link`.
- **`detail_private.html`:** trocar o card de dados para `.card-pad`; título vira `.page-title`; Status e Condição no `<dl>` ganham `.badge-*`; as 3 barras de ações (movimentar/alterar status/alterar condição/manutenção/higienização/editar/reclassificar/reemitir, QR/etiqueta) viram `.link`, com "Reemitir patrimônio" mantendo `text-red-600` → mapeando para uma variação de `.link` em tom de alerta (a definir — é uma ação sensível mas não destrutiva no sentido de excluir dado, é reemissão; proponho manter vermelho mas não como `.btn-danger`, já que não é um POST direto com confirmação, é navegação para uma tela própria com sua própria confirmação). A seção "Manutenção e higienização" e o histórico já têm estrutura pronta — só trocam as classes de cor/link.
- **`detail_public.html`:** é a única tela pública autenticada-opcional (acesso por QR sem login). Proponho tratamento mínimo: manter simples e central como está, só trocar `bg-blue-600` do botão "Entrar para ver mais detalhes" por `.btn-primary` e o card por `.card-pad`. Não adicionar navegação/nav bar aqui — ela já não aparece para anônimo, o que está certo.
- **`equipment_form.html`, `change_status.html`, `change_condition.html`, `reclassify.html`, `supersede.html`, `batch_create.html`:** todos compartilham o mesmo esqueleto (card + campos + botão primário + link "Cancelar" cinza). Migração mecânica: card vira `.card-pad`, botão de submit vira `.btn-primary`, "Cancelar" vira `.btn-neutral` ou mantém como link simples cinza (a definir — ver seção 11), erros de campo/form usam `.field-error`.
- **`batch_confirm.html`, `batch_result.html`, `import_upload.html`, `import_review.html`, `import_summary.html`:** ainda não lidos linha a linha nesta auditoria (não são o foco imediato pedido — "tela de Equipamentos" no sentido de lista/detalhe/criação — mas seguem o mesmo padrão estrutural das demais telas de formulário/tabela da mesma app, então a migração é do mesmo tipo).

Nada disso remove ou reordena busca, filtros, paginação, exportações, criação individual, criação em lote, QR, etiquetas — só troca a camada visual por cima do que já existe.

## 7. Ordem recomendada de migração

Critério: baixo risco primeiro (poucas telas, sem paginação/JS complexo), maior visibilidade por último dentro de cada grupo, e aproveitar o ponto de alavancagem centralizado (`TEXT_INPUT_CLASS`) antes de tocar template por template.

1. **`apps/*/forms.py` — trocar `TEXT_INPUT_CLASS` por `"field-input"` nos 6 arquivos.** Isso já corrige a aparência de praticamente todo input/select/textarea do sistema de uma vez, sem tocar em nenhum template.
2. **`accounts/login.html`** (tela mais vista, isolada, sem nav, sem paginação) — bom piloto de validação rápida.
3. **Telas de formulário simples e isoladas:** `change_status.html`, `change_condition.html`, `reclassify.html`, `supersede.html`, `equipment_form.html`, `batch_create.html`, `user_form.html`, `category_form.html`, `model_form.html`, `client_form.html`, `client_update_form.html`, `client_fiscal_address_form.html`, `location_form.html`, `location_update_form.html`, `location_address_form.html`, `movement_form.html` — mesmo esqueleto, risco baixo, alto volume de telas resolvidas de uma vez.
4. **Listagens sem paginação:** `category_list.html`, `model_list.html`, `location_list.html`, `user_list.html` — trocar tabela/badge/botão de filtro, sem mexer em lógica.
5. **`equipment/detail_private.html` e `detail_public.html`** — maior visibilidade operacional, badges de status/condição entram aqui.
6. **`equipment/list.html` e `clients/client_list.html`** — as duas telas com paginação; aproveitar `client_list.html` para também resolver o mecanismo de querystring manual (decisão a aprovar, ver seção 11).
7. **Telas de fluxo mais longo/específico:** `batch_confirm.html`, `batch_result.html`, `import_upload.html`, `import_review.html`, `import_summary.html`, `operations/location_detail.html`, `operations/duplicate_locations_report.html` (essa já foi tocada indiretamente e tem os 2 testes sensíveis a markup — mexer nela por último e com atenção).
8. **`qrcodes/label.html`** — tratamento à parte (ver seção 9), não necessariamente no mesmo ritmo das telas de UI interativa.

## 8. Arquivos que seriam alterados numa padronização completa

- `apps/core/forms.py`, `apps/accounts/forms.py`, `apps/equipment/forms.py`, `apps/clients/forms.py`, `apps/operations/forms.py`, `apps/catalog/forms.py` (só a constante `TEXT_INPUT_CLASS`).
- Os 38 templates listados na seção 3 (trocas de classe, sem alterar `{% url %}`, nomes de campo, `name=`/`id=` de formulário, ou qualquer tag Django).
- Nenhuma alteração prevista em `apps/*/views.py`, `apps/*/models.py`, `apps/*/services.py`, `apps/*/urls.py`, nem em `apps/*/migrations/`.

## 9. Riscos de regressão

- **Baixo, estrutural:** a uniformidade quase total do HTML atual (mesmo esqueleto de card/tabela/formulário repetido em quase todas as 38 telas) torna a migração mecânica — trocar classe por classe, não reescrever estrutura. Isso reduz bastante o risco de quebrar comportamento.
- **Testes de markup:** só um arquivo de teste (`apps/operations/tests/test_duplicate_locations_report.py`) já se mostrou sensível a mudanças estruturais globais (contagem de `<button`, de `<form`) — qualquer novo elemento estrutural adicionado a `base.html` ou àquela tela específica pode exigir ajuste nesse arquivo de novo (é o mesmo padrão do ajuste já feito na etapa anterior, não um problema novo).
- **`qrcodes/label.html`:** é renderizado para geração de PDF de etiqueta (`weasyprint` ou equivalente, a confirmar), não só para navegador — Tailwind via CDN pode não se comportar da mesma forma nesse pipeline de renderização. Recomendo tratar esse arquivo separadamente e testar a geração real do PDF antes de aplicar qualquer classe nova ali, para não quebrar a etiqueta física impressa.
- **`clients/client_list.html`:** se a paginação for corrigida para usar `url_replace` (ver seção 11), isso é uma mudança de comportamento (ainda que uma correção), não puramente visual — por isso está listada como decisão a aprovar, não como parte automática da padronização visual.
- **Nenhum risco identificado** para regras de permissão, domínio, ou dados — nenhuma dessas mudanças propostas toca em `views.py`/`services.py`/`forms.py` além da constante de estilo de input.

## 10. Testes provavelmente afetados

- `apps/operations/tests/test_duplicate_locations_report.py` — os dois testes já ajustados na etapa anterior (`content.count("<button")` e a checagem de `bg-red-100` restrita a `<main`) podem precisar de nova revisão se a padronização adicionar/remover elementos estruturais naquela tela especificamente.
- Não encontrei, em uma varredura de todos os arquivos em `apps/*/tests/*.py`, nenhum outro teste que faça `assertContains`/`assertNotContains` sobre uma classe CSS, cor, ou string de estilo — a suíte inteira testa comportamento (status HTTP, contexto, contagem de registros, redirecionamentos, presença de texto visível como labels/mensagens), não markup visual. Isso é uma boa notícia: a padronização visual, por si só, não deveria quebrar a suíte.
- Ainda assim, qualquer teste que faça `assertContains(response, "texto exato do botão")` (ex.: o texto "Filtrar", "Novo equipamento") continua seguro, porque a padronização não muda o texto visível, só a classe.

## 11. Decisões que precisam da sua aprovação antes de eu implementar

1. **Botão de filtro:** confirmar que a padronização é `.btn-neutral` para todos os botões de "Filtrar" (Equipamentos, Unidades) — ele deixa de ser escuro/preto (`bg-gray-800`) e passa a ser neutro cinza, já que o dourado fica reservado à ação primária da tela.
2. **Link "Cancelar" em formulários:** manter como link de texto cinza discreto (padrão atual, sem virar `.btn-neutral`) ou padronizar como `.btn-neutral` de fato (mais visível, mais peso visual num botão que não é a ação principal)? As telas de Manutenção/Higienização já usam `.btn-neutral` para isso — recomendo o mesmo aqui por consistência, mas é uma escolha de peso visual, não só de cor.
3. **"Reemitir patrimônio" (ação sensível, `equipment/detail_private.html`):** confirmar que o tratamento fica como um link vermelho de navegação (não um botão com confirmação inline), já que a tela de destino tem sua própria confirmação — ou se você prefere elevar isso visualmente a algo mais parecido com as ações de cancelamento de Manutenção.
4. **`clients/client_list.html` — paginação manual:** essa é uma mudança funcional (não visual) que encontrei de bônus durante a auditoria: o link de página usa querystring construída manualmente em vez do `url_replace` genérico, então qualquer filtro futuro além de `q` seria perdido ao paginar. Não é bug ativo hoje (só existe o filtro `q`), mas é o mesmo problema que já foi corrigido uma vez em `equipment/list.html`. Aprova eu corrigir isso *dentro* desta etapa de padronização (já que estou mexendo no arquivo de qualquer forma), ou prefere tratar como um item separado?
5. **Badges de Status/Condição em Equipamentos:** aprovar especificamente o mapeamento de cores proposto na seção 5 (DISPONÍVEL=verde, EM_OPERACAO=azul, MANUTENÇÃO=âmbar, INATIVO=cinza; BOM=verde, REGULAR=âmbar, RUIM=vermelho) — é a mudança de maior impacto visual/usabilidade da rodada e não existe hoje em nenhuma tela.
6. **`qrcodes/label.html`:** confirmar se você quer essa tela dentro do escopo da padronização agora, ou tratada à parte depois — pelo motivo técnico da seção 9 (pipeline de geração de PDF, não só navegador).
7. **`TEXT_INPUT_CLASS` centralizada:** aprovar a mudança de ponto único nos 6 arquivos `forms.py` como primeiro passo da migração (item 1 da ordem recomendada) — é a intervenção de maior alavancagem/menor risco de toda a proposta.

---

Aguardando sua aprovação item a item (ou aprovação geral) antes de alterar qualquer template ou arquivo `forms.py`.
