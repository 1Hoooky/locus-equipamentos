"""
Landing pública/comercial do QR Code (etapa de UX/UI, 28/08/2026 — ver
AUDITORIA_UX_HOME_NAVEGACAO_QR.md). Complementa (não substitui)
`test_public_detail_view.py`/`test_public_detail_no_operational_leak.py`,
que já cobrem o risco de vazamento de dado sensível. Este arquivo cobre a
experiência comercial em si: imagem, CTAs configuráveis, alt text,
ausência de custo de N+1.
"""

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase, override_settings

from apps.catalog.models import Category, EquipmentModel
from apps.catalog.templatetags.model_images import _resolve_existing_static_path
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()


class PublicLandingBasicContentTest(TestCase):
    def setUp(self):
        _resolve_existing_static_path.cache_clear()
        category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(
            category=category, name="Climatizador 9PRO", code="9PRO", manufacturer="Locus Locações"
        )
        creator = User.objects.create_user(username="cadastrador_landing", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=creator))

    def _get(self):
        return self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")

    def test_landing_loads_with_public_base(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "equipment/detail_public.html")
        self.assertTemplateUsed(response, "base_public.html")
        self.assertTemplateNotUsed(response, "base.html")

    def test_patrimonio_is_present(self):
        content = self._get().content.decode()
        self.assertIn(self.equipment.patrimonio, content)

    def test_model_name_is_present(self):
        content = self._get().content.decode()
        self.assertIn("Climatizador 9PRO", content)

    def test_manufacturer_shown_when_present(self):
        content = self._get().content.decode()
        self.assertIn("Locus Locações", content)

    def test_manufacturer_hidden_when_blank(self):
        category = Category.objects.create(name="Aquecedor")
        model_no_manufacturer = EquipmentModel.objects.create(category=category, name="Aquecedor Sem Fabricante", code="AQSF")
        creator = User.objects.get(username="cadastrador_landing")
        equipment = create_equipment(NewEquipmentData(model_id=model_no_manufacturer.pk, created_by=creator))

        response = self.client.get(f"/equipamentos/{equipment.patrimonio}/")
        self.assertNotContains(response, "Fabricante:")

    def test_image_tag_has_no_lazy_loading_and_has_fetchpriority(self):
        """Item [2] do briefing aprovado: imagem principal sem lazy loading, com fetchpriority alto."""
        content = self._get().content.decode()
        self.assertIn('fetchpriority="high"', content)
        self.assertNotIn('loading="lazy"', content)

    def test_image_has_descriptive_alt_text(self):
        content = self._get().content.decode()
        self.assertIn("Climatizador 9PRO", content.split("<img")[1].split(">")[0])

    def test_image_src_points_to_an_existing_static_file(self):
        """
        "9PRO" está mapeado em MODEL_IMAGE_MAP, mas o arquivo real
        (9pro.webp) ainda não foi enviado pela Locus nesta etapa — a
        página precisa cair no placeholder, nunca numa imagem quebrada.
        """
        content = self._get().content.decode()
        self.assertIn("_placeholder.webp", content)

    def test_no_operational_or_administrative_labels_leak(self):
        content = self._get().content.decode()
        for forbidden in ("Cliente atual", "Localização atual", "Fornecedor", "Ações operacionais", "Histórico do equipamento"):
            self.assertNotIn(forbidden, content)


