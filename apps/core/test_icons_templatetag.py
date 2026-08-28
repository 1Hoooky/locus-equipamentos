"""
Testes da template tag `{% icon %}` (apps.core.templatetags.icons).

Escopo (auditoria de iconografia, 28/08/2026): a tag só faz uma coisa —
devolver o SVG vendorizado certo, do tamanho certo, sem quebrar a página
quando alguém pedir um nome que não existe. Não testamos "parece bonito",
testamos contrato: nome conhecido -> SVG esperado; tamanho/classe
respeitados; nome inválido -> não levanta exceção e não injeta HTML não
escapado.
"""

from django.template import Context, Template
from django.test import SimpleTestCase

from apps.core.templatetags.icons import icon


class IconTagUnitTest(SimpleTestCase):
    """Chamando a função da tag diretamente (sem passar pelo motor de templates)."""

    def test_icone_conhecido_renderiza_o_svg_esperado(self):
        rendered = icon("eye")
        self.assertIn("<svg", rendered)
        self.assertIn('viewBox="0 0 24 24"', rendered)
        # path data exato do Heroicons "eye" (outline) — prova que é o
        # ícone certo, não só "algum svg".
        self.assertIn("M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z", rendered)

    def test_tamanho_normal_e_compacto_sao_os_dois_unicos_tokens(self):
        normal = icon("eye")
        compact = icon("eye", size="compact")
        self.assertIn('width="20" height="20"', normal)
        self.assertIn('width="16" height="16"', compact)

    def test_tamanho_desconhecido_cai_para_normal_em_vez_de_quebrar(self):
        rendered = icon("eye", size="gigante")
        self.assertIn('width="20" height="20"', rendered)

    def test_extra_class_e_aplicada_e_escapada(self):
        rendered = icon("eye", extra_class="shrink-0")
        self.assertIn("shrink-0", rendered)

    def test_extra_class_com_html_e_escapada_nunca_injetada_crua(self):
        rendered = icon("eye", extra_class='"><script>alert(1)</script>')
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_icone_desconhecido_nao_levanta_excecao(self):
        # Não pode derrubar a página: nome errado vira comentário HTML
        # inofensivo, nunca uma KeyError/Exception nem um <svg> vazio
        # quebrado.
        rendered = icon("nome-que-nao-existe")
        self.assertNotIn("<svg", rendered)
        self.assertIn("<!--", rendered)

    def test_nome_de_icone_desconhecido_e_escapado_no_comentario(self):
        rendered = icon('"><script>alert(1)</script>')
        self.assertNotIn("<script>alert(1)</script>", rendered)

    def test_todos_os_icones_vendorizados_renderizam_sem_erro(self):
        from apps.core.templatetags.icons import _ICONS

        for name in _ICONS:
            with self.subTest(icon=name):
                rendered = icon(name)
                self.assertIn("<svg", rendered)
                self.assertIn("</svg>", rendered)

    def test_svg_e_marcado_aria_hidden_o_nome_acessivel_e_do_elemento_pai(self):
        # O ícone nunca carrega o nome acessível sozinho — isso é sempre
        # responsabilidade do aria-label do <a>/<button> que o envolve
        # (ver componentes .icon-btn-* em base.html).
        rendered = icon("eye")
        self.assertIn('aria-hidden="true"', rendered)
        self.assertIn('focusable="false"', rendered)


class IconTagTemplateRenderingTest(SimpleTestCase):
    """Chamando a tag de dentro de um template real, via {% load icons %}."""

    def test_tag_funciona_carregada_num_template(self):
        template = Template('{% load icons %}{% icon "pencil" %}')
        rendered = template.render(Context({}))
        self.assertIn("<svg", rendered)

    def test_tag_aceita_size_compact_num_template(self):
        template = Template('{% load icons %}{% icon "tag" size="compact" %}')
        rendered = template.render(Context({}))
        self.assertIn('width="16" height="16"', rendered)

    def test_tag_aceita_variavel_de_contexto_como_nome(self):
        template = Template('{% load icons %}{% icon icon_name %}')
        rendered = template.render(Context({"icon_name": "arrow-left"}))
        self.assertIn("<svg", rendered)

    def test_tag_com_nome_desconhecido_nao_quebra_render_do_template(self):
        template = Template('{% load icons %}<p>antes</p>{% icon "inexistente" %}<p>depois</p>')
        rendered = template.render(Context({}))
        self.assertIn("<p>antes</p>", rendered)
        self.assertIn("<p>depois</p>", rendered)
