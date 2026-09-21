# apps.qrcodes

## Objetivo

`apps.qrcodes` é um app puramente de **serviço + views de download**: gera, sob demanda e inteiramente em memória, PNG de QR Code, PNG de código de barras (Code128), etiquetas em PDF (padrão "antigo"/completo e padrão "novo"/simplificado, os dois no MESMO canvas físico de adesivo — ver "Padrão físico do adesivo" abaixo), um PDF A4 em grade de QR "puro" por modelo, e exportações em `.zip`/PDF combinado em lote. **Não define landing pública nem admin customizado próprio** — a landing pública do QR e o modal de tema no Django Admin vivem em `apps.equipment`, que só consome `apps.qrcodes.services`/`urls`. O QR sempre codifica só a URL permanente `SITE_BASE_URL + /equipamentos/{patrimonio}/` — nunca dados do equipamento.

### Padrão físico do adesivo (rodada de padronização física)

O adesivo real disponível para uso da Locus é **60×40mm**. `STICKER_WIDTH_MM`/`STICKER_HEIGHT_MM` (`apps/qrcodes/services.py`) são a fonte ÚNICA de verdade para esse tamanho — a etiqueta antiga/completa (`LABEL_WIDTH_MM`/`LABEL_HEIGHT_MM`) e a etiqueta nova/simplificada (`SIMPLE_LABEL_WIDTH_MM`/`SIMPLE_LABEL_HEIGHT_MM`) apontam para as MESMAS constantes — nenhum renderer (individual, lote, Admin, cadastro em lote) fica com um tamanho diferente por esquecimento. **Antes desta rodada**: etiqueta antiga 100×50mm, etiqueta nova 60×60mm (literalmente quadrada), grade A4 com célula/QR de 50×50mm em 3×5 (15 por página) — todos os três formatos foram redesenhados.

Distinção importante, válida em TODO renderer deste app: **o canvas do adesivo (60×40mm) não é o tamanho do QR**. O QR (`generate_qr_png`) continua e sempre continuará quadrado — cada template decide, por conta própria, que fração quadrada do canvas retangular o QR ocupa:

| Onde | Canvas | QR |
|---|---|---|
| Etiqueta antiga/completa | 60×40mm | ~25×25mm (metade direita, "quase quadrada" nessa largura) |
| Etiqueta nova/simplificada | 60×40mm | 27×27mm fixo (com ou sem identificador legado) |
| Grade A4 (por célula) | 60×40mm | 36×36mm, centralizado |

Todos os três valores de QR foram **auditados/medidos fisicamente** no PDF real gerado (WeasyPrint → `pdfplumber`, em milímetros, nunca "no olho") — não são só o que o CSS declara. Ver `apps/qrcodes/tests/test_qr_and_labels.py`/`test_qr_grid_export.py` para as medições automatizadas equivalentes.

## Models

`apps/qrcodes/models.py` está **vazio** — nenhum model. `apps/qrcodes/migrations/` só tem `__init__.py`. O "tema" (light/dark) é um parâmetro transiente de request (`?tema=`), nunca persistido.

## Services

Arquivo: `apps/qrcodes/services.py`. Bibliotecas: `qrcode[pil]`, `Pillow`, `weasyprint`, `python-barcode`.

