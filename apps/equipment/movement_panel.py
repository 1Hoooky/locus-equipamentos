"""
Painel visual "Movimentar equipamento" da ficha privada do equipamento —
melhoria de UX/UI (etapa seguinte à listagem agrupada por modelo).

Módulo PURAMENTE de leitura/apresentação: decide quais `MovementType`
mostrar como card na ficha, sem duplicar nem reescrever nenhuma regra de
transição. Lê diretamente as MESMAS estruturas já usadas por
`apps.operations.services.create_movement()` — `_TRANSITION_RULES`
(status exigido por tipo) e `_BLOCKED_BY_OPEN_MAINTENANCE` — mais
`apps.maintenance.services.has_open_maintenance()` (função pública,
mesma usada por `_validate_transition()`). Nenhum desses arquivos foi
alterado por este módulo — zero regra duplicada, zero cópia que possa
divergir com o tempo.

Import cross-app feito LOCAL (dentro da função, não no topo do módulo):
mesmo padrão já usado em `apps.equipment.views.EquipmentDetailView.
_render_private()` para `apps.maintenance.services` — evita acoplamento
de import-time entre apps (`apps.equipment` nunca deve depender, no
topo do módulo, de `apps.operations`/`apps.maintenance`, que já
importam DE `apps.equipment`; ver docstrings de
`apps.operations.services._validate_transition` e
`apps.maintenance.services.has_open_maintenance`).

IMPORTANTE — isto é só uma AJUDA VISUAL, nunca a autoridade final:
`create_movement()` (chamado somente depois que o operador escolhe o
destino e confirma no formulário) continua sendo o único lugar que de
fato valida e grava a movimentação, dentro de uma transação com
`select_for_update()`. Uma corrida rara — por exemplo, outra aba abrindo
uma Maintenance bem no instante entre este cálculo (feito ao renderizar
a ficha, sem lock nenhum) e o clique no card — não é um problema de
segurança: o pior caso é o card aparecer e o formulário recusar no
submit com a mesma mensagem de erro que já existia antes desta
melhoria. O comportamento de HOJE (dropdown único, sem nenhum filtro
por status) já dependia inteiramente dessa mesma validação no submit;
este módulo só acrescenta uma prévia — nunca substitui a validação.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MovementAction:
    movement_type: str
    label: str
    icon: str
    variant: str  # "primary" | "warning" | "neutral" — só apresentação (ver templates/_design_tokens.html)


# Ícone/texto/cor por MovementType — decisão de apresentação desta etapa
# (mapeamento completo no relatório de entrega). `MovementType.OUTRO`
# deliberadamente ausente: `apps.operations.forms.MOVEMENT_TYPE_CHOICES`
# já não oferece essa opção em NENHUMA tela hoje ("não tem fluxo de UI
# nesta etapa", ver docstring de `MovementForm`) — mantido assim aqui
# também, sem inventar uma tela nova para ele.
_ACTION_PRESENTATION: dict[str, MovementAction] = {
    "INSTALACAO": MovementAction("INSTALACAO", "Instalar", "arrow-right-circle", "primary"),
    "RETIRADA": MovementAction("RETIRADA", "Retirar", "arrow-left-circle", "neutral"),
    "TRANSFERENCIA": MovementAction("TRANSFERENCIA", "Transferir", "arrows-right-left", "neutral"),
    "RETORNO_ESTOQUE": MovementAction("RETORNO_ESTOQUE", "Retorno ao estoque", "archive-box-arrow-down", "neutral"),
    "ENVIO_MANUTENCAO": MovementAction("ENVIO_MANUTENCAO", "Enviar à manutenção", "wrench-screwdriver", "warning"),
    "RETORNO_MANUTENCAO": MovementAction("RETORNO_MANUTENCAO", "Retorno da manutenção", "arrow-uturn-left", "neutral"),
}


def available_movement_actions(equipment) -> list[MovementAction]:
    """
    Lista, na MESMA ordem de `apps.operations.forms.MOVEMENT_TYPE_CHOICES`,
    as ações de movimentação com card na ficha — só as que a regra de
    status JÁ EXISTENTE (`_TRANSITION_RULES`) permite para o status atual
    de `equipment`, excluindo as bloqueadas por manutenção técnica aberta
    (`_BLOCKED_BY_OPEN_MAINTENANCE` + `has_open_maintenance()`).

    Não checa disponibilidade de `Location` de destino — isso continua
    sendo responsabilidade do formulário/serviço no próximo passo do
    fluxo (`MovementForm`/`create_movement()`), exatamente como já era
    antes desta melhoria. Só os dois critérios que já decidem se o TIPO
    de movimentação em si faz sentido agora para este equipamento.
    """
    from apps.maintenance.services import has_open_maintenance
    from apps.operations.forms import MOVEMENT_TYPE_CHOICES
    from apps.operations.services import _BLOCKED_BY_OPEN_MAINTENANCE, _TRANSITION_RULES

    # Calculado no máximo uma vez, e só se algum tipo bloqueável por
    # manutenção aberta realmente estiver entre os candidatos — evita
    # uma query à toa quando, por exemplo, o status só admite
    # RETORNO_ESTOQUE/RETORNO_MANUTENCAO (nenhum dos dois bloqueável).
    blocked_by_open_maintenance: bool | None = None

    actions: list[MovementAction] = []
    for movement_type, _label in MOVEMENT_TYPE_CHOICES:
        rule = _TRANSITION_RULES.get(movement_type)
        if rule is None or equipment.status not in rule.required_statuses:
            continue

        if movement_type in _BLOCKED_BY_OPEN_MAINTENANCE:
            if blocked_by_open_maintenance is None:
                blocked_by_open_maintenance = has_open_maintenance(equipment)
            if blocked_by_open_maintenance:
                continue

        action = _ACTION_PRESENTATION.get(movement_type)
        if action is not None:
            actions.append(action)

    return actions
