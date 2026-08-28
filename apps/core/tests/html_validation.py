"""
Validador estrutural de HTML renderizado — rodada CORRETIVA de UX/UI
(homologação no Render). Usado pelos testes de regressão que garantem que
os templates alterados nesta etapa (bases + sidebar/drawer + landing
pública) produzem HTML bem formado: nenhuma `<div>` aberta sem fechamento,
nenhum fechamento fora de ordem, nenhuma tag aninhada incorretamente.

Deliberadamente NÃO usa BeautifulSoup/lxml/html5lib para esta checagem
específica: esses parsers são tolerantes por design (reparam o HTML
quebrado silenciosamente, que é exatamente o comportamento que NÃO
queremos aqui — precisamos que o erro apareça, não que seja escondido).
`html.parser.HTMLParser` da biblioteca padrão relata as tags exatamente
como aparecem na fonte, sem corrigir nada, então uma pilha simples de
abertura/fechamento é suficiente para detectar a classe de bug pedida.
"""

from html.parser import HTMLParser

# Elementos "void" do HTML5 — nunca têm tag de fechamento, não entram na pilha.
_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _StackValidator(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.issues = []

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_ELEMENTS:
            return
        self.stack.append((tag, self.getpos()))

    def handle_startendtag(self, tag, attrs):
        # Tag auto-fechada explicitamente (ex.: <path ... />) — não entra na pilha.
        return

    def handle_endtag(self, tag):
        if tag in _VOID_ELEMENTS:
            # Tag de fechamento pra um void element (incomum, mas não é o
            # bug que estamos procurando aqui) — ignora.
            return
        if not self.stack:
            self.issues.append(f"Fechamento </{tag}> em {self.getpos()} sem nenhuma tag aberta correspondente.")
            return
        if self.stack[-1][0] == tag:
            self.stack.pop()
            return
        # Não bate com o topo da pilha: procura mais abaixo (fechamento fora
        # de ordem / tag intermediária nunca fechada).
        for depth, (open_tag, open_pos) in enumerate(reversed(self.stack)):
            if open_tag == tag:
                skipped = list(reversed(self.stack))[:depth]
                skipped_desc = ", ".join(f"<{t}> aberta em {p}" for t, p in skipped)
                self.issues.append(
                    f"</{tag}> em {self.getpos()} fecha fora de ordem — "
                    f"tag(s) aberta(s) e nunca fechada(s) antes dela: {skipped_desc}."
                )
                del self.stack[len(self.stack) - 1 - depth :]
                return
        self.issues.append(
            f"Fechamento </{tag}> em {self.getpos()} não corresponde a nenhuma tag aberta na pilha atual "
            f"(pilha: {[t for t, _ in self.stack]})."
        )


def find_html_structure_issues(html: str) -> list[str]:
    """
    Retorna uma lista de problemas estruturais encontrados no HTML (vazia
    se o documento estiver bem formado). Cada item descreve exatamente
    onde (linha/coluna) o problema foi detectado.
    """

    validator = _StackValidator()
    validator.feed(html)
    validator.close()

    issues = list(validator.issues)
    if validator.stack:
        unclosed = ", ".join(f"<{tag}> aberta em {pos}" for tag, pos in validator.stack)
        issues.append(f"Tag(s) aberta(s) nunca fechada(s) até o fim do documento: {unclosed}.")
    return issues