- `equipment_url(equipment)` — `SITE_BASE_URL + reverse("equipment:detail", patrimonio=...)`.
- `generate_qr_png(equipment)` / `generate_barcode_png(equipment)` (Code128 codificando só o `patrimonio`) — intocadas pela padronização física: o QR nunca teve nem tem nenhuma noção de "60×40", é sempre quadrado.
- `generate_label_pdf`/`generate_labels_pdf(equipment_list, theme="light")` — etiqueta **antiga/completa** (canvas 60×40mm — `LABEL_WIDTH_MM`/`LABEL_HEIGHT_MM`, com wordmark/barcode/patrimônio/QR; o rodapé com o site institucional foi removido nesta rodada para caber no canvas menor), via `weasyprint.HTML(string=render_to_string(...)).write_pdf()`.
- `generate_square_label_pdf`/`generate_square_labels_pdf(equipment_list, theme)` — etiqueta **nova/simplificada** (canvas 60×40mm — `SIMPLE_LABEL_WIDTH_MM`/`SIMPLE_LABEL_HEIGHT_MM`; nome de função "square" herdado de quando era literalmente quadrada, 60×60mm): só QR (`SIMPLE_LABEL_QR_SIZE_MM=27mm`, fixo com ou sem legado) + `model.code` (nunca o nome comercial) + `legacy_code` opcional. Sem logo, sem barcode, sem URL escrita, sem patrimônio.
- `_sanitize_path_segment()` — sanitiza nomes de pasta/arquivo dentro dos `.zip` (proteção contra directory traversal).
- `generate_qr_zip()` (QR "puro"), `generate_labels_zip()` (etiquetas antigas/completas), `generate_square_labels_zip()` (etiquetas novas/simplificadas) — todos `.zip` em memória (disco efêmero do Render free tier).
- `generate_qr_grid_pdf(equipment_list, theme="light")` — **um único PDF A4** com QR "puro" (sem logo/nome/patrimônio/barcode/texto) em grade `QR_GRID_COLUMNS × QR_GRID_ROWS` (3×6, `QR_GRID_PAGE_SIZE=18` por página, rodada de padronização física — era 3×5/15). Cada CÉLULA da grade é 1 adesivo real (`QR_GRID_CELL_WIDTH_MM=60` × `QR_GRID_CELL_HEIGHT_MM=40`, mesmo padrão único das etiquetas acima), com o QR (`QR_GRID_QR_SIZE_MM=36`, sempre quadrado) centralizado dentro dela — diferente de antes da padronização física, quando a célula tinha exatamente o tamanho do QR (`QR_GRID_CELL_SIZE_MM=50`, sem sobra nenhuma). `QR_GRID_GUTTER_MM=2` entre células (era 5). A grade inteira (`QR_GRID_WIDTH_MM=184` × `QR_GRID_HEIGHT_MM=250`) é centralizada matematicamente em A4 (`QR_GRID_PAGE_WIDTH_MM=210`×`QR_GRID_PAGE_HEIGHT_MM=297`): `QR_GRID_MARGIN_HORIZONTAL_MM=13` e `QR_GRID_MARGIN_VERTICAL_MM=23.5`, ambas calculadas (`(página - grade) / 2`), nunca hardcoded em paralelo — a margem VISÍVEL ao redor de cada QR impresso (medida do QR até a borda da página) é essa margem de página **mais** a folga da célula ao redor do QR (12mm horizontal, 2mm vertical), então na prática o primeiro QR de cada página fica a 25mm/25.5mm da borda, não 13mm/23.5mm (ver `apps/qrcodes/tests/test_qr_grid_export.py::ModelQRGridPhysicalDimensionsTest`, que mede os dois separadamente). `theme` ("light" padrão ou "dark", mesmas constantes `LABEL_THEME_*` de sempre) só muda o FUNDO da página (`#fff`/`#0a0a0a`) — o QR em si nunca é invertido (o PNG de `generate_qr_png` já é opaco com fundo branco, então a "ilha branca" acontece de graça, sem wrapper extra), e a geometria física é idêntica nos dois temas. Reaproveita `generate_qr_png`/`equipment_url` (via `_qr_data_uri`) — a MESMA origem de QR de qualquer outra função deste arquivo, nenhum segundo padrão. Paginação decidida em Python (`_chunked`), nunca deixada para o WeasyPrint resolver sozinho (quebra automática de grid/flex entre páginas não é confiável). Renderiza `templates/qrcodes/qr_grid.html`. Distinta de `generate_qr_zip` (que gera um `.zip` de PNGs soltos, sem paginação/impressão) — aqui o resultado é um documento único.

Nenhuma função grava em disco. Validação de tema é só em `views.py` (whitelist "light"/"dark"); `services.py` nunca valida, confia no chamador.

