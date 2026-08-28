"""
Mapeamento EquipmentModel -> imagem comercial estática (etapa de UX/UI,
28/08/2026 — ver AUDITORIA_UX_HOME_NAVEGACAO_QR.md, itens [9]/[10]).

Cobre as duas camadas: `apps.catalog.images` (o dicionário/decisão de
caminho pretendido) e a template tag `apps.catalog.templatetags.
model_images` (que confirma existência real do arquivo e cai no
placeholder quando o WEBP ainda não foi enviado pela Locus — cenário
esperado nesta etapa).
"""

from django.template import Context, Template
from django.test import TestCase

from apps.catalog.images import MODEL_IMAGE_MAP, PLACEHOLDER_IMAGE, get_model_image_path
from apps.catalog.models import Category, EquipmentModel
from apps.catalog.templatetags.model_images import (
    _resolve_existing_static_path,
    model_has_commercial_image,
    model_image_url,
)


class GetModelImagePathTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Aquecedor")

    def test_mapped_code_returns_its_configured_path(self):
        model = EquipmentModel.objects.create(category=self.category, name="Aquecedor Pirâmide", code="AQCP")
        self.assertEqual(get_model_image_path(model), MODEL_IMAGE_MAP["AQCP"])

    def test_unmapped_code_falls_back_to_placeholder(self):
        model = EquipmentModel.objects.create(category=self.category, name="Modelo Sem Foto", code="ZZNOFOTO")
        self.assertEqual(get_model_image_path(model), PLACEHOLDER_IMAGE)

    def test_none_model_falls_back_to_placeholder(self):
        self.assertEqual(get_model_image_path(None), PLACEHOLDER_IMAGE)


class ModelImageUrlTemplateTagTest(TestCase):
    """
    A página nunca pode quebrar por falta de arquivo (decisão aprovada,
    item [4]) — `model_image_url` sempre devolve uma URL estática válida,
    apontando para um arquivo que existe de fato em disco.
    """

    def setUp(self):
        self.category = Category.objects.create(name="Aquecedor")
        # Limpa o cache do resolvedor entre testes — ele é cacheado por
        # processo (lru_cache) para não bater no filesystem a cada
        # request na landing pública (auditoria, item [17]).
        _resolve_existing_static_path.cache_clear()

    def test_model_with_no_real_file_on_disk_resolves_to_placeholder_url(self):
        # "AQCP" está mapeado em MODEL_IMAGE_MAP, mas o arquivo
        # 9pro.webp/aqcp.webp real ainda não foi enviado pela Locus nesta
        # etapa — só o placeholder de desenvolvimento existe em disco.
        model = EquipmentModel.objects.create(category=self.category, name="Aquecedor Pirâmide", code="AQCP")
        url = model_image_url(model)
        self.assertIn("_placeholder.webp", url)
        self.assertFalse(model_has_commercial_image(model))

    def test_none_model_resolves_to_placeholder_url_without_raising(self):
        url = model_image_url(None)
        self.assertIn("_placeholder.webp", url)

    def test_url_is_a_valid_static_url(self):
        model = EquipmentModel.objects.create(category=self.category, name="Modelo Qualquer", code="QQ1")
        url = model_image_url(model)
        self.assertTrue(url.startswith("/static/"))


class ModelImageUrlInTemplateTest(TestCase):
    """Confirma que a tag funciona de dentro de um template real (com {% load %})."""

    def setUp(self):
        _resolve_existing_static_path.cache_clear()

    def test_tag_renders_inside_template(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQCT")

        template = Template("{% load model_images %}{% model_image_url model %}")
        rendered = template.render(Context({"model": model}))

        self.assertIn("/static/", rendered)
        self.assertTrue(rendered.strip())
