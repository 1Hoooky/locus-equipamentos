# apps.qrcodes

## Objetivo

`apps.qrcodes` é um app puramente de **serviço + views de download**: gera, sob demanda e inteiramente em memória, PNG de QR Code, PNG de código de barras (Code128), etiquetas em PDF (padrão antigo 100×50mm e padrão novo 6×6cm), um PDF A4 em grade de QR "puro" por modelo, e exportações em `.zip`/PDF combinado em lote. **Não define landing pública nem admin customizado próprio** — a landing pública do QR e o modal de tema no Django Admin vivem em `apps.equipment`, que só consome `apps.qrcodes.services`/`urls`. O QR sempre codifica só a URL permanente `SITE_BASE_URL + /equipamentos/{patrimonio}/` — nunca dados do equipamento.

## Models

`apps/qrcodes/models.py` está **vazio** — nenhum model. `apps/qrcodes/migrations/` só tem `__init__.py`. O "tema" (light/dark) é um parâmetro transiente de request (`?tema=`), nunca persistido.

## Services

Arquivo: `apps/qrcodes/services.py`. Bibliotecas: `qrcode[pil]`, `Pillow`, `weasyprint`, `python-barcode`.

- `equipment_url(equipment)` — `SITE_BASE_URL + reverse("equipment:detail", patrimonio=...)`.
- `generate_qr_png(equipment)` / `generate_barcode_png(equipment)` (Code128 codificando só o `patrimonio`).
- `generate_label_pdf`/`generate_labels_pdf(equipment_list, theme="light")` — etiqueta **antiga** (100×50mm, com logo/barcode/patrimônio/URL), via `weasyprint.HTML(string=render_to_string(...)).write_pdf()`.
- `generate_square_label_pdf`/`generate_square_labels_pdf(equipment_list, theme)` — etiqueta **nova** 6×6cm: só QR + `model.code` (nunca o nome comercial) + `legacy_code` opcional. Sem logo, sem barcode, sem URL escrita, sem patrimônio.
- `_sanitize_path_segment()` — sanitiza nomes de pasta/arquivo dentro dos `.zip` (proteção contra directory traversal).
- `generate_qr_zip()` (QR "puro"), `generate_labels_zip()` (etiquetas antigas), `generate_square_labels_zip()` (etiquetas novas) — todos `.zip` em memória (disco efêmero do Render free tier).
- `generate_qr_grid_pdf(equipment_list)` (pedido de 16/09/2026, dimensionamento corrigido no mesmo dia após validação física) — **um único PDF A4** com QR "puro" (sem logo/nome/patrimônio/barcode/texto) em grade `QR_GRID_COLUMNS × QR_GRID_ROWS` (3×5, `QR_GRID_PAGE_SIZE=15` por página). Cada QR mede **exatamente `QR_GRID_CELL_SIZE_MM=50` × 50mm** (não uma aproximação — a v1 usava 48mm e foi corrigida), `QR_GRID_GUTTER_MM=5` entre células. A grade inteira (`QR_GRID_WIDTH_MM=160` × `QR_GRID_HEIGHT_MM=270`) é centralizada matematicamente em A4 (`QR_GRID_PAGE_WIDTH_MM=210`×`QR_GRID_PAGE_HEIGHT_MM=297`): `QR_GRID_MARGIN_HORIZONTAL_MM=25` e `QR_GRID_MARGIN_VERTICAL_MM=13.5`, ambas calculadas (`(página - grade) / 2`), nunca hardcoded em paralelo. Reaproveita `generate_qr_png`/`equipment_url` (via `_qr_data_uri`) — a MESMA origem de QR de qualquer outra função deste arquivo, nenhum segundo padrão. Paginação decidida em Python (`_chunked`), nunca deixada para o WeasyPrint resolver sozinho (quebra automática de grid/flex entre páginas não é confiável). Renderiza `templates/qrcodes/qr_grid.html`. Distinta de `generate_qr_zip` (que gera um `.zip` de PNGs soltos, sem paginação/impressão) — aqui o resultado é um documento único.

Nenhuma função grava em disco. Validação de tema é só em `views.py` (whitelist "light"/"dark"); `services.py` nunca valida, confia no chamador.

## Forms

Nenhum form neste app — todas as views são GET puro (download).

## Views

Arquivo: `apps/qrcodes/views.py`. Todas usam `RoleRequiredMixin` com `CAN_MANAGE_EQUIPMENT=(ADMIN,ADMINISTRATIVO)` — **as 8 rotas são privadas**.