## Forms

Nenhum form neste app — todas as views são GET puro (download).

## Views

Arquivo: `apps/qrcodes/views.py`. Todas usam `RoleRequiredMixin` com `CAN_MANAGE_EQUIPMENT=(ADMIN,ADMINISTRATIVO)` — **as 8 rotas são privadas**.

| View | Resumo |
|---|---|
| `QRCodeDownloadView` | PNG do QR inline, 1 patrimônio |
| `LabelDownloadView` | PDF etiqueta individual, padrão novo/simplificado, sempre tema light |
| `LabelBatchDownloadView` | PDF combinado, etiqueta antiga/completa; usada pela action do Django Admin |
| `QRCodeZipExportView` | zip de etiquetas simplificadas (apesar do nome "QR Codes") |
| `QRCodeOnlyZipExportView` | zip de QR "puro" |
| `ModelLabelBatchDownloadView` | PDF simplificado de todos equipamentos ativos de 1 modelo |
| `ModelQRGridDownloadView` | PDF A4 em grade de QR "puro" de todos equipamentos ativos de 1 modelo |
| `LabelZipExportView` | zip de etiquetas antigas/completas |

Todos os formatos PDF acima imprimem no mesmo canvas físico de adesivo (60×40mm) — ver "Padrão físico do adesivo" no topo deste documento.

`ModelQRGridDownloadView` espelha exatamente o escopo/permissão/tratamento de 404 de `ModelLabelBatchDownloadView` (mesmo `Equipment.objects.filter(model_id=model_id, is_active=True)`, só acrescentando `order_by("patrimonio")` para ordem determinística — a spec pediu explicitamente ordem determinística, o que `model_label_batch` nunca precisou declarar) — só troca o conteúdo do PDF (`generate_qr_grid_pdf` em vez de `generate_square_labels_pdf`) e o nome do arquivo (`qrcodes-{code}.pdf`). **`?tema=light|dark`** (decisão revista em 16/09/2026 — a v1 não aceitava tema; passou a aceitar reaproveitando o MESMO modal Claro/Escuro de `model_label_batch`) validado via `_validated_theme`, a mesma função já usada por toda outra rota deste arquivo — nenhuma validação nova.

## URLs

`app_name="qrcodes"`, montado como `path("qrcodes/", ...)`. **Todas as 8 rotas são privadas.** A rota realmente pública ligada ao QR físico **não está aqui** — é `equipment:detail` (`/equipamentos/<patrimonio>/`), em `apps.equipment`. `modelo/<int:model_id>/qrcodes.pdf` (`model_qr_grid`) vem antes do catch-all `<str:patrimonio>/...`, mesmo raciocínio defensivo de `modelo/<int:model_id>/etiquetas.pdf`.

## Permissions

`CAN_MANAGE_EQUIPMENT=(ADMIN,ADMINISTRATIVO)` aplicado a todas as views. A rota pública (`equipment:detail`) não usa nenhum mixin — é um `View` puro que ramifica por `is_authenticated` (documentado em `docs/apps/equipment.md`). Validação de tema sempre no backend, nunca confiando só no JS do modal.

## Templates

`templates/qrcodes/label.html` (etiqueta antiga/completa), `label_square.html` (etiqueta nova/simplificada) e `qr_grid.html` (grade A4 de QR puro) — renderizados só internamente via `render_to_string` → WeasyPrint, nunca servidos como página normal.

