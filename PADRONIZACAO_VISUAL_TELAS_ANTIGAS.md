# Padronização visual das telas antigas — Relatório de entrega

**Data:** 28/08/2026
**Escopo:** aplicar o design system (definido em `base.html` na etapa da UI de Manutenção/Higienização) às 38 telas antigas identificadas na auditoria aprovada, seguindo à risca as 7 decisões e a ordem de migração ali propostas. Nenhuma regra de negócio, model, migration, permissão ou contrato de view foi alterada — a única exceção combinada é a correção de paginação de `clients/client_list.html`, explicitamente aprovada.

---

## 1. Arquivos alterados

**Centralização de estilo de input (6 arquivos, só a constante):**
`apps/core/forms.py`, `apps/accounts/forms.py`, `apps/equipment/forms.py`, `apps/clients/forms.py`, `apps/operations/forms.py`, `apps/catalog/forms.py` — `TEXT_INPUT_CLASS` trocado do literal Tailwind antigo para `"field-input"`.

**37 templates migrados** (nenhum outro arquivo de template foi tocado; `qrcodes/label.html` permanece intocado, conforme decisão 6):

- `accounts/`: `login.html`, `password_reset.html`, `password_reset_done.html`, `password_reset_confirm.html`, `password_reset_complete.html`, `user_form.html`, `user_list.html`.
- `catalog/`: `category_list.html`, `category_form.html`, `model_list.html`, `model_form.html`.
- `clients/`: `client_list.html`, `client_detail.html`, `client_form.html`, `client_update_form.html`, `client_fiscal_address_form.html`.
- `equipment/`: `list.html`, `detail_private.html`, `detail_public.html`, `equipment_form.html`, `batch_create.html`, `batch_confirm.html`, `batch_result.html`, `change_status.html`, `change_condition.html`, `reclassify.html`, `supersede.html`, `import_upload.html`, `import_review.html`, `import_summary.html`.
- `operations/`: `location_list.html`, `location_detail.html`, `location_form.html`, `location_update_form.html`, `location_address_form.html`, `movement_form.html`, `duplicate_locations_report.html`.

**Testes:** `apps/clients/tests/test_client_list_pagination.py` (novo — 2 testes cobrindo a correção de paginação).

## 2. Componentes reutilizados

Nenhuma classe nova foi criada em `base.html` — a padronização usou exclusivamente o catálogo já existente: `.btn-primary`, `.btn-neutral`, `.btn-danger`, `.btn-sm`, `.link`, `.card`/`.card-pad`, `.page-header`/`.page-title`/`.page-subtitle`, `.badge-success`/`.badge-warning`/`.badge-danger`/`.badge-info`/`.badge-neutral`, `.field-label`/`.field-hint`/`.field-error`/`.field-input`/`.filter-input`, `.table-wrap`/`.table-base`, `.empty-state`, `.timeline-item`, `.alert-*`. Nos poucos lugares sem componente equivalente (ex.: o link vermelho "Reemitir patrimônio", o destaque âmbar de linhas com pendência na revisão de importação), mantive CSS ad hoc mínimo e documentado, exatamente como a instrução pedia.

## 3. Telas migradas

Todas as 38 telas da auditoria, na ordem aprovada:

1. **Centralização de inputs** — `TEXT_INPUT_CLASS` nos 6 `forms.py`.
2. **Login e autenticação** — `login.html`, os 4 templates de redefinição de senha. Como `AuthenticationForm`/`PasswordResetForm`/`SetPasswordForm` são forms nativos do Django (sem `forms.py` próprio no projeto), apliquei a classe `field-input` diretamente nesses 5 campos via HTML explícito no template (mesmo `name`/`id`/`value` que o Django geraria), sem criar nenhum form novo — mantém a mudança 100% dentro do template, sem tocar em backend.
3. **Formulários simples** — as 16 telas de card+campos+botão: `change_status`, `change_condition`, `reclassify`, `supersede`, `equipment_form`, `batch_create`, `user_form`, `category_form`, `model_form`, `client_form`, `client_update_form`, `client_fiscal_address_form`, `location_form`, `location_update_form`, `location_address_form`, `movement_form`.
4. **Listagens simples** — `category_list`, `model_list` (badges Ativo/Inativo), `location_list`, `user_list` (badge Ativo/Inativo).
5. **Detalhe de Equipment** — `detail_private.html` e `detail_public.html`, com os badges de Status/Condição.
6. **Lista de Equipment** — `list.html`, a tela de referência (ver seção 5).
7. **Lista de Clients** — `client_list.html`, com a correção de paginação (ver seção 4).
8. **Fluxos longos** — `batch_confirm`, `batch_result`, `import_upload`, `import_review`, `import_summary`.
9. **Diagnóstico somente-leitura** — `client_detail`, `location_detail`, `duplicate_locations_report` (os dois badges "COM/SEM REFERÊNCIAS" agora usam `.badge-danger`/`.badge-success` em vez de utilitário Tailwind cru).