class PublicLandingQueryBudgetTest(TestCase):
    """
    Item [17]/[24] do briefing: a landing pública pode receber mais
    tráfego anônimo que o resto do sistema — o número de queries não pode
    crescer, e precisa ficar travado por teste (regressão de N+1 aqui
    seria especialmente cara).
    """

    def setUp(self):
        category = Category.objects.create(name="Climatizador")
        model = EquipmentModel.objects.create(category=category, name="Climatizador 6PRO", code="6PRO")
        creator = User.objects.create_user(username="cadastrador_budget", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

    def test_query_count_is_stable_and_low(self):
        # 1 query: Equipment + select_related(model, category) num único
        # JOIN. Nenhuma consulta a cliente/localização/manutenção
        # /histórico — essas nunca são feitas na rota pública (defesa em
        # profundidade, EquipmentDetailView._get_public_equipment).
        with self.assertNumQueries(1):
            self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")


class CommercialLinksCtaVisibilityTest(TestCase):
    """
    Item [9]/[10] do briefing: cada CTA só aparece se a URL correspondente
    estiver configurada (settings + apps.core.context_processors.
    commercial_links) — nunca um link vazio/`href="#"`.
    """

    def setUp(self):
        category = Category.objects.create(name="Climatizador")
        model = EquipmentModel.objects.create(category=category, name="Climatizador NI23", code="NI23")
        creator = User.objects.create_user(username="cadastrador_cta", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

    def _get(self):
        return self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")

    @override_settings(
        LOCUS_ORCAMENTO_URL="https://wa.me/5511999990000?text=orcamento",
        LOCUS_WHATSAPP_URL="",
        LOCUS_INSTAGRAM_URL="",
        LOCUS_SITE_URL="",
        LOCUS_EQUIPAMENTOS_URL="",
    )
    def test_configured_cta_is_rendered(self):
        content = self._get().content.decode()
        self.assertIn("https://wa.me/5511999990000?text=orcamento", content)
        self.assertIn("Faça seu orçamento", content)

    @override_settings(
        LOCUS_ORCAMENTO_URL="",
        LOCUS_WHATSAPP_URL="",
        LOCUS_INSTAGRAM_URL="",
        LOCUS_SITE_URL="",
        LOCUS_EQUIPAMENTOS_URL="",
    )
    def test_unconfigured_ctas_are_never_rendered_and_no_broken_href(self):
        # Só o <body> importa aqui: o <head> inclui o partial de tokens
        # compartilhado (_design_tokens.html), cujo CSS tem um comentário
        # de código mencionando "Faça seu orçamento" como documentação da
        # classe .btn-cta-primary — não é conteúdo visível, então checar
        # o documento inteiro daria falso positivo.
        content = self._get().content.decode()
        body = content.split("<body", 1)[1]
        self.assertNotIn("Faça seu orçamento", body)
        self.assertNotIn("Falar com a Locus", body)
        self.assertNotIn("Conheça nosso Instagram", body)
        self.assertNotIn("Conheça nosso site", body)
        self.assertNotIn("Conheça nossos equipamentos", body)
        self.assertNotIn('href="#"', body)
        # Título da pequena área comercial (WhatsApp/Instagram) também não
        # deve sobrar sozinho quando os dois estão vazios.
        self.assertNotIn("Precisa de climatização para seu espaço?", body)

    @override_settings(
        LOCUS_ORCAMENTO_URL="https://wa.me/5511999990000",
        LOCUS_WHATSAPP_URL="https://wa.me/5511988880000",
        LOCUS_INSTAGRAM_URL="https://instagram.com/locuslocacoes",
        LOCUS_SITE_URL="https://locuslocacoes.com.br",
        LOCUS_EQUIPAMENTOS_URL="https://locuslocacoes.com.br/equipamentos",
    )
    def test_all_five_ctas_render_when_fully_configured(self):
        content = self._get().content.decode()
        for expected_url in (
            "https://wa.me/5511999990000",
            "https://wa.me/5511988880000",
            "https://instagram.com/locuslocacoes",
            "https://locuslocacoes.com.br",
            "https://locuslocacoes.com.br/equipamentos",
        ):
            self.assertIn(expected_url, content)


class PublicLandingCommercialAreaTest(TestCase):
    """
    Pequena área comercial (WhatsApp/Instagram) da landing pública —
    alteração cirúrgica de 31/08/2026. Reaproveita EXATAMENTE
    `commercial_links.whatsapp`/`commercial_links.instagram`
    (settings.LOCUS_WHATSAPP_URL/LOCUS_INSTAGRAM_URL via
    apps.core.context_processors.commercial_links) — nenhuma
    configuração nova. Complementa `CommercialLinksCtaVisibilityTest`
    acima (que já cobre a visibilidade condicional dos 5 CTAs em
    conjunto); este arquivo foca no que É NOVO: o título da área só
    aparece com pelo menos um CTA, segurança dos links externos, e que
    o query budget da landing não muda com a reorganização.
    """

    def setUp(self):
        category = Category.objects.create(name="Climatizador Área Comercial")
        model = EquipmentModel.objects.create(category=category, name="Climatizador AC01", code="AC01")
        creator = User.objects.create_user(username="cadastrador_area_comercial", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

    def _get(self):
        return self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")

    @override_settings(LOCUS_WHATSAPP_URL="https://wa.me/5511988880000", LOCUS_INSTAGRAM_URL="")
    def test_whatsapp_configurado_aparece(self):
        content = self._get().content.decode()
        self.assertIn("Falar com a Locus", content)
        self.assertIn("https://wa.me/5511988880000", content)

    @override_settings(LOCUS_WHATSAPP_URL="", LOCUS_INSTAGRAM_URL="")
    def test_whatsapp_vazio_nao_aparece(self):
        content = self._get().content.decode()
        self.assertNotIn("Falar com a Locus", content)

    @override_settings(LOCUS_WHATSAPP_URL="", LOCUS_INSTAGRAM_URL="https://instagram.com/locuslocacoes")
    def test_instagram_configurado_aparece(self):
        content = self._get().content.decode()
        self.assertIn("Conheça nosso Instagram", content)
        self.assertIn("https://instagram.com/locuslocacoes", content)

    @override_settings(LOCUS_WHATSAPP_URL="", LOCUS_INSTAGRAM_URL="")
    def test_instagram_vazio_nao_aparece(self):
        content = self._get().content.decode()
        self.assertNotIn("Conheça nosso Instagram", content)

    @override_settings(LOCUS_WHATSAPP_URL="", LOCUS_INSTAGRAM_URL="")
    def test_ambos_vazios_nao_deixa_titulo_da_area_sem_ctas(self):
        # O título ("Precisa de climatização...") é específico DESSA área —
        # não pode sobrar sozinho, sem nenhum botão embaixo, quando os
        # dois canais estão desconfigurados.
        content = self._get().content.decode()
        self.assertNotIn("Precisa de climatização", content)

    @override_settings(LOCUS_WHATSAPP_URL="https://wa.me/5511988880000", LOCUS_INSTAGRAM_URL="")
    def test_titulo_da_area_aparece_com_pelo_menos_um_ctas(self):
        content = self._get().content.decode()
        self.assertIn("Precisa de climatização", content)

    @override_settings(
        LOCUS_WHATSAPP_URL="https://wa.me/5511977776666",
        LOCUS_INSTAGRAM_URL="https://instagram.com/outraconta",
    )
    def test_href_usa_exatamente_o_valor_configurado_sem_hardcode(self):
        content = self._get().content.decode()
        self.assertIn('href="https://wa.me/5511977776666"', content)
        self.assertIn('href="https://instagram.com/outraconta"', content)

    @override_settings(
        LOCUS_WHATSAPP_URL="https://wa.me/5511988880000",
        LOCUS_INSTAGRAM_URL="https://instagram.com/locuslocacoes",
    )
    def test_links_externos_usam_target_blank_e_rel_noopener(self):
        # A mesma URL de WhatsApp também aparece no menu público
        # (base_public.html, fora do escopo desta alteração) — por isso
        # localizamos a âncora pelo texto NOVO ("Falar com a Locus"),
        # específico da área comercial da landing, e não pela primeira
        # ocorrência do href na página.
        content = self._get().content.decode()
        whatsapp_text_pos = content.find("Falar com a Locus")
        whatsapp_anchor_start = content.rfind("<a ", 0, whatsapp_text_pos)
        whatsapp_anchor = content[whatsapp_anchor_start:whatsapp_text_pos]

        instagram_text_pos = content.find("Conheça nosso Instagram")
        instagram_anchor_start = content.rfind("<a ", 0, instagram_text_pos)
        instagram_anchor = content[instagram_anchor_start:instagram_text_pos]

        for anchor in (whatsapp_anchor, instagram_anchor):
            self.assertIn('target="_blank"', anchor)
            self.assertIn("noopener", anchor)

    @override_settings(
        LOCUS_WHATSAPP_URL="https://wa.me/5511988880000",
        LOCUS_INSTAGRAM_URL="https://instagram.com/locuslocacoes",
    )
    def test_whatsapp_e_visualmente_mais_destacado_que_instagram(self):
        # WhatsApp usa a mesma base visual do CTA principal (.btn-cta-whatsapp,
        # fundo dourado sólido) — Instagram continua em .btn-cta-secondary
        # (mesma classe já usada para os outros CTAs de menor ênfase).
        content = self._get().content.decode()
        self.assertIn("btn-cta-whatsapp", content)
        self.assertIn("btn-cta-secondary", content)

    @override_settings(
        LOCUS_WHATSAPP_URL="https://wa.me/5511988880000",
        LOCUS_INSTAGRAM_URL="https://instagram.com/locuslocacoes",
    )
    def test_usuario_anonimo_continua_recebendo_a_landing_publica(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "equipment/detail_public.html")

    @override_settings(
        LOCUS_WHATSAPP_URL="https://wa.me/5511988880000",
        LOCUS_INSTAGRAM_URL="https://instagram.com/locuslocacoes",
    )
    def test_landing_continua_sem_dado_operacional_com_os_novos_ctas(self):
        content = self._get().content.decode()
        for forbidden in ("Cliente atual", "Localização atual", "Fornecedor", "Ações operacionais", "Histórico do equipamento"):
            self.assertNotIn(forbidden, content)

    @override_settings(
        LOCUS_WHATSAPP_URL="https://wa.me/5511988880000",
        LOCUS_INSTAGRAM_URL="https://instagram.com/locuslocacoes",
    )
    def test_query_budget_nao_aumenta_com_os_novos_ctas(self):
        # Os CTAs dependem só de settings/context processor — nenhuma
        # consulta nova ao banco. Mesmo teto de sempre (1 query).
        with self.assertNumQueries(1):
            self._get()


class DesignTokensSharedAcrossBasesTest(TestCase):
    """
    Item [16] do briefing: base.html e base_public.html compartilham o
    mesmo partial de tokens (`templates/_design_tokens.html`), sem
    duplicar o bloco @layer components inteiro em dois arquivos.
    """

    def test_public_base_includes_shared_design_tokens(self):
        rendered = render_to_string("base_public.html")
        self.assertIn("brand-gold", rendered)
        self.assertIn("btn-cta-primary", rendered)

    def test_internal_base_still_includes_shared_design_tokens(self):
        rendered = render_to_string("base.html")
        self.assertIn("brand-gold", rendered)
        self.assertIn(".btn-primary", rendered)