- `label.html` — REDESENHADA na rodada de padronização física para o canvas 60×40mm (antes: 100×50mm). Recebe `label_width_mm`/`label_height_mm` (sempre `LABEL_WIDTH_MM`/`LABEL_HEIGHT_MM`). Duas metades 50/50 (identidade+patrimônio à esquerda, QR à direita — a divisão antiga era 52/48). Bloco de marca reduzido a só o wordmark "LOCUS" (subtítulo, linha divisória amarela e tagline foram removidos); rodapé com o site institucional removido por completo — devolveram espaço vertical ao código de barras/patrimônio, que são funcionais (o site era só decorativo). `.identity-patrimonio` não trunca mais com reticências (`text-overflow`) — quebra em até 2 linhas (`overflow-wrap: break-word`), porque a coluna de 30mm de largura não comporta o patrimônio inteiro numa linha só sem cortar informação funcional.
- `label_square.html` — REDESENHADA para o canvas 60×40mm (antes: 60×60mm, literalmente quadrado). Ordem do conteúdo trocada: código do modelo agora é a PRIMEIRA linha (antes vinha depois do QR), seguido do QR (`qr_size_mm`, sempre `SIMPLE_LABEL_QR_SIZE_MM=27mm`, fixo com ou sem legado) e do identificador legado (condicional, como antes). Layout sempre em coluna única vertical, nunca duas colunas. `.label` usa `justify-content: center` para absorver a diferença de altura entre "com legado" e "sem legado" sem mudar o tamanho do QR. `.model-code`/`.legacy-code` precisam de `width` explícito (não só `max-width`) para o truncamento por reticências funcionar de verdade dentro do flex column — sem isso, um `model.code` de 20 caracteres (o máximo do cadastro) extrapolava a largura do adesivo inteiro em vez de truncar (bug encontrado e corrigido nesta rodada).
- `qr_grid.html` — recebe `pages` (lista de páginas já paginadas em Python, cada uma com até `QR_GRID_PAGE_SIZE` células), `page_width_mm`/`page_height_mm`/`cell_width_mm`/`cell_height_mm`/`qr_size_mm`/`gutter_mm`/`margin_horizontal_mm`/`margin_vertical_mm` (nenhuma medida fixa no template, `@page{margin:0}` e toda margem visível vem do `padding` calculado do `.qr-page`) e `theme` (`<body class="theme-dark">` quando "dark" — mesmo padrão de `label_square.html`: só `body.theme-dark`/`.qr-page`/`.qr-caption` ganham regra de cor extra, o `.qr-image` nunca muda). `.qr-cell` é o adesivo inteiro (`cell_width_mm × cell_height_mm`); `.qr-image`, dentro dela, é `qr_size_mm × qr_size_mm` e fica centralizada pelo flex da célula — antes da padronização física, célula e imagem eram o MESMO tamanho (sem sobra). Cada célula tem um campo `caption` (sempre `None` hoje) como ponto de extensão futuro, sem nenhuma opção de UI para preenchê-lo ainda — agora com mais margem real ao redor para acomodar uma legenda futura. **Bug histórico (16/09/2026, ainda relevante)**: `{{ margin_vertical_mm }}` fracionário (ex.: 13.5, hoje 23.5) renderizava com VÍRGULA decimal por causa de `LANGUAGE_CODE="pt-br"` ("23,5mm", CSS inválido, WeasyPrint ignorava e colapsava a margem para 0 — a causa raiz do "grade deslocada para a esquerda" relatado à época) — corrigido com `{% load l10n %}{% localize off %}` ao redor do `<style>`, e continua necessário porque as margens da nova grade também são fracionárias.

## JavaScript

Dois arquivos **distintos e não relacionados por herança**, cobrindo o mesmo conceito (modal de tema) em contextos diferentes:

1. **`static/qrcodes/admin/label_theme_modal.js`** (+ `.css`) — carregado **exclusivamente via `ModelAdmin.Media`** de `EquipmentAdmin` (`apps/equipment/admin.py`). **Nenhuma tag `{% static %}` referencia este arquivo em nenhum template** — um audit ingênuo de grep em templates não o encontraria.
2. **`static/qrcodes/label_theme_modal.js`** — arquivo separado, para as páginas normais da aplicação, carregado via `{% static %}` em `templates/equipment/list.html` e `batch_result.html`.

## Admin

