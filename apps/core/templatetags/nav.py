"""
Tag de template fina sobre `apps.core.nav.active_nav_group` — só extrai
`view_name`/`app_name` de `request.resolver_match` (contexto do template)
e delega à função pura. Ver apps/core/nav.py para a lógica/documentação
completa; este arquivo não deve crescer com nenhuma regra nova, é só o
adaptador "request -> função pura".

Uso:
    {% load nav %}
    {% active_nav_group as current_group %}
    {% if current_group == "crm" %}...{% endif %}
"""

from django import template

from apps.core import nav

register = template.Library()


@register.simple_tag(takes_context=True)
def active_nav_group(context):
    request = context.get("request")
    match = getattr(request, "resolver_match", None) if request is not None else None
    if match is None:
        return None
    return nav.active_nav_group(match.view_name, match.app_name)
