"""
Formatação de valores monetários no padrão brasileiro ("R$ 1.234,56") —
auditoria de idioma/localização/UTF-8 (ago/2026).

Django já localiza automaticamente `Decimal`/`float` em templates (porque
`LANGUAGE_CODE = "pt-br"` e `USE_I18N = True`), então `{{ valor }}` já sai
com vírgula decimal ("1234,56") — mas SEM separador de milhar, porque
`USE_THOUSAND_SEPARATOR` nunca foi ligado no projeto (e ligá-lo global
afetaria também números não-monetários, como contadores e paginação, o
que está fora do escopo desta rodada). Este filtro resolve isso de forma
cirúrgica, só para os campos monetários que o chamam — sem depender de
nenhuma configuração de locale do sistema operacional (formatação sempre
determinística, calculada dígito a dígito a partir do `Decimal`).

`Decimal` nunca é convertido para float em nenhum passo — só formatado
como string para exibição. O valor armazenado/usado em cálculos em
qualquer outro lugar do sistema continua sendo o `Decimal` original,
intocado.

`format_brl()` é a função "crua" (reutilizável fora de templates — ex.:
respostas JSON de endpoints AJAX, como o Kanban de oportunidades do CRM).
`brl()` é só um wrapper fino dela como filtro de template, para manter
100% de compatibilidade com todo lugar que já usa `{{ valor|brl }}`.
"""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def format_brl(value):
    """
    Formata um valor monetário como "R$ 1.234,56". `None`/vazio vira "—"
    (mesmo marcador já usado em todo o resto do sistema para "sem valor").
    Um valor que não é numérico é devolvido sem alteração, sem levantar
    exceção — esta função nunca deve quebrar a chamadora (template ou view).
    """
    if value in (None, ""):
        return "—"
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value

    negative = amount < 0
    amount = abs(amount).quantize(Decimal("0.01"))
    integer_part, _, decimal_part = f"{amount:.2f}".partition(".")

    reversed_digits = integer_part[::-1]
    grouped_reversed = ".".join(reversed_digits[i : i + 3] for i in range(0, len(reversed_digits), 3))
    integer_grouped = grouped_reversed[::-1]

    sign = "-" if negative else ""
    return f"{sign}R$ {integer_grouped},{decimal_part}"


@register.filter(name="brl")
def brl(value):
    """Wrapper de template para `format_brl()` — ver docstring acima."""
    return format_brl(value)
