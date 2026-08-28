"""
Regressão: comentários Django multi-linha vazando como texto literal na
página renderizada (rodada CORRETIVA de UX/UI — homologação no Render).

Causa raiz (confirmada lendo o lexer do próprio Django,
`django/template/base.py`): `tag_re = re.compile(r"({%.*?%}|{{.*?}}|{#.*?#})")`
é compilado SEM `re.DOTALL`, então `{# ... #}` só é reconhecido como tag
quando abre e fecha na MESMA linha. Um `{# #}` escrito ocupando várias
linhas nunca "casa" com o regex: o `{#` e tudo que vem depois — inclusive
o `#}` que deveria fechá-lo — vira TextNode literal, impresso do jeito que
está na tela. Foi exatamente isso que apareceu no topo da tela de
Equipamentos e da landing pública em produção.

Encontradas (varredura completa de `templates/**/*.html`, não só dos
arquivos tocados na etapa anterior) exatamente duas ocorrências:
`templates/base.html` (drawer do menu mobile) e `templates/base_public.html`
(header público). Ambas corrigidas para `{% comment %}...{% endcomment %}`.
Este arquivo tranca esse comportamento para nunca mais regredir — tanto
apontando para os textos específicos que vazaram quanto, de forma mais
ampla, garantindo que nenhuma página renderizada contenha um `{#` sem o
`#}` correspondente na mesma linha do HTML de saída (o que cobriria
qualquer ocorrência futura do mesmo erro, em qualquer template).
"""

import re

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment

User = get_user_model()

# Trechos literais dos dois comentários que vazaram em produção — se
# aparecerem de novo em QUALQUER resposta, é o mesmo bug voltando. Cada
# frase foi escolhida por ser específica o bastante para não colidir com
# nenhum comentário JS/CSS legítimo que o próprio chrome (sidebar/drawer)
# passou a ter depois da correção (ex.: "Drawer do menu mobile interno —
# vanilla JS" é um comentário `//` real e válido no script do drawer —
# usar só "Drawer do menu mobile" como marcador daria falso positivo ali).
LEAKED_PHRASES = (
    "Organizado por módulo (grupos aprovados: Operação,",
    "ganha link de navegação pela primeira vez aqui (antes só era",
    "Header público minimalista (auditoria, item [8]): LOCUS + ☰, nada de",
    "menu (drawer) contém os CTAs comerciais + \"Entrar\" (visualmente",
)


class NoLeakedTemplateCommentsOnInternalPagesTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Climatizador")
        model = EquipmentModel.objects.create(category=category, name="Climatizador 9PRO", code="9PRO")
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            User.objects.create_user(username=f"leak_check_{role.lower()}", password="senha-forte-123", role=role)
        creator = User.objects.get(username="leak_check_admin")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

    def test_equipment_list_never_leaks_comment_text_for_any_role(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            self.client.login(username=f"leak_check_{role.lower()}", password="senha-forte-123")
            content = self.client.get("/equipamentos/").content.decode()
            for phrase in LEAKED_PHRASES:
                self.assertNotIn(phrase, content, f"Comentário vazou para {role}: '{phrase}'")
            self.client.logout()

    def test_dashboard_home_never_leaks_comment_text(self):
        self.client.login(username="leak_check_admin", password="senha-forte-123")
        content = self.client.get("/").content.decode()
        for phrase in LEAKED_PHRASES:
            self.assertNotIn(phrase, content)

    def test_equipment_private_detail_never_leaks_comment_text(self):
        self.client.login(username="leak_check_admin", password="senha-forte-123")
        content = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/").content.decode()
        for phrase in LEAKED_PHRASES:
            self.assertNotIn(phrase, content)


class NoLeakedTemplateCommentsOnPublicPagesTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQTR")
        creator = User.objects.create_user(username="leak_check_public_creator", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

    def test_public_landing_never_leaks_comment_text(self):
        content = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/").content.decode()
        for phrase in LEAKED_PHRASES:
            self.assertNotIn(phrase, content)

    def test_login_page_never_leaks_comment_text(self):
        content = self.client.get("/contas/login/").content.decode()
        for phrase in LEAKED_PHRASES:
            self.assertNotIn(phrase, content)


class NoUnterminatedDjangoCommentTagInAnyRenderedPageTest(TestCase):
    """
    Checagem mais ampla que os textos específicos acima: nenhuma resposta
    HTTP renderizada pode conter um `{#` sem um `#}` de fechamento — esse
    padrão em si já é o sintoma do bug (comentário Django virando texto
    literal), independente de qual comentário seja. Cobre qualquer
    recorrência futura da mesma classe de erro, em qualquer template.
    """

    def setUp(self):
        category = Category.objects.create(name="Climatizador")
        model = EquipmentModel.objects.create(category=category, name="Climatizador 6PRO", code="6PRO")
        User.objects.create_user(username="leak_scan_admin", password="senha-forte-123", role="ADMIN")
        creator = User.objects.get(username="leak_scan_admin")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

    def _assert_no_unterminated_comment_marker(self, content):
        # `{#` seguido de qualquer coisa que NÃO feche com `#}` antes do
        # próximo `{#`/fim da string é o sintoma exato do bug.
        for match in re.finditer(r"\{#", content):
            remainder = content[match.start() :]
            self.assertIn(
                "#}",
                remainder,
                f"Marcador de comentário Django '{{#' sem fechamento '#}}' encontrado na posição {match.start()}.",
            )

    def test_equipment_list_has_no_unterminated_comment_marker(self):
        self.client.login(username="leak_scan_admin", password="senha-forte-123")
        content = self.client.get("/equipamentos/").content.decode()
        self._assert_no_unterminated_comment_marker(content)

    def test_public_landing_has_no_unterminated_comment_marker(self):
        content = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/").content.decode()
        self._assert_no_unterminated_comment_marker(content)

    def test_dashboard_home_has_no_unterminated_comment_marker(self):
        self.client.login(username="leak_scan_admin", password="senha-forte-123")
        content = self.client.get("/").content.decode()
        self._assert_no_unterminated_comment_marker(content)
