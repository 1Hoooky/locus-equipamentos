# Homologação — Iconografia e apresentação de ações

Implementação da estratégia aprovada em `AUDITORIA_ICONOGRAFIA_ACOES.md` (28/08/2026). Nenhuma alteração de modelo, migration, service, regra de domínio, permissão, URL, query, form, lógica HTMX, `SubmissionGuard` ou comportamento de POST — só templates, um novo template tag e componentes CSS do design system. `qrcodes/label.html` não foi tocado.

## 1. Arquivos alterados

**Novos:**
- `apps/core/templatetags/icons.py` — template tag `{% icon %}` com os SVGs vendorizados.
- `apps/core/test_icons_templatetag.py` — 13 testes da tag.
- `AUDITORIA_ICONOGRAFIA_ACOES.md` — auditoria aprovada (já entregue antes desta etapa).

**Design system:**
- `templates/base.html` — componentes `.icon-btn`, `.icon-btn-neutral`, `.icon-btn-danger`, `.icon-inline`, `.action-group`.

**Templates (33 arquivos):**
`equipment/list.html`, `equipment/detail_private.html`, `equipment/equipment_form.html`, `equipment/batch_create.html`, `equipment/change_status.html`, `equipment/change_condition.html`, `equipment/reclassify.html`, `equipment/supersede.html`, `clients/client_list.html`, `clients/client_detail.html`, `clients/client_form.html`, `clients/client_update_form.html`, `clients/client_fiscal_address_form.html`, `operations/location_list.html`, `operations/location_detail.html`, `operations/location_form.html`, `operations/location_update_form.html`, `operations/location_address_form.html`, `operations/movement_form.html`, `catalog/category_list.html`, `catalog/category_form.html`, `catalog/model_list.html`, `catalog/model_form.html`, `accounts/user_list.html`, `accounts/user_form.html`, `maintenance/maintenance_list.html`, `maintenance/maintenance_detail.html`, `maintenance/maintenance_open_form.html`, `maintenance/maintenance_close_form.html`, `maintenance/maintenance_cancel_confirm.html`, `maintenance/cleaning_list.html`, `maintenance/cleaning_detail.html`, `maintenance/cleaning_form.html`, `maintenance/cleaning_cancel_confirm.html`.

**Teste ajustado (markup, não comportamento):**
- `apps/equipment/tests/test_list_pagination_filters.py` — ver seção 7.

Nenhum arquivo de `models.py`, `views.py`, `services.py`, `forms.py`, `urls.py` ou `migrations/` foi tocado.

## 2. Ícones vendorizados (Heroicons, outline, MIT License)

Copiados uma única vez em `apps/core/templatetags/icons.py` (nenhum pacote/CDN externo):

| Ícone | Uso |
|---|---|
| `eye` | "Ver" icon-only em tabelas/listagens |
| `qr-code` | QR Code |
| `tag` | Etiqueta |
| `pencil` | "Editar" icon-only em tabelas |
| `plus` | Botões primários "Novo/Nova X" |
| `wrench` | "Abrir manutenção" |
| `arrow-down-tray` | Exportar/baixar |
| `arrow-left` | "Voltar" e paginação "Anterior" |
| `arrow-right` | Paginação "Próxima" |
| `x-mark` | "Cancelar" (abandono de formulário) |

Só 2 tamanhos: `normal` (20px) e `compact` (16px) — nenhuma variante extra criada.

## 3. Componentes novos do design system

`.icon-btn` / `.icon-btn-neutral` / `.icon-btn-danger` / `.icon-inline` / `.action-group`, reaproveitando foco/borda/radius dos `.btn-*` existentes.

`.icon-btn-primary` **não foi criada**: nenhuma ação primária virou ícone-sozinho nesta rodada (todos os botões primários mantiveram texto, por decisão), então a variante ficaria sem nenhum uso — melhor não criar classe morta.

Área clicável (ajuste pedido na aprovação, diferente da proposta original de 32px): `min-w-[44px] min-h-[44px]` no mobile, `sm:min-w-[36px] sm:min-h-[36px]` a partir de tablet/desktop — sempre via padding, nunca aumentando o SVG.

## 4. Textos substituídos por ícone-só (as 4 categorias aprovadas + extensão da ficha)

Todos com `aria-label` e `title` específicos (nome do registro, nunca genérico), elemento `<a>` real, foco visível herdado de `.icon-btn`:

- **Ver → `eye`**: `clients/client_list.html`, `operations/location_list.html`, e a lista de manutenção/higienização recente em `equipment/detail_private.html` (linha já identifica tipo+status+data — texto seria redundante).
- **Editar → `pencil`**: `catalog/category_list.html`, `catalog/model_list.html`, `accounts/user_list.html`.
- **QR → `qr-code`** e **Etiqueta → `tag`**: coluna QR/Etiqueta de `equipment/list.html`, agrupados num `.action-group`.