## 4. Ajustes de paginação

`clients/client_list.html` construía os links "Anterior"/"Próxima" manualmente (`?page=N&q=...`), conhecendo só o parâmetro `q` — qualquer filtro futuro além desse seria perdido ao trocar de página. Troquei pelo mesmo mecanismo genérico já usado em `equipment/list.html` e em `maintenance/*_list.html`: `{% load pagination_tags %}` + `{% url_replace request 'page' N %}`, que preserva toda a querystring atual sem precisar conhecer nomes de parâmetro específicos.

Teste novo (`apps/clients/tests/test_client_list_pagination.py`, 2 testes): confirma que o link de "Próxima" preserva o filtro `q` entre páginas, e que `url_replace` preserva **qualquer** parâmetro GET presente na URL (não só `q`) — provando a generalidade da correção, não apenas o caso já existente.

## 5. Equipamentos como tela de referência

`equipment/list.html` agora tem: uma única ação primária dourada ("Novo equipamento"), botão "Filtrar" neutro (não compete mais com a ação primária), tabela em `.table-wrap`/`.table-base`, badges de Status (Disponível=verde, Em operação=azul, Manutenção=âmbar, Inativo=cinza) e Condição (Bom=verde, Médio=âmbar, Ruim/Inutilizável=vermelho) — a mudança de maior impacto de legibilidade da rodada, porque não existia nenhuma cor de status antes. Ações secundárias (lote, exportações, QR, etiquetas) ficaram como links dourados discretos, sem competir visualmente com a ação primária. Nenhuma URL, filtro, busca, paginação, exportação, criação individual/em lote, QR ou etiqueta foi alterada — só a camada visual por cima do que já existia. A mesma paleta de badges foi replicada em `detail_private.html` para manter a mesma leitura de status em toda a jornada do equipamento.

## 6. Impactos indiretos

- Como o `.alert-*` de mensagens do sistema já vivia só em `base.html`, ele já cobria todas as telas automaticamente desde a fase anterior — nenhuma mudança adicional necessária aqui.
- `duplicate_locations_report.html`: troquei os badges `bg-red-100`/`bg-green-100` crus por `.badge-danger`/`.badge-success`. Isso reforça (não enfraquece) a intenção original do teste `test_duplicate_group_renders_required_fields_and_sem_referencias_marker`, que já verificava a ausência da string `bg-red-100` dentro de `<main>` — antes essa string podia legitimamente aparecer ali vinda do badge cru desta própria tela; agora só aparece na definição do componente, no `<head>`. Não precisei alterar esse teste.
- `test_page_exposes_no_destructive_action` (mesmo arquivo) continua correto sem alteração: a tela de diagnóstico não ganhou nenhum `<button>` próprio — a contagem de 2 (`Sair` + o toggle de menu mobile do cabeçalho) permanece válida.
- Nenhum outro teste precisou de ajuste. Uma varredura completa da suíte por asserções sensíveis a classe CSS/cor (`assertContains`/`assertNotContains` com strings de estilo) não encontrou nenhuma outra ocorrência além das duas já citadas — a suíte inteira testa comportamento (status HTTP, contexto, contagem de registros, texto visível), não markup visual, então a padronização não teve efeito colateral em nenhum outro teste.

## 7. Responsividade

Validado com capturas de tela via Playwright headless em três larguras: 1366px (notebook/desktop), 834px (tablet) e 390px (mobile), nas telas de Login, Equipamentos (lista e detalhe), Clientes e Unidades — todas responderam HTTP 200, sem erros de renderização, com o conteúdo presente e legível em todas as larguras, e o menu mobile abrindo corretamente. Nenhuma tabela foi convertida em cards; onde a tabela é larga (ex.: Equipamentos com coluna QR), o comportamento já herdado de `.table-wrap` é `overflow-x-auto` — scroll horizontal consciente, como pedido, em vez de forçar um layout alternativo.

