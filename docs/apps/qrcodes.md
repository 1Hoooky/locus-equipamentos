# apps.qrcodes

## Objetivo

`apps.qrcodes` é um app puramente de **serviço + views de download**: gera, sob demanda e inteiramente em memória, PNG de QR Code, PNG de código de barras (Code128), etiquetas em PDF (padrão "antigo"/completo e padrão "novo"/simplificado, os dois no MESMO canvas físico de adesivo — ver "Padrão físico do adesivo" abaixo), um PDF multipágina de QR "puro" por modelo (1 página = 1 adesivo — ver "Correção — exportação em lote de QR puro" abaixo), e exportações em `.zip`/PDF combinado em lote. **Não define landing pública nem admin customizado próprio** — a landing pública do QR e o modal de tema no Django Admin vivem em `apps.equipment`, que só consome `apps.qrcodes.services`/`urls`. O QR sempre codifica só a URL permanente `SITE_BASE_URL + /equipamentos/{patrimonio}/` — nunca dados do equipamento.

### Padrão físico do adesivo (rodada de padronização física)

O adesivo real disponível para uso da Locus é **60×40mm**. `STICKER_WIDTH_MM`/`STICKER_HEIGHT_MM` (`apps/qrcodes/services.py`) são a fonte ÚNICA de verdade para esse tamanho — a etiqueta antiga/completa (`LABEL_WIDTH_MM`/`LABEL_HEIGHT_MM`) e a etiqueta nova/simplificada (`SIMPLE_LABEL_WIDTH_MM`/`SIMPLE_LABEL_HEIGHT_MM`) apontam para as MESMAS constantes — nenhum renderer (individual, lote, Admin, cadastro em lote) fica com um tamanho diferente por esquecimento. **Antes desta rodada**: etiqueta antiga 100×50mm, etiqueta nova 60×60mm (literalmente quadrada), grade A4 com célula/QR de 50×50mm em 3×5 (15 por página) — todos os três formatos foram redesenhados.

Distinção importante, válida em TODO renderer deste app: **o canvas do adesivo (60×40mm) não é o tamanho do QR**. O QR (`generate_qr_png`) continua e sempre continuará quadrado — cada template decide, por conta própria, que fração quadrada do canvas retangular o QR ocupa:

| Onde | Canvas | QR |
|---|---|---|
| Etiqueta antiga/completa | 60×40mm | ~25×25mm (metade direita, "quase quadrada" nessa largura) |
| Etiqueta nova/simplificada | 60×40mm | 27×27mm fixo (com ou sem identificador legado) |
| Exportação em lote de QR puro (1 página = 1 adesivo) | 60×40mm | 36×36mm, centralizado |
| Grade A4 antiga (por célula, código ainda existe, órfã — ver seção seguinte) | 60×40mm | 36×36mm, centralizado |

Todos os valores de QR foram **auditados/medidos fisicamente** no PDF real gerado (WeasyPrint → `pdfplumber`, em milímetros, nunca "no olho") — não são só o que o CSS declara. Ver `apps/qrcodes/tests/test_qr_and_labels.py`/`test_qr_grid_export.py` para as medições automatizadas equivalentes.

### Correção — exportação em lote de QR puro para impressão real (23/09/2026)

A exportação em lote de QR "puro" por modelo (botão "Exportar QR Codes em PDF") entregava, até esta correção, uma **grade A4** (`generate_qr_grid_pdf`, 3 colunas × 6 linhas = 18 QRs por folha). Na prática de impressão em adesivo — folha alimentada uma a uma, sem o operador desabilitar "ajustar à página" no driver — o resultado saía **cortado**: o problema nunca foi o QR em si, era o formato de saída (uma folha A4 com várias colunas não corresponde ao adesivo físico real).

A view (`ModelQRGridDownloadView`) passou a entregar um **PDF multipágina** via `generate_qr_batch_pdf`: cada página é **1 adesivo físico inteiro** (`QR_BATCH_WIDTH_MM`×`QR_BATCH_HEIGHT_MM` = 60×40mm, o MESMO canvas de sempre) com **1 QR puro centralizado** (`QR_BATCH_QR_SIZE_MM` = 36mm — o MESMO valor de `QR_GRID_QR_SIZE_MM`, de propósito: a conta física "maior QR que cabe centralizado numa área 60×40" já tinha sido auditada uma vez). `N` equipamentos ativos do modelo sempre produzem um PDF de `N` páginas — o mesmo conceito de impressão que `generate_labels_pdf`/`generate_square_labels_pdf` já usam (e que nunca teve esse problema).