Nada além destes casos virou ícone-só — "Editar dados", "Editar endereço", "Editar unidade", "Ver QR Code", "Ver ficha" etc. continuam com texto (não são o "Editar"/"Ver" genérico em tabela que a decisão 3 cobre).

## 5. Ícone + texto (nunca substituindo o texto)

- **Voltar** (`arrow-left`) em 11 telas, mantendo o texto específico de cada link ("Voltar", "Ver categorias").
- **Cancelar** (`x-mark`) em 19 botões `.btn-neutral` de abandono de formulário. Deliberadamente **não** aplicado a "Cancelar manutenção"/"Cancelar registro" (`btn-danger`) — são ações destrutivas de outra natureza (anular um registro, não fechar um formulário); um X ali sugeriria "fechar", não "anular", e a decisão 10 já veta ícone-só em ação destrutiva.
- **Exportar CSV/Excel/QR Codes/Etiquetas** (`arrow-down-tray`) em `equipment/list.html`.
- **Ver QR Code / Baixar QR Code / Baixar etiqueta** (`qr-code`/`arrow-down-tray`) na ficha do equipamento.
- **Abrir manutenção** (`wrench`) nas 3 ocorrências (lista de manutenções, formulário de abertura, ficha do equipamento).
- **Novo/Nova X** (`plus`) nos 6 botões primários de criação (Equipamento, Cliente, Unidade, Categoria, Modelo, Usuário) — extensão consistente do mesmo ícone já aprovado para "Novo equipamento", corrigindo a inconsistência que a auditoria apontou.
- **Paginação** (`arrow-left`/`arrow-right`) nas 4 telas paginadas (Equipamentos, Clientes, Manutenções, Higienizações), texto "Anterior"/"Próxima" sempre visível.

Botões de salvar/confirmar/continuar (Cadastrar, Salvar alterações, Salvar cliente, Continuar, Confirmar e criar N equipamentos, Enviar e analisar, Confirmar importação, Registrar higienização, Concluir manutenção) **não** receberam ícone — nenhum ganha significado extra com um ícone, por decisão.

## 6. Reorganização de `equipment/detail_private.html`

Dois grupos visuais dentro do mesmo card, com um rótulo pequeno acima de cada um — **sem dropdown, sem menu de três pontos, sem clique extra**, todas as ações continuam visíveis ao mesmo tempo:

- **Ações operacionais**: Registrar movimentação, Alterar status, Alterar condição, Abrir manutenção (com ícone), Registrar higienização.
- **Ações administrativas**: Editar dados, Reclassificar modelo, Reemitir patrimônio.

As condições de permissão (`is_operacional_ou_superior` envolvendo tudo, `is_administrativo_ou_superior` e `is_admin` controlando os itens administrativos) são **exatamente as mesmas de antes** — só a divisão em dois blocos visuais com rótulo é nova. "Reemitir patrimônio" continua vermelho, com texto explícito, sem ícone.

## 7. Testes alterados/adicionados

**Novo — `apps/core/test_icons_templatetag.py` (13 testes):** ícone conhecido renderiza o SVG certo; os 2 tamanhos (`normal`/`compact`) são respeitados e um tamanho desconhecido cai para `normal`; `extra_class` é aplicada e escapada (inclusive tentativa de injeção de `<script>`); nome de ícone desconhecido não levanta exceção e vira comentário HTML inofensivo com o nome escapado; todos os ícones vendorizados renderizam sem erro; o SVG sai `aria-hidden`/`focusable="false"` (o nome acessível é sempre do elemento pai); a tag funciona carregada de dentro de um template real, inclusive com nome vindo de variável de contexto.

**Ajustado — `apps/equipment/tests/test_list_pagination_filters.py`:** o helper `_extract_href` localizava o link de paginação por regex exigindo que o texto ("Anterior"/"Próxima") fosse o único conteúdo do `<a>`. Como os links agora têm um ícone SVG junto do texto, o helper foi reescrito para: percorrer cada âncora isoladamente, remover as tags internas (o ícone) do conteúdo, colapsar espaços e comparar o texto visível resultante — sem nunca "vazar" de uma âncora para outra em busca do texto (uma versão ingênua com `.*?` solto fazia exatamente isso e quebrava, foi corrigido antes de fechar a tarefa). Continua testando exatamente a mesma coisa: o `href` do link identificado pelo texto visível. Nenhuma asserção foi enfraquecida — os 8 testes desse arquivo continuam verificando href/querystring, nunca o markup em si.

Busca prévia em toda a suíte (antes de tocar templates) não encontrou nenhum outro teste que dependesse do texto literal "Ver"/"Editar"/"QR"/"Etiqueta" como único conteúdo de uma âncora — os demais testes checam `status_code`, contexto (`response.context[...]`), ou substrings como `"status=ABERTA"`/`"q=Alfa"` dentro do HTML, que continuam presentes e inalterados.