**Mesma limitação já registrada na entrega anterior:** este sandbox de desenvolvimento bloqueia a saída de rede para `cdn.tailwindcss.com` (confirmado via `curl`, retorna 403 no proxy da sandbox), então as capturas de tela aqui mostram o HTML estruturalmente correto (badges como `<span>` com o texto certo por linha, campos de formulário corretos, links corretos) mas sem o CSS do Tailwind aplicado — nem cores, nem espaçamento. Confirmei por leitura direta do HTML servido que todas as classes novas (`badge-*`, `btn-*`, `field-*`, `table-*` etc.) estão corretas e presentes no markup gerado. Em qualquer ambiente com acesso normal à internet — incluindo o Render — o CDN carrega normalmente. A confirmação visual final (cores, espaçamento) depende do checklist manual abaixo.

## 8. Testes

- **Suíte completa:** 488/488 testes passando (486 já existentes + 2 novos de paginação de Clientes), rodada contra PostgreSQL real.
- **`manage.py check`:** nenhum problema identificado.
- **`manage.py makemigrations --check --dry-run`:** nenhuma mudança pendente — confirma que nada nesta etapa tocou em `models.py`.
- **Nenhum teste existente foi enfraquecido** — nenhuma asserção de comportamento foi removida ou relaxada para acomodar a mudança visual; os únicos dois testes sensíveis a markup (`test_duplicate_locations_report.py`) permaneceram passando sem alteração, pelos motivos explicados na seção 6.

## 9. Checklist visual para validação manual no Render

1. Login: campos de usuário/senha com o mesmo visual dos demais formulários do sistema (borda, foco dourado).
2. Equipamentos → lista: badges coloridos de Status e Condição em cada linha; botão "Novo equipamento" dourado; botão "Filtrar" neutro (cinza); busca e os 4 selects de filtro num único estilo; paginação preservando filtros ao trocar de página.
3. Equipamentos → detalhe: Status e Condição como badges (não mais texto puro); "Reemitir patrimônio" continua vermelho, mas como link discreto, não botão destrutivo destacado.
4. Equipamentos → editar/criar, alterar status, alterar condição, reclassificar, reemitir patrimônio, adicionar em lote: mesmo padrão de card + campos + botão dourado + "Cancelar" neutro em todos.
5. Equipamentos → importar planilha: linhas com pendência destacadas em âmbar (não mais amarelo puro); confirmar importação com botão dourado.
6. Clientes → lista: paginação testada com um filtro de busca ativo — o filtro deve permanecer na URL ao trocar de página.
7. Clientes → detalhe, editar, endereço fiscal: mesmo padrão visual das demais telas.
8. Unidades → lista, detalhe, formulários: badges/botões/tabela consistentes com Equipamentos.
9. Categorias e Modelos: badge Ativo (verde) / Inativo (cinza) nas listagens.
10. Usuários: mesmo padrão de listagem e formulário; badge Ativo/Inativo.
11. Diagnóstico de Locations duplicadas (Admin): badges "COM REFERÊNCIAS" (vermelho) / "SEM REFERÊNCIAS" (verde) com o novo estilo de pílula.
12. Conferir em mobile (largura estreita): menu hamburger abre/fecha; tabelas largas (ex.: Equipamentos) rolam horizontalmente sem quebrar o layout da página.
13. Conferir em 1366px/tablet: densidade de informação preservada, nada "esticado" como landing page.
14. Confirmar que nenhuma URL, filtro, exportação, criação em lote, importação, QR ou etiqueta parou de funcionar — só a aparência mudou.

## 10. Fora de escopo (confirmado, nada tocado)

`qrcodes/label.html` permanece intocado. Nenhum model, migration, service, regra de domínio ou permissão foi alterado. Nenhuma feature nova foi implementada. Nenhum deploy foi realizado.

## 11. Git

Todas as alterações desta etapa (6 `forms.py`, 37 templates, 1 teste novo, este relatório e o documento de auditoria) serão commitadas juntas nesta entrega, seguindo o padrão já estabelecido nas etapas anteriores.