`apps/qrcodes/admin.py` está vazio. O modal de tema é customização de **`EquipmentAdmin`** (`apps.equipment`): `qr_etiqueta_links` (links para `qrcodes:qr_png`/`label_pdf`), action `download_labels_pdf` (redireciona para `qrcodes:label_batch`), `class Media` (injeta o JS/CSS do item 1 acima só na changelist de Equipment).

## Dependências

`apps.equipment.models.Equipment`; `apps.catalog.models.EquipmentModel`; `apps.accounts.permissions`; `settings.SITE_BASE_URL`; bibliotecas `qrcode`, `Pillow`, `weasyprint`, `barcode`.

## Quem chama apps.qrcodes

`apps.equipment.admin` (links, redirect, `LABEL_THEME_LIGHT`, assets do modal); templates de `apps.equipment` (`list.html`, `batch_result.html`, `_model_group_items.html`, `detail_private.html`). `list.html` também tem o botão novo "Exportar QR Codes em PDF" (`qrcodes:model_qr_grid`), sibling do botão "Etiquetas em lote" já existente, dentro do mesmo `.model-group-card` (agrupados num wrapper `.action-group`, 16/09/2026) — inclui `data-label-theme-trigger` (mesma decisão revista de 16/09/2026: reaproveita o MESMO modal Claro/Escuro já carregado nessa página via `static/qrcodes/label_theme_modal.js`, nenhum JS/modal novo). Nenhum outro app (`clients`, `operations`, `maintenance`, `crm`, `dashboard`, `catalog`) referencia `qrcodes` diretamente.

## Testes

`apps/qrcodes/tests/test_qr_and_labels.py` — cobertura ampla: QR/barcode válidos e decodificáveis, conteúdo do PDF nos dois temas, etiqueta quadrada nunca expõe nome comercial/patrimônio/URL, sanitização de path contra directory traversal, geração não escreve em disco, permissões (Admin/Administrativo podem, Operacional/Consulta proibidos). **Atualizado na rodada de padronização física** (importa `SIMPLE_LABEL_WIDTH_MM`/`SIMPLE_LABEL_HEIGHT_MM`/`SIMPLE_LABEL_QR_SIZE_MM` em vez do antigo `SQUARE_LABEL_SIZE_MM`): `test_light_theme_is_a_valid_pdf_at_the_configured_sticker_size`/`test_dark_theme_is_a_valid_pdf_at_the_same_sticker_size`/`test_label_pdf_download_uses_the_new_simplified_format` (renomeados, validam o canvas 60×40mm) e o novo `test_qr_inside_the_sticker_is_square_and_uses_the_configured_size` (mede via `pdfplumber` que o QR da etiqueta simplificada é exatamente `SIMPLE_LABEL_QR_SIZE_MM` quadrado, não deformado). O helper `_assert_patrimonio_legible()` (compara o patrimônio ignorando quebras de linha) existe porque `label.html` agora QUEBRA o patrimônio em até 2 linhas em vez de truncar com reticências (ver "Templates" acima) — `pypdf.extract_text()` insere `\n` reais onde o CSS quebra, então comparar com `assertIn` direto quebraria mesmo com o patrimônio 100% legível; usado nos 3 testes que liam esse texto. Mais `apps/equipment/tests/test_admin_label_theme_action.py` (confirma via `assertContains` que os assets do `Media` estão na changelist) e `test_equipment_grouped_listing.py` (confirma o JS de app na listagem).

