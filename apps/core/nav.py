"""
Fonte única de verdade para "qual grupo do menu lateral está ativo" nesta
requisição (REFINAMENTO DA SIDEBAR / REORGANIZAÇÃO DA ARQUITETURA DE
NAVEGAÇÃO, 11/09/2026) — usada IGUALMENTE pela sidebar desktop
(templates/base.html) e pelo drawer mobile para garantir que os dois
NUNCA divirjam sobre qual grupo deve abrir automaticamente quando o
usuário está numa página daquele grupo.

Importante: esta função só decide qual grupo deve aparecer ABERTO/
destacado visualmente — ela NUNCA decide se um item ou grupo deve
aparecer. Quem decide isso continua sendo exclusivamente o backend
(RoleRequiredMixin/allowed_roles nas views, `perms.*`/`user.is_*` nos
próprios `{% if %}` do template) — ver templates/base.html. Não
alterar/duplicar essa checagem aqui.

Função pura (sem request, sem DB, sem I/O) de propósito: recebe só
`view_name`/`app_name` (o que `request.resolver_match` já expõe) e
devolve uma string — trivial de testar isoladamente (ver
apps/core/tests/test_nav.py), sem precisar de client HTTP nem banco.
"""

CRM = "crm"
OPERACAO = "operacao"
CADASTROS = "cadastros"
CONFIGURACOES = "configuracoes"

# Alguns apps do projeto têm rotas que pertencem a MAIS de um grupo do
# menu (ex.: "equipment" tem tanto a operação do dia a dia quanto a
# importação de planilha, que é um recurso administrativo) — por isso não
# dá para resolver só por `app_name`; view_names específicos são checados
# antes do fallback genérico por app.
_EQUIPMENT_CONFIG_PREFIXES = ("equipment:import_",)

_ACCOUNTS_CADASTROS = {
    "accounts:user_list",
    "accounts:user_create",
    "accounts:user_update",
}
_ACCOUNTS_CONFIG_PREFIXES = ("accounts:role_",)

_OPERATIONS_CADASTROS = {
    "operations:location_list",
    "operations:location_create",
    "operations:location_detail",
    "operations:location_update",
    "operations:location_address_update",
}
_OPERATIONS_CONFIG = {"operations:duplicate_locations_report"}


def active_nav_group(view_name, app_name):
    """
    Devolve qual dos 4 grupos do menu deve aparecer aberto/ativo para a
    página atual: "crm" | "operacao" | "cadastros" | "configuracoes", ou
    None quando a página não pertence a nenhum grupo (ex.: Início, tela
    de login, ou uma rota que não tem item correspondente no menu
    lateral — como uma sub-rota de movimentação aberta a partir da ficha
    do equipamento).
    """
    if not view_name:
        return None

    if app_name == "crm":
        return CRM

    if app_name == "equipment":
        if any(view_name.startswith(prefix) for prefix in _EQUIPMENT_CONFIG_PREFIXES):
            return CONFIGURACOES
        return OPERACAO

    if app_name == "maintenance":
        return OPERACAO

    if app_name == "clients":
        return CADASTROS

    if app_name == "catalog":
        return CADASTROS

    if app_name == "accounts":
        if view_name in _ACCOUNTS_CADASTROS:
            return CADASTROS
        if any(view_name.startswith(prefix) for prefix in _ACCOUNTS_CONFIG_PREFIXES):
            return CONFIGURACOES
        return None

    if app_name == "operations":
        if view_name in _OPERATIONS_CADASTROS:
            return CADASTROS
        if view_name in _OPERATIONS_CONFIG:
            return CONFIGURACOES
        return None

    return None
