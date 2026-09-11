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
"""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter(name="brl")
def brl(value):
    """
    Formata um valor monetário como "R$ 1.234,56". `None`/vazio vira "—"
    (mesmo marcador já usado em todo o resto do sistema para "sem valor").
    Um valor que não é numérico é devolvido sem alteração, sem levantar
    exceção — um filtro de template nunca deve quebrar a página.
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