`apps/qrcodes/tests/test_qr_grid_export.py` (16/09/2026, **medições atualizadas na rodada de padronização física**) — `ModelQRGridDownloadViewTest`: permissão (backend, igual a `model_label_batch`), 200/`Content-Type: application/pdf`, 1 QR por equipamento (lote único e grande/multi-página), o QR embutido decodifica para a MESMA URL/bytes de `generate_qr_png`/`equipment_url` (nenhum segundo padrão), sem mistura de escopo (outro modelo/inativo nunca aparece), ordem determinística por `patrimonio`, ausência total de efeito colateral (`Equipment`/`Movement`/`StatusHistory`/`ConditionHistory`/`Attachment` inalterados), nome de arquivo (`qrcodes-{code}.pdf`), PDF sem nenhum texto (QR puro), 404 de modelo inexistente/sem equipamento ativo. `ModelQRGridPhysicalDimensionsTest` (mesmo arquivo) mede posição/tamanho de cada imagem embutida direto do conteúdo do PDF via `pdfplumber` (em mm, não por screenshot), agora contra os valores da padronização física: página A4 210×297mm, cada QR exatamente 36×36mm (`test_each_qr_image_is_exactly_36x36mm`, nunca mais 50mm), grade 3 colunas × 6 linhas = 18 por página (`test_grid_is_three_columns_by_six_rows_of_eighteen`, era 3×5=15). O "gutter" agora é medido em duas camadas distintas, porque célula (60×40mm) e QR (36×36mm) deixaram de ter o mesmo tamanho: `test_grid_pitch_between_cells_is_cell_size_plus_gutter` confirma o passo entre células (tamanho da célula + `QR_GRID_GUTTER_MM=2`) e `test_visible_gap_between_adjacent_qr_images_matches_gutter_plus_cell_margins` confirma a folga VISÍVEL entre dois QRs vizinhos (gutter + a margem da célula ao redor do QR, `CELL_MARGIN_HORIZONTAL_MM=12`/`CELL_MARGIN_VERTICAL_MM=2`, substituindo o teste único de gutter de antes). Grade centralizada horizontalmente (`test_grid_is_horizontally_centered_with_equal_margins`) e verticalmente (`test_grid_and_vertical_margins_match_the_requested_layout`) — margem visível até o primeiro/último QR é `QR_GRID_MARGIN_HORIZONTAL_MM + CELL_MARGIN_HORIZONTAL_MM = 25mm` e `QR_GRID_MARGIN_VERTICAL_MM + CELL_MARGIN_VERTICAL_MM = 25.5mm` (grade 184×250mm), não a margem de página sozinha. Nenhuma página extra para lotes que fecham em múltiplos exatos de 18 (`test_no_extra_blank_page_for_exact_multiples_of_page_size`, casos 18→1 e 36→2, era 15/30), múltiplas páginas nos casos 19→2 e 37→3 (`test_multiple_pages_for_batches_past_a_full_page`, era 16→2/31→3), página incompleta preenchendo em ordem de leitura sem redistribuir/centralizar os itens entre si e mantendo as MESMAS margens de página (`test_partial_page_keeps_the_same_grid_positions_and_page_margins`, agora conferindo `QR_GRID_MARGIN_*_MM + CELL_MARGIN_*_MM`). `ModelQRGridThemeTest` (mesmo arquivo, rodada do tema Claro/Escuro) confirma: default sem `?tema=` continua "light", `dark` aceito, tema inválido rejeitado com 400 (mesma `_validated_theme`), light/dark geram PDFs com bytes diferentes mas geometria física IDÊNTICA nos dois, o PNG do QR embutido é byte-a-byte idêntico entre temas (nunca invertido), QR continua decodificando para a URL certa nos dois temas, nome de arquivo não muda com o tema, sem texto em nenhum dos dois. `LabelThemeModalMarkupTest` (em `apps/equipment/tests/test_equipment_grouped_listing.py`) ganhou `test_model_qr_grid_button_is_also_a_theme_trigger`/`test_model_qr_grid_button_hidden_for_consulta`, confirmando que o botão novo usa o MESMO `data-label-theme-trigger`/script já validado para "Etiquetas em lote", nenhum gatilho/modal próprio.

## Migrations

Nenhuma — `apps/qrcodes/migrations/` só tem `__init__.py` (reflexo de não haver models).

## Pontos importantes

