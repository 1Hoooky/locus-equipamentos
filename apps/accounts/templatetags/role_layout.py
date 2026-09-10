"""
Filtro puramente de apresentação para o checklist de permissões da tela
de Cargos (ajuste visual de 10/09/2026 — "AJUSTE VISUAL FINAL — TELA DE
CARGOS / PERMISSÕES", ver templates/accounts/role_form.html).

Não mexe em nada do catálogo/model/serviço de permissões — só calcula
quantos itens (mantendo a ordem original) devem ficar na coluna
esquerda de um grid CSS `grid-auto-flow: column`, para que a
distribuição seja VERTICAL por coluna (1, 2, 3, 4 na esquerda; 5, 6, 7
na direita) em vez do padrão intercalado do grid comum
(`grid-auto-flow: row`, que dá 1, 3, 5, 7 na esquerda e 2, 4, 6 na
direita — o problema relatado).

`ceil_half(n)` = ceil(n / 2) é usado como `grid-template-rows:
repeat(N, auto)` no CSS (ver <style> em role_form.html): com
`grid-auto-flow: column`, o grid preenche as N linhas da 1ª coluna
inteiras, na ordem do HTML, antes de "transbordar" para a 2ª — sem
precisar reordenar nenhum item no template nem no backend. No mobile a
regra de 2 colunas nem entra em vigor (fica dentro de um
`@media (min-width: 768px)`), então a ordem natural 1, 2, 3, 4, 5... é
preservada automaticamente, sem lógica condicional extra.
"""

from django import template

register = template.Library()


@register.filter
def ceil_half(count):
    """
    ceil(count / 2), sem depender de `math` — `-(-a // b)` é o idioma
    padrão de divisão inteira arredondada para cima em Python.

    Entrada inválida (None, string não numérica etc.) cai em 1 em vez de
    levantar exceção: é só um valor de layout (quantas linhas o grid
    reserva pra 1ª coluna), nunca deveria quebrar a renderização da
    página por causa disso.
    """
    try:
        count = int(count)
    except (TypeError, ValueError):
        return 1
    if count < 1:
        return 1
    return -(-count // 2)
