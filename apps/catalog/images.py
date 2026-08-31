"""
Mapeamento centralizado de EquipmentModel -> imagem comercial estática.

Contexto (etapa de UX/UI, 28/08/2026 — ver AUDITORIA_UX_HOME_NAVEGACAO_QR.md,
itens [9]/[10]): a landing pública do QR (`templates/equipment/
detail_public.html`) precisa mostrar uma imagem grande do MODELO do
equipamento, não do equipamento individual (todas as unidades do mesmo
modelo reusam a mesma imagem comercial). Decisões aprovadas:

- Sem migration, sem campo novo de banco, sem upload, sem S3, sem
  filesystem de mídia do Render — as imagens são arquivos WEBP versionados
  com o próprio projeto, em `static/images/equipment/`.
- Sem `{% if model.code == "..." %}{% elif %}` espalhado por template — só
  este dicionário, mais a template tag em
  `apps/catalog/templatetags/model_images.py`.
- `EquipmentModel.code` é a chave: já é único, validado por regex
  (`^[A-Z0-9]{2,20}$`, portanto seguro como nome de arquivo) e travado para
  edição assim que o modelo tem equipamento vinculado (`EquipmentModel.
  clean()`) — não muda silenciosamente debaixo do mapeamento.
- Um modelo sem entrada aqui (ou cujo arquivo não existir de fato em
  `static/`) SEMPRE cai no placeholder — a página nunca pode quebrar nem
  mostrar um ícone de imagem quebrada. A checagem de existência real do
  arquivo é feita pela template tag (`model_images.py`), não aqui: este
  módulo só decide o CAMINHO pretendido.

IMPORTANTE (decisão aprovada 28/08/2026): a ausência dos arquivos WEBP
finais não pode bloquear esta implementação. Os nomes abaixo são a
estrutura conceitual dada pela Locus; os arquivos reais chegam depois,
substituindo gradualmente o placeholder — sem qualquer mudança de código
quando isso acontecer, só adicionando o arquivo em `static/images/
equipment/` com o nome já mapeado aqui (ou adicionando uma nova entrada no
dicionário, para um `code` que ainda não tem linha).
"""

from apps.catalog.models import EquipmentModel

# code (EquipmentModel.code, já normalizado para maiúsculas por
# EquipmentModel.clean()) -> caminho relativo dentro de STATICFILES_DIRS,
# pronto para `{% static %}`.
#
# Estrutura conceitual pedida pela Locus (auditoria, item [9]). Os `code`
# reais de cada modelo são cadastrados pela equipe em Catálogo > Modelos —
# esta tabela só precisa ser mantida em sincronia manualmente quando um
# novo modelo comercial ganhar uma foto de catálogo. Nenhum destes valores
# foi inventado como dado de equipamento: são só nomes de arquivo.
MODEL_IMAGE_MAP: dict[str, str] = {
    "9PRO": "images/equipment/9pro.webp",
    "9PRO2": "images/equipment/9pro.webp",
    "6PRO": "images/equipment/6pro.webp",
    "AQCP": "images/equipment/aqcp.webp",
    "AQCT": "images/equipment/aqct.webp",
    "AQCH": "images/equipment/aqch.webp",
    "NI23BT": "images/equipment/ni23bt.webp",
    "NI23TC": "images/equipment/ni23tc.webp",
}

PLACEHOLDER_IMAGE = "images/equipment/_placeholder.webp"


def get_model_image_path(model: "EquipmentModel | None") -> str:
    """
    Caminho ESTÁTICO PRETENDIDO para a imagem comercial do modelo — sem
    checar se o arquivo existe de verdade em disco (isso é
    responsabilidade da template tag `model_image_url`, que é quem
    efetivamente decide se cai no placeholder). `model=None` (defensivo,
    não deve acontecer com `Equipment.model` sendo `on_delete=PROTECT`)
    também cai no placeholder.
    """

    if model is None or not model.code:
        return PLACEHOLDER_IMAGE
    return MODEL_IMAGE_MAP.get(model.code.upper(), PLACEHOLDER_IMAGE)