## 8. Totais e checks

- Suíte completa: **501/501 testes passando** (488 já existentes + 13 novos da template tag).
- `python manage.py check`: **0 problemas**.
- `python manage.py makemigrations --check --dry-run`: **nenhuma mudança detectada** (confirma que nada de modelo foi tocado).

## 9. Verificação visual

Playwright (mesma ressalva já conhecida deste sandbox: o proxy de rede bloqueia `cdn.tailwindcss.com`, então os screenshots aqui saem **estruturalmente corretos mas sem estilo/cor** — a mesma limitação documentada nas fases anteriores; a página real, servida com internet normal, herda as cores/toques de `.icon-btn-neutral`/`.link`/`.btn-primary` já validados no design system). Testado em desktop (1366×800), tablet (834×1112) e mobile (390×844) em `equipment/list.html`, `equipment/detail_private.html` e `clients/client_list.html`: HTTP 200 em todas as combinações, ícones e `aria-label`s presentes e corretos (conferido também via requisição HTTP direta, contando `<svg>`s e extraindo todos os `aria-label` renderizados por tela — nenhum "ícone desconhecido" apareceu em nenhuma página).

**Bug pego e corrigido durante esta verificação:** o primeiro rascunho de `equipment/detail_private.html` usava um comentário Django `{# ... #}` de várias linhas para explicar a divisão dos dois grupos — esse comentário Django **não suporta múltiplas linhas** e estava vazando como texto visível na página. Foi trocado por `{% comment %}...{% endcomment %}` (que suporta multi-linha) antes de fechar esta etapa; busca no restante dos templates confirmou que era o único caso. Ficou registrado aqui porque é exatamente o tipo de regressão silenciosa que a suíte automatizada não pega sozinha (nenhum teste afirma a ausência de um texto) — só apareceu ao olhar a página renderizada.

## 10. Riscos de regressão

Baixo. Nenhum `href`, `name`, `id`, atributo `hx-*` ou comportamento de POST mudou — só o conteúdo visual interno de âncoras/botões já existentes, mais a reorganização puramente visual da ficha do equipamento (mesmas condições de permissão). O ponto mais sensível (paginação, por já ter teste específico de markup) foi identificado, ajustado e revalidado antes de tocar qualquer template.

## 11. Checklist manual para o Render (desktop e mobile)

1. Confirmar que os ícones aparecem com a cor certa (cinza neutro nos `.icon-btn-neutral`, dourado nos `.link`) — no sandbox local isso não é visível pelo bloqueio de CDN.
2. `equipment/list.html`: coluna QR/Etiqueta mostra 2 ícones lado a lado por linha, com tooltip (passar o mouse) mostrando "Ver QR Code de LOC-..." e "Baixar etiqueta de LOC-...".
3. `equipment/list.html`: "Novo equipamento" com ícone `+`; os 4 links "Exportar..." com ícone de download.
4. `equipment/detail_private.html`: dois grupos visíveis ("Ações operacionais"/"Ações administrativas") sem nenhum clique extra; "Abrir manutenção" com ícone de chave inglesa.
5. `equipment/detail_private.html`: itens de "Manutenção e higienização" mostram só o ícone de olho no lugar de "Ver" — passar o mouse deve mostrar o tooltip com tipo+data.
6. `equipment/detail_private.html`: "Reemitir patrimônio" continua vermelho, com texto, sem ícone.
7. Testar tab/teclado: todo `.icon-btn` deve ter contorno de foco visível ao navegar com Tab.
8. Testar leitor de tela (ou inspecionar o HTML) num ícone-só qualquer: o `aria-label` deve ser lido, nunca "botão sem nome".
9. `clients/client_list.html`, `operations/location_list.html`: coluna final mostra só o ícone de olho/lápis, alinhado, sem quebrar linha da tabela.
10. Paginação (Equipamentos, Clientes, Manutenções, Higienizações): "← Anterior" / "Próxima →" com seta e texto, nas duas pontas.
11. Todos os botões "Cancelar" (cinza) mostram um X pequeno antes do texto; "Cancelar manutenção"/"Cancelar registro" (vermelhos) continuam só texto.
12. **Mobile real** (não só viewport estreito no desktop): confirmar que qualquer ícone-só é fácil de tocar com o dedo, sem encostar no ícone vizinho.
13. Testar com zoom de texto do navegador aumentado — os `.icon-btn` não podem ficar menores que o alvo de toque.
14. Confirmar que nenhuma ação sensível (Reemitir patrimônio, Cancelar manutenção/registro) ficou menos visível que antes.

Sem deploy realizado — implementação só neste ambiente, aguardando validação do usuário.