| View | Resumo |
|---|---|
| `QRCodeDownloadView` | PNG do QR inline, 1 patrimônio |
| `LabelDownloadView` | PDF etiqueta individual, padrão 6×6 novo, sempre tema light |
| `LabelBatchDownloadView` | PDF combinado, etiqueta antiga; usada pela action do Django Admin |
| `QRCodeZipExportView` | zip de etiquetas 6×6 (apesar do nome "QR Codes") |
| `QRCodeOnlyZipExportView` | zip de QR "puro" |
| `ModelLabelBatchDownloadView` | PDF 6×6 de todos equipamentos ativos de 1 modelo |
| `ModelQRGridDownloadView` | PDF A4 em grade de QR "puro" de todos equipamentos ativos de 1 modelo (16/09/2026) |
| `LabelZipExportView` | zip de etiquetas antigas |

`ModelQRGridDownloadView` espelha exatamente o escopo/permissão/tratamento de 404 de `ModelLabelBatchDownloadView` (mesmo `Equipment.objects.filter(model_id=model_id, is_active=True)`, só acrescentando `order_by("patrimonio")` para ordem determinística — a spec pediu explicitamente ordem determinística, o que `model_label_batch` nunca precisou declarar) — só troca o conteúdo do PDF (`generate_qr_grid_pdf` em vez de `generate_square_labels_pdf`) e o nome do arquivo (`qrcodes-{code}.pdf`). Sem `?tema=` (QR puro não tem etiqueta para ter LIGHT/DARK).

## URLs

`app_name="qrcodes"`, montado como `path("qrcodes/", ...)`. **Todas as 8 rotas são privadas.** A rota realmente pública ligada ao QR físico **não está aqui** — é `equipment:detail` (`/equipamentos/<patrimonio>/`), em `apps.equipment`. `modelo/<int:model_id>/qrcodes.pdf` (`model_qr_grid`) vem antes do catch-all `<str:patrimonio>/...`, mesmo raciocínio defensivo de `modelo/<int:model_id>/etiquetas.pdf`.

## Permissions

`CAN_MANAGE_EQUIPMENT=(ADMIN,ADMINISTRATIVO)` aplicado a todas as views. A rota pública (`equipment:detail`) não usa nenhum mixin — é um `View` puro que ramifica por `is_authenticated` (documentado em `docs/apps/equipment.md`). Validação de tema sempre no backend, nunca confiando só no JS do modal.

## Templates

`templates/qrcodes/label.html` (etiqueta antiga), `label_square.html` (etiqueta nova) e `qr_grid.html` (grade A4 de QR puro, 16/09/2026) — renderizados só internamente via `render_to_string` → WeasyPrint, nunca servidos como página normal. `qr_grid.html` recebe `pages` (lista de páginas já paginadas em Python, cada uma com até `QR_GRID_PAGE_SIZE` células) mais `page_width_mm`/`page_height_mm`/`cell_size_mm`/`gutter_mm`/`margin_horizontal_mm`/`margin_vertical_mm` — nenhuma medida fixa no template, `@page{margin:0}` e toda margem visível vem do `padding` calculado do `.qr-page`. Cada célula tem um campo `caption` (sempre `None` hoje) como ponto de extensão futuro, sem nenhuma opção de UI para preenchê-lo ainda. **Bug corrigido no mesmo dia**: `{{ margin_vertical_mm }}` (13.5, fracionário) renderizava com VÍRGULA decimal por causa de `LANGUAGE_CODE="pt-br"` ("13,5mm", CSS inválido, WeasyPrint ignorava e colapsava a margem para 0 — a causa raiz do "grade deslocada para a esquerda" relatado) — corrigido com `{% load l10n %}{% localize off %}` ao redor do `<style>`.

## JavaScript

Dois arquivos **distintos e não relacionados por herança**, cobrindo o mesmo conceito (modal de tema) em contextos diferentes:

1. **`static/qrcodes/admin/label_theme_modal.js`** (+ `.css`) — carregado **exclusivamente via `ModelAdmin.Media`** de `EquipmentAdmin` (`apps/equipment/admin.py`). **Nenhuma tag `{% static %}` referencia este arquivo em nenhum template** — um audit ingênuo de grep em templates não o encontraria.
2. **`static/qrcodes/label_theme_modal.js`** — arquivo separado, para as páginas normais da aplicação, carregado via `{% static %}` em `templates/equipment/list.html` e `batch_result.html`.

## Admin

`apps/qrcodes/admin.py` está vazio. O modal de tema é customização de **`EquipmentAdmin`** (`apps.equipment`): `qr_etiqueta_links` (links para `qrcodes:qr_png`/`label_pdf`), action `download_labels_pdf` (redireciona para `qrcodes:label_batch`), `class Media` (injeta o JS/CSS do item 1 acima só na changelist de Equipment).