`generate_qr_grid_pdf`/`templates/qrcodes/qr_grid.html` (a grade A4) **não foram removidos** — continuam no código, com cobertura de teste direta própria (`LegacyQrGridServiceStillWorksTest`), disponíveis para reuso futuro, só deixaram de ser o que este botão entrega. Nome da URL/view/classe (`model_qr_grid`/`ModelQRGridDownloadView`) e nome do arquivo (`qrcodes-{code}.pdf`) foram mantidos de propósito — nenhuma relação com o formato de impressão em si, e trocar exigiria tocar template/JS/testes à toa (mesmo raciocínio já usado para manter `generate_square_label_pdf`/"square" depois que o formato virou 60×40 retangular).

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
- `generate_qr_grid_pdf(equipment_list, theme="light")` — **ÓRFÃ desde 23/09/2026** (ver "Correção — exportação em lote de QR puro" acima): continua funcional e testada diretamente (`LegacyQrGridServiceStillWorksTest`), só não é mais chamada por nenhuma view. Gera **um único PDF A4** com QR "puro" em grade `QR_GRID_COLUMNS × QR_GRID_ROWS` (3×6, `QR_GRID_PAGE_SIZE=18` por página). Cada CÉLULA da grade é 1 adesivo real (`QR_GRID_CELL_WIDTH_MM=60` × `QR_GRID_CELL_HEIGHT_MM=40`), com o QR (`QR_GRID_QR_SIZE_MM=36`, sempre quadrado) centralizado dentro dela. `QR_GRID_GUTTER_MM=2` entre células. A grade inteira (`QR_GRID_WIDTH_MM=184` × `QR_GRID_HEIGHT_MM=250`) é centralizada matematicamente em A4 (`QR_GRID_PAGE_WIDTH_MM=210`×`QR_GRID_PAGE_HEIGHT_MM=297`): `QR_GRID_MARGIN_HORIZONTAL_MM=13` e `QR_GRID_MARGIN_VERTICAL_MM=23.5`. Paginação decidida em Python (`_chunked`). Renderiza `templates/qrcodes/qr_grid.html`.
- `generate_qr_batch_pdf(equipment_list, theme="light")` — **exportação em lote de QR puro atual** (substitui `generate_qr_grid_pdf` como conteúdo de `ModelQRGridDownloadView` desde 23/09/2026): um **PDF multipágina** onde cada página é 1 adesivo físico inteiro (`QR_BATCH_WIDTH_MM`×`QR_BATCH_HEIGHT_MM` = 60×40mm) com 1 QR puro (`QR_BATCH_QR_SIZE_MM=36mm`, sempre quadrado) centralizado — sem logo/nome/patrimônio/barcode/texto algum. `N` equipamentos = `N` páginas, sempre — nenhum agrupamento/`_chunked` (diferente de `generate_qr_grid_pdf`, não existe "página cheia" aqui). `theme` — mesmo comportamento de sempre: só muda o FUNDO da página; o QR em si nunca é invertido. Reaproveita `generate_qr_png`/`equipment_url` (via `_qr_data_uri`) — a MESMA origem de QR de qualquer outra função deste arquivo, nenhum segundo padrão. Renderiza `templates/qrcodes/qr_batch.html`. Distinta de `generate_qr_zip` (que gera um `.zip` de PNGs soltos, sem paginação/impressão) — aqui o resultado é um documento único pronto para imprimir adesivo a adesivo.

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
| `ModelQRGridDownloadView` | PDF multipágina de QR "puro" (1 página = 1 adesivo) de todos equipamentos ativos de 1 modelo |
| `LabelZipExportView` | zip de etiquetas antigas/completas |

Todos os formatos PDF acima imprimem no mesmo canvas físico de adesivo (60×40mm) — ver "Padrão físico do adesivo" no topo deste documento.