- **Segurança da rota pública** vive em `apps.equipment`, não aqui — `.only(...)` no queryset garante em nível de banco que campos operacionais/comerciais nunca saem na consulta anônima.
- **Duas gerações de etiqueta coexistem deliberadamente, nunca unificadas** — reaproveitar a mesma função faria um botão existente mudar de formato sem ter sido pedido.
- **`generate_qr_zip` ficou "órfã" por um tempo** (08/09 a 10/09/2026) até ganhar um chamador de volta (`QRCodeOnlyZipExportView`) — mantida porque tinha cobertura de teste.
- **Validação de tema é redundante por design**: front-end evita esquecimento, back-end (`_validated_theme`) é a única barreira real contra tema forjado via querystring/POST.
- **`generate_qr_grid_pdf`/`model_qr_grid` (16/09/2026) foi escopado ao lote POR MODELO** (mesma queryset de `ModelLabelBatchDownloadView`), não ao lote "todos os equipamentos ativos" do toolbar (`_active_equipment_for_export`/`QRCodeOnlyZipExportView`) — decisão inferida do exemplo concreto do pedido original (card de 1 modelo específico), não reconfirmada explicitamente. Se um QR grid em PDF do escopo do toolbar também for desejado, é uma extensão futura, não implementada nesta rodada.
- **`model_qr_grid` aceitar `?tema=` foi uma decisão REVISTA no mesmo dia** — a v1 deliberadamente não aceitava tema ("QR puro não tem etiqueta para ter LIGHT/DARK"); um pedido explícito de reaproveitar o modal Claro/Escuro fez essa decisão ser revertida. O tema muda só o fundo da página (`#fff`/`#0a0a0a`, mesmo tom de `label_square.html`) — o QR em si continua com a mesma regra incondicional de nunca ser invertido, herdada de graça porque `generate_qr_png` já produz um PNG opaco de fundo branco.
- **Rodada de padronização física para adesivo 60×40mm** (21/09/2026) — motivada por uma restrição de produção real: o único adesivo disponível para a Locus é 60×40mm, não 100×50mm nem 60×60mm nem a célula de 50×50mm da grade A4. Decisões tomadas, todas auditadas fisicamente (PDF real → `pdfplumber`, nunca só CSS):
  - **Rodapé com o site institucional removido de `label.html`** — era puramente decorativo; no canvas menor (60×40 vs. 100×50) o espaço vertical passou a ser necessário para o código de barras/patrimônio, que são funcionais.
  - **Patrimônio de `label.html` passou de truncamento por reticências para quebra em até 2 linhas** (`overflow-wrap: break-word`) — a coluna de 30mm de largura não comporta o patrimônio inteiro numa linha só; truncar cortaria informação funcional (prioridade 2 do pedido, "patrimônio legível"), então a solução foi quebrar em vez de cortar. Exigiu o helper de teste `_assert_patrimonio_legible()` (ver "Testes").
  - **QR de `label_square.html` fixado em 27mm, igual com ou sem identificador legado** (não um valor "maior quando cabe") — escolhido empiricamente: com `SIMPLE_LABEL_QR_SIZE_MM=30` (primeira tentativa, dentro da faixa de referência de 28–32mm do pedido) o cenário "com legado" estourava o canvas de 40mm de altura (~43.46mm de conteúdo) e o `overflow:hidden` cortava a linha do identificador legado por completo sem erro visível — só percebido medindo o texto extraído do PDF. Reduzido para 27mm (fora da faixa de referência, mas dentro do espírito "não rígida, deve ser auditada e justificada" do pedido) e os paddings/fontes ajustados até os dois cenários (com/sem legado) caberem com margem real, sem gerar duas variantes visualmente distintas da mesma etiqueta.
  - **Bug de `text-overflow: ellipsis` não aplicado em `.model-code`/`.legacy-code` de `label_square.html`** — descoberto ao testar com um `model.code` de 20 caracteres (o máximo aceito pelo `CODE_VALIDATOR`): o texto extrapolava o adesivo inteiro em vez de truncar, porque dentro de um flex column com `align-items:center` o WeasyPrint não calcula overflow/ellipsis de forma confiável quando o elemento só tem `max-width` (sem `width` explícito). Corrigido adicionando `display:block; width:92%` a ambos.
- Nenhum TODO/FIXME real encontrado.