## Dependências

`apps.equipment.models.Equipment`; `apps.catalog.models.EquipmentModel`; `apps.accounts.permissions`; `settings.SITE_BASE_URL`; bibliotecas `qrcode`, `Pillow`, `weasyprint`, `barcode`.

## Quem chama apps.qrcodes

`apps.equipment.admin` (links, redirect, `LABEL_THEME_LIGHT`, assets do modal); templates de `apps.equipment` (`list.html`, `batch_result.html`, `_model_group_items.html`, `detail_private.html`). `list.html` também tem o botão novo "Exportar QR Codes em PDF" (`qrcodes:model_qr_grid`), sibling do botão "Etiquetas em lote" já existente, dentro do mesmo `.model-group-card` (agrupados num wrapper `.action-group`, 16/09/2026). Nenhum outro app (`clients`, `operations`, `maintenance`, `crm`, `dashboard`, `catalog`) referencia `qrcodes` diretamente.

## Testes

`apps/qrcodes/tests/test_qr_and_labels.py` — cobertura ampla: QR/barcode válidos e decodificáveis, conteúdo do PDF nos dois temas, etiqueta quadrada nunca expõe nome comercial/patrimônio/URL, sanitização de path contra directory traversal, geração não escreve em disco, permissões (Admin/Administrativo podem, Operacional/Consulta proibidos). Mais `apps/equipment/tests/test_admin_label_theme_action.py` (confirma via `assertContains` que os assets do `Media` estão na changelist) e `test_equipment_grouped_listing.py` (confirma o JS de app na listagem).

`apps/qrcodes/tests/test_qr_grid_export.py` (16/09/2026) — `ModelQRGridDownloadViewTest`: permissão (backend, igual a `model_label_batch`), 200/`Content-Type: application/pdf`, 1 QR por equipamento (lote único e grande/multi-página), o QR embutido decodifica para a MESMA URL/bytes de `generate_qr_png`/`equipment_url` (nenhum segundo padrão), sem mistura de escopo (outro modelo/inativo nunca aparece), ordem determinística por `patrimonio`, ausência total de efeito colateral (`Equipment`/`Movement`/`StatusHistory`/`ConditionHistory`/`Attachment` inalterados), nome de arquivo (`qrcodes-{code}.pdf`), PDF sem nenhum texto (QR puro), 404 de modelo inexistente/sem equipamento ativo. `ModelQRGridPhysicalDimensionsTest` (mesmo arquivo, adicionada na correção de dimensionamento do mesmo dia) mede posição/tamanho de cada imagem embutida direto do conteúdo do PDF via `pdfplumber` (em mm, não por screenshot): página A4 210×297mm, cada QR exatamente 50×50mm (nunca mais 48mm), gutter uniforme de 5mm entre colunas/linhas, grade centralizada horizontalmente (margem esquerda = margem direita = 25mm) e verticalmente (13.5mm), nenhuma página extra para lotes que fecham em múltiplos exatos de 15, múltiplas páginas nos exemplos do pedido (16→2, 31→3), página incompleta preenchendo em ordem de leitura sem redistribuir/centralizar os itens entre si.

## Migrations

Nenhuma — `apps/qrcodes/migrations/` só tem `__init__.py` (reflexo de não haver models).

## Pontos importantes

- **Segurança da rota pública** vive em `apps.equipment`, não aqui — `.only(...)` no queryset garante em nível de banco que campos operacionais/comerciais nunca saem na consulta anônima.
- **Duas gerações de etiqueta coexistem deliberadamente, nunca unificadas** — reaproveitar a mesma função faria um botão existente mudar de formato sem ter sido pedido.
- **`generate_qr_zip` ficou "órfã" por um tempo** (08/09 a 10/09/2026) até ganhar um chamador de volta (`QRCodeOnlyZipExportView`) — mantida porque tinha cobertura de teste.
- **Validação de tema é redundante por design**: front-end evita esquecimento, back-end (`_validated_theme`) é a única barreira real contra tema forjado via querystring/POST.
- **`generate_qr_grid_pdf`/`model_qr_grid` (16/09/2026) foi escopado ao lote POR MODELO** (mesma queryset de `ModelLabelBatchDownloadView`), não ao lote "todos os equipamentos ativos" do toolbar (`_active_equipment_for_export`/`QRCodeOnlyZipExportView`) — decisão inferida do exemplo concreto do pedido original (card de 1 modelo específico), não reconfirmada explicitamente. Se um QR grid em PDF do escopo do toolbar também for desejado, é uma extensão futura, não implementada nesta rodada.
- Nenhum TODO/FIXME real encontrado.