`ModelQRGridDownloadView` espelha exatamente o escopo/permissão/tratamento de 404 de `ModelLabelBatchDownloadView` (mesmo `Equipment.objects.filter(model_id=model_id, is_active=True)`, só acrescentando `order_by("patrimonio")` para ordem determinística — a spec pediu explicitamente ordem determinística, o que `model_label_batch` nunca precisou declarar) — só troca o conteúdo do PDF (`generate_qr_batch_pdf` desde 23/09/2026, antes `generate_qr_grid_pdf` — ver "Correção — exportação em lote de QR puro" no topo do documento) e o nome do arquivo (`qrcodes-{code}.pdf`). **`?tema=light|dark`** validado via `_validated_theme`, a mesma função já usada por toda outra rota deste arquivo — nenhuma validação nova.

## URLs

`app_name="qrcodes"`, montado como `path("qrcodes/", ...)`. **Todas as 8 rotas são privadas.** A rota realmente pública ligada ao QR físico **não está aqui** — é `equipment:detail` (`/equipamentos/<patrimonio>/`), em `apps.equipment`. `modelo/<int:model_id>/qrcodes.pdf` (`model_qr_grid`) vem antes do catch-all `<str:patrimonio>/...`, mesmo raciocínio defensivo de `modelo/<int:model_id>/etiquetas.pdf`.

## Permissions

`CAN_MANAGE_EQUIPMENT=(ADMIN,ADMINISTRATIVO)` aplicado a todas as views. A rota pública (`equipment:detail`) não usa nenhum mixin — é um `View` puro que ramifica por `is_authenticated` (documentado em `docs/apps/equipment.md`). Validação de tema sempre no backend, nunca confiando só no JS do modal.

## Templates

`templates/qrcodes/label.html` (etiqueta antiga/completa), `label_square.html` (etiqueta nova/simplificada), `qr_batch.html` (exportação em lote de QR puro, 1 página = 1 adesivo — o que `ModelQRGridDownloadView` renderiza desde 23/09/2026) e `qr_grid.html` (grade A4 de QR puro, órfã — só usada diretamente por `generate_qr_grid_pdf`, sem view) — renderizados só internamente via `render_to_string` → WeasyPrint, nunca servidos como página normal.

