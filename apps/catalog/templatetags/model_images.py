"""
Template tag da landing pública (`equipment/detail_public.html`) para
resolver a imagem comercial de um `EquipmentModel` — ver
`apps/catalog/images.py` para a decisão de arquitetura completa (sem
migration, sem upload, mapeamento por `EquipmentModel.code`).

Diferença deliberada em relação a `images.py::get_model_image_path()`:
aqui a gente CONFIRMA que o arquivo existe de verdade em disco antes de
apontar para ele. Isso é o que garante a regra aprovada "a landing nunca
pode exibir imagem quebrada" mesmo que o dicionário `MODEL_IMAGE_MAP`
tenha uma entrada para um arquivo que ainda não foi enviado pela Locus
(cenário esperado nesta etapa — a estrutura foi preparada antes das fotos
finais existirem).
"""

from functools import lru_cache

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static as static_url

from apps.catalog.images import PLACEHOLDER_IMAGE, get_model_image_path

register = template.Library()


@lru_cache(maxsize=256)
def _resolve_existing_static_path(candidate: str) -> str:
    """
    Devolve `candidate` se o arquivo existir de fato em algum
    STATICFILES_DIRS/`static/` de app, senão devolve o placeholder.
    `finders.find()` procura nas pastas de ORIGEM (não depende de
    `collectstatic` já ter rodado), então funciona igual em dev e straight
    do checkout do repositório.

    Cacheado em processo (`lru_cache`): esta função é chamada na landing
    pública, que pode receber tráfego anônimo maior que o resto do sistema
    (auditoria, item [17] — "performance da landing pública") — evita
    bater no filesystem a cada request para o mesmo modelo. O processo
    precisa ser reiniciado para enxergar um WEBP novo adicionado depois do
    deploy, o que já é o comportamento normal de deploy do projeto.
    """

    if candidate != PLACEHOLDER_IMAGE and finders.find(candidate):
        return candidate
    return PLACEHOLDER_IMAGE


@register.simple_tag
def model_image_url(model):
    """
    Uso: {% model_image_url equipment.model %}

    Sempre devolve uma URL estática válida — nunca None, nunca um caminho
    para um arquivo que não existe. `model=None` (defensivo) cai no
    placeholder, do mesmo jeito que um modelo sem entrada no mapeamento ou
    com entrada apontando para um WEBP ainda não enviado.
    """

    candidate = get_model_image_path(model)
    resolved = _resolve_existing_static_path(candidate)
    return static_url(resolved)


@register.simple_tag
def model_has_commercial_image(model):
    """
    Uso: {% model_has_commercial_image equipment.model as has_real_image %}

    True só quando o modelo tem uma imagem comercial REAL (não o
    placeholder) — não usado na primeira versão da landing (que sempre
    mostra alguma imagem, real ou placeholder), mas exposto para casos
    futuros em que o comportamento precise diferenciar os dois (ex.:
    Open Graph só com foto real).
    """

    candidate = get_model_image_path(model)
    return _resolve_existing_static_path(candidate) != PLACEHOLDER_IMAGE
