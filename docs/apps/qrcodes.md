# apps.qrcodes

## Objetivo

`apps.qrcodes` é um app puramente de **serviço + views de download**: gera, sob demanda e inteiramente em memória, PNG de QR Code, PNG de código de barras (Code128), etiquetas em PDF (padrão antigo 100×50mm e padrão novo 6×6cm) e exportações em `.zip`/PDF combinado em lote. **Não define landing pública nem admin customizado próprio** — a landing pública do QR e o modal de tema no Django Admin vivem em `apps.equipment`, que só consome `apps.qrcodes.services`/`urls`. O QR sempre codifica só a URL permanente `SITE_BASE_URL + /equipamentos/{patrimonio}/` — nunca dados do equipamento.

## Models

`apps/qrcodes/models.py` está **vazio** — nenhum model. `apps/qrcodes/migrations/` só tem `__init__.py`. O "tema" (light/dark) é um parâmetro transiente de request (`?tema=`), nunca persistido.

## Services

Arquivo: `apps/qrcodes/services.py` (354 linhas). Bibliotecas: `qrcode[pil]`, `Pillow`, `weasyprint`, `python-barcode`.

- `equipment_url(equipment)` — `SITE_BASE_URL + reverse("equipment:detail", patrimonio=...)`.
- `generate_qr_png(equipment)` / `generate_barcode_png(equipment)` (Code128 codificando só o `patrimonio`).
- `generate_label_pdf`/`generate_labels_pdf(equipment_list, theme="light")` — etiqueta **antiga** (100×50mm, com logo/barcode/patrimônio/URL), via `weasyprint.HTML(string=render_to_string(...)).write_pdf()`.
- `generate_square_label_pdf`/`generate_square_labels_pdf(equipment_list, theme)` — etiqueta **nova** 6×6cm: só QR + `model.code` (nunca o nome comercial) + `legacy_code` opcional. Sem logo, sem barcode, sem URL escrita, sem patrimônio.
- `_sanitize_path_segment()` — sanitiza nomes de pasta/arquivo dentro dos `.zip` (proteção contra directory traversal).
- `generate_qr_zip()` (QR "puro"), `generate_labels_zip()` (etiquetas antigas), `generate_square_labels_zip()` (etiquetas novas) — todos `.zip` em memória (disco efêmero do Render free tier).

Nenhuma função grava em disco. Validação de tema é só em `views.py` (whitelist "light"/"dark"); `services.py` nunca valida, confia no chamador.

## Forms

Nenhum form neste app — todas as views são GET puro (download).

## Views

Arquivo: `apps/qrcodes/views.py` (277 linhas). Todas usam `RoleRequiredMixin` com `CAN_MANAGE_EQUIPMENT=(ADMIN,ADMINISTRATIVO)` — **as 7 rotas são privadas**.

| View | Resumo |
|---|---|
| `QRCodeDownloadView` | PNG do QR inline, 1 patrimônio |
| `LabelDownloadView` | PDF etiqueta individual, padrão 6×6 novo, sempre tema light |
| `LabelBatchDownloadView` | PDF combinado, etiqueta antiga; usada pela action do Django Admin |
| `QRCodeZipExportView` | zip de etiquetas 6×6 (apesar do nome "QR Codes") |
| `QRCodeOnlyZipExportView` | zip de QR "puro" |
| `ModelLabelBatchDownloadView` | PDF 6×6 de todos equipamentos ativos de 1 modelo |
| `LabelZipExportView` | zip de etiquetas antigas |

## URLs

`app_name="qrcodes"`, montado como `path("qrcodes/", ...)`. **Todas as 7 rotas são privadas.** A rota realmente pública ligada ao QR físico **não está aqui** — é `equipment:detail` (`/equipamentos/<patrimonio>/`), em `apps.equipment`.

## Permissions

`CAN_MANAGE_EQUIPMENT=(ADMIN,ADMINISTRATIVO)` aplicado a todas as views. A rota pública (`equipment:detail`) não usa nenhum mixin — é um `View` puro que ramifica por `is_authenticated` (documentado em `docs/apps/equipment.md`). Validação de tema sempre no backend, nunca confiando só no JS do modal.

## Templates

`templates/qrcodes/label.html` (etiqueta antiga) e `label_square.html` (etiqueta nova) — renderizados só internamente via `render_to_string` → WeasyPrint, nunca servidos como página normal.

## JavaScript

Dois arquivos **distintos e não relacionados por herança**, cobrindo o mesmo conceito (modal de tema) em contextos diferentes:

1. **`static/qrcodes/admin/label_theme_modal.js`** (+ `.css`) — carregado **exclusivamente via `ModelAdmin.Media`** de `EquipmentAdmin` (`apps/equipment/admin.py`). **Nenhuma tag `{% static %}` referencia este arquivo em nenhum template** — um audit ingênuo de grep em templates não o encontraria.
2. **`static/qrcodes/label_theme_modal.js`** — arquivo separado, para as páginas normais da aplicação, carregado via `{% static %}` em `templates/equipment/list.html` e `batch_result.html`.

## Admin

`apps/qrcodes/admin.py` está vazio. O modal de tema é customização de **`EquipmentAdmin`** (`apps.equipment`): `qr_etiqueta_links` (links para `qrcodes:qr_png`/`label_pdf`), action `download_labels_pdf` (redireciona para `qrcodes:label_batch`), `class Media` (injeta o JS/CSS do item 1 acima só na changelist de Equipment).

## Dependências

`apps.equipment.models.Equipment`; `apps.catalog.models.EquipmentModel`; `apps.accounts.permissions`; `settings.SITE_BASE_URL`; bibliotecas `qrcode`, `Pillow`, `weasyprint`, `barcode`.

## Quem chama apps.qrcodes

`apps.equipment.admin` (links, redirect, `LABEL_THEME_LIGHT`, assets do modal); templates de `apps.equipment` (`list.html`, `batch_result.html`, `_model_group_items.html`, `detail_private.html`). Nenhum outro app (`clients`, `operations`, `maintenance`, `crm`, `dashboard`, `catalog`) referencia `qrcodes` diretamente.

## Testes

`apps/qrcodes/tests/test_qr_and_labels.py` (1012 linhas) — cobertura ampla: QR/barcode válidos e decodificáveis, conteúdo do PDF nos dois temas, etiqueta quadrada nunca expõe nome comercial/patrimônio/URL, sanitização de path contra directory traversal, geração não escreve em disco, permissões (Admin/Administrativo podem, Operacional/Consulta proibidos). Mais `apps/equipment/tests/test_admin_label_theme_action.py` (confirma via `assertContains` que os assets do `Media` estão na changelist) e `test_equipment_grouped_listing.py` (confirma o JS de app na listagem).

## Migrations

Nenhuma — `apps/qrcodes/migrations/` só tem `__init__.py` (reflexo de não haver models).

## Pontos importantes

- **Segurança da rota pública** vive em `apps.equipment`, não aqui — `.only(...)` no queryset garante em nível de banco que campos operacionais/comerciais nunca saem na consulta anônima.
- **Duas gerações de etiqueta coexistem deliberadamente, nunca unificadas** — reaproveitar a mesma função faria um botão existente mudar de formato sem ter sido pedido.
- **`generate_qr_zip` ficou "órfã" por um tempo** (08/09 a 10/09/2026) até ganhar um chamador de volta (`QRCodeOnlyZipExportView`) — mantida porque tinha cobertura de teste.
- **Validação de tema é redundante por design**: front-end evita esquecimento, back-end (`_validated_theme`) é a única barreira real contra tema forjado via querystring/POST.
- Nenhum TODO/FIXME real encontrado.