- `label.html` — REDESENHADA na rodada de padronização física para o canvas 60×40mm (antes: 100×50mm). Recebe `label_width_mm`/`label_height_mm` (sempre `LABEL_WIDTH_MM`/`LABEL_HEIGHT_MM`). Duas metades 50/50 (identidade+patrimônio à esquerda, QR à direita — a divisão antiga era 52/48). Bloco de marca reduzido a só o wordmark "LOCUS" (subtítulo, linha divisória amarela e tagline foram removidos); rodapé com o site institucional removido por completo — devolveram espaço vertical ao código de barras/patrimônio, que são funcionais (o site era só decorativo). `.identity-patrimonio` não trunca mais com reticências (`text-overflow`) — quebra em até 2 linhas (`overflow-wrap: break-word`), porque a coluna de 30mm de largura não comporta o patrimônio inteiro numa linha só sem cortar informação funcional.
- `label_square.html` — REDESENHADA para o canvas 60×40mm (antes: 60×60mm, literalmente quadrado). Ordem do conteúdo trocada: código do modelo agora é a PRIMEIRA linha (antes vinha depois do QR), seguido do QR (`qr_size_mm`, sempre `SIMPLE_LABEL_QR_SIZE_MM=27mm`, fixo com ou sem legado) e do identificador legado (condicional, como antes). Layout sempre em coluna única vertical, nunca duas colunas. `.label` usa `justify-content: center` para absorver a diferença de altura entre "com legado" e "sem legado" sem mudar o tamanho do QR. `.model-code`/`.legacy-code` precisam de `width` explícito (não só `max-width`) para o truncamento por reticências funcionar de verdade dentro do flex column — sem isso, um `model.code` de 20 caracteres (o máximo do cadastro) extrapolava a largura do adesivo inteiro em vez de truncar (bug encontrado e corrigido nesta rodada).
- `qr_batch.html` (23/09/2026) — CRIADA para a correção de impressão real (ver seção no topo do documento). Recebe `pages` (lista de contextos, 1 por equipamento — nenhum agrupamento/paginação em Python aqui, diferente de `qr_grid.html`), `page_width_mm`/`page_height_mm` (sempre `QR_BATCH_WIDTH_MM`/`QR_BATCH_HEIGHT_MM` = 60×40mm), `qr_size_mm` (sempre `QR_BATCH_QR_SIZE_MM` = 36mm) e `theme`. `@page { size: {{ page_width_mm }}mm {{ page_height_mm }}mm; margin: 0 }` — mesma técnica de `label.html`/`label_square.html` (uma página física exata por item, não uma folha A4 genérica). Cada `<div class="qr-page">` é 1 adesivo inteiro com `page-break-after: always`, contendo só a imagem do QR centralizada (`display:flex; align-items:center; justify-content:center`) — nenhum texto, nenhuma célula/grade, nenhum `caption`. Sem `{% load l10n %}{% localize off %}`: diferente de `qr_grid.html`, `page_width_mm`/`page_height_mm`/`qr_size_mm` aqui são sempre inteiros (60/40/36), nunca fracionários, então o bug de vírgula decimal nunca se aplica.
- `qr_grid.html` — ÓRFÃ desde 23/09/2026 (ver acima), mantida intacta. Recebe `pages` (lista de páginas já paginadas em Python, cada uma com até `QR_GRID_PAGE_SIZE` células), `page_width_mm`/`page_height_mm`/`cell_width_mm`/`cell_height_mm`/`qr_size_mm`/`gutter_mm`/`margin_horizontal_mm`/`margin_vertical_mm` (nenhuma medida fixa no template, `@page{margin:0}` e toda margem visível vem do `padding` calculado do `.qr-page`) e `theme` (`<body class="theme-dark">` quando "dark" — mesmo padrão de `label_square.html`: só `body.theme-dark`/`.qr-page`/`.qr-caption` ganham regra de cor extra, o `.qr-image` nunca muda). `.qr-cell` é o adesivo inteiro (`cell_width_mm × cell_height_mm`); `.qr-image`, dentro dela, é `qr_size_mm × qr_size_mm` e fica centralizada pelo flex da célula. Cada célula tem um campo `caption` (sempre `None` hoje) como ponto de extensão futuro, sem nenhuma opção de UI para preenchê-lo ainda. **Bug histórico (16/09/2026, ainda relevante para quem reutilizar este template)**: `{{ margin_vertical_mm }}` fracionário (ex.: 13.5, hoje 23.5) renderizava com VÍRGULA decimal por causa de `LANGUAGE_CODE="pt-br"` ("23,5mm", CSS inválido, WeasyPrint ignorava e colapsava a margem para 0) — corrigido com `{% load l10n %}{% localize off %}` ao redor do `<style>`.

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

`apps/qrcodes/tests/test_qr_grid_export.py` (16/09/2026; **reescrito em 23/09/2026** para a correção de impressão real — ver seção no topo do documento) — 4 classes:

