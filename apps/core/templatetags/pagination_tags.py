"""
Tag genérica para links de paginação que preservam a querystring atual.

Bug corrigido (relatado pelo usuário): os links "Anterior"/"Próxima" da
listagem de equipamentos eram montados como `?page=N` puro, descartando
qualquer filtro (`?model=...`, `?status=...`, `?q=...` etc.) já aplicado
— ao trocar de página, o filtro "sumia" silenciosamente.

`url_replace` resolve isso de forma genérica: parte da querystring atual
(`request.GET`), sobrescreve só o parâmetro pedido (normalmente `page`) e
devolve tudo mais intacto. Não conhece nenhum nome de filtro específico
(`model`, `status`, `category`, `q`...) — funciona com qualquer combinação
presente ou futura de parâmetros GET, sem precisar ser alterada quando um
filtro novo for adicionado à listagem.

`QueryDict.__setitem__` já substitui (nunca duplica) todos os valores
existentes daquela chave por um único valor, então `field` nunca aparece
repetido no resultado.
"""

from django import template

register = template.Library()


@register.simple_tag
def url_replace(request, field, value):
    query_dict = request.GET.copy()
    query_dict[field] = value
    return query_dict.urlencode()