- `ModelQRGridDownloadViewTest`: permissão (backend, igual a `model_label_batch`), 200/`Content-Type: application/pdf`, 1 QR por equipamento, `N` equipamentos produzem um PDF de EXATAMENTE `N` páginas (`test_n_equipment_produces_a_pdf_with_exactly_n_pages`, usa 26 — o próprio exemplo numérico do pedido de correção — em vez do antigo "≥2 páginas para lote >18"), o QR embutido decodifica para a MESMA URL/bytes de `generate_qr_png`/`equipment_url` (nenhum segundo padrão), sem mistura de escopo (outro modelo/inativo nunca aparece), ordem determinística por `patrimonio` (agora verificada página a página, já que a ordem de leitura do PDF multipágina É a ordem das páginas), ausência total de efeito colateral (`Equipment`/`Movement`/`StatusHistory`/`ConditionHistory`/`Attachment` inalterados), nome de arquivo (`qrcodes-{code}.pdf`, inalterado pela correção), PDF sem nenhum texto (QR puro), 404 de modelo inexistente/sem equipamento ativo.
- `ModelQRBatchPhysicalDimensionsTest` (substitui a antiga `ModelQRGridPhysicalDimensionsTest`) mede, via `pdfplumber`, direto no conteúdo do PDF (em mm, não por screenshot): cada página mede exatamente 60×40mm — nunca A4 (`test_every_page_measures_60x40mm`, testado em várias páginas do mesmo lote, não só a primeira); cada página contém exatamente 1 imagem (`test_each_page_has_exactly_one_qr`); o QR mede exatamente 36×36mm em toda página (`test_each_qr_image_is_exactly_36x36mm`); o QR fica centralizado em CADA página com margens simétricas — esquerda=direita=12mm, topo=base=2mm (`test_qr_is_centered_on_every_page_with_symmetric_margins`); `N` equipamentos = `N` páginas para `N` em `{1, 4, 26}` (`test_n_equipment_produces_n_pages`, nenhum desses números é múltiplo de nada "especial" — não existe mais o conceito de "página cheia"); QR decodifica corretamente; PDF sem texto; operação sem efeito colateral. Os testes antigos de grade (colunas/linhas, gutter entre células, página cheia de 18, página parcial preenchendo em ordem de leitura) foram removidos — não porque perderam cobertura, mas porque testavam um objeto (folha A4 com várias colunas) que não existe mais no que esta view entrega; o requisito físico real que protegiam (QR centralizado, tamanho exato, sem corte) continua coberto, agora por página individual.
- `ModelQRGridThemeTest` (nome mantido — ainda testa o tema da MESMA view): default "light", `dark` aceito, tema inválido rejeitado com 400 (mesma `_validated_theme`), light/dark geram PDFs com bytes diferentes mas geometria física IDÊNTICA nos dois (agora comparando o QR de cada página, não só a primeira), o PNG do QR embutido é byte-a-byte idêntico entre temas (nunca invertido), QR continua decodificando para a URL certa nos dois temas, nome de arquivo não muda com o tema, sem texto em nenhum dos dois, e `generate_qr_batch_pdf` (a função atual, antes era `generate_qr_grid_pdf`) aceita as duas constantes de tema quando chamada diretamente.
- `LegacyQrGridServiceStillWorksTest` (NOVA, 23/09/2026) — cobertura direta e mínima para `generate_qr_grid_pdf`/`qr_grid.html`, chamando a função de serviço direto, sem nenhuma view/URL (nenhuma rota a usa mais): confirma que a grade A4 3×6=18/página, QR 36mm, decodificação e suporte a tema continuam funcionando — mesmo precedente já usado neste projeto para não deletar `generate_qr_zip` quando ela ficou "órfã" por um tempo (ver "Pontos importantes").

`LabelThemeModalMarkupTest` (em `apps/equipment/tests/test_equipment_grouped_listing.py`) continua com `test_model_qr_grid_button_is_also_a_theme_trigger`/`test_model_qr_grid_button_hidden_for_consulta` (inalterados pela correção — o botão/JS/modal não mudaram, só o conteúdo do PDF que ele baixa).

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
- **Correção — exportação em lote de QR puro (23/09/2026)**: a grade A4 introduzida em 16/09/2026 nunca teve nenhum problema de MEDIDA (a padronização física de 21/09/2026 já tinha corrigido/auditado o tamanho do QR e da célula) — o problema era o FORMATO em si: uma folha A4 com 18 QRs em grade não é o que uma impressora de adesivo, alimentada folha a folha, consegue imprimir sem erro operacional. A correção não mexeu em nenhuma medida (`QR_BATCH_QR_SIZE_MM` reaproveita literalmente `QR_GRID_QR_SIZE_MM=36`) — só trocou "várias colunas numa folha A4" por "1 adesivo por página", o mesmo conceito que as etiquetas já usavam com sucesso. `generate_qr_grid_pdf`/`qr_grid.html` foram deliberadamente MANTIDOS no código (não removidos) em vez de trocados por `generate_qr_batch_pdf`/`qr_batch.html` — mesmo padrão já registrado acima para `generate_qr_zip`: função com cobertura de teste própria, sem chamador ativo, disponível para reuso futuro sem precisar reescrever nada caso um dia um "modo grade opcional" seja pedido de volta.
- Nenhum TODO/FIXME real encontrado.
