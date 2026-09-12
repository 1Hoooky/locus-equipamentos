"""
Services do CRM (LocusHub, Etapa 1) — único caminho suportado para criar/
editar `Opportunity`, mudar sua etapa (incluindo ganho/perda) e registrar
`CommercialActivity`. Nunca `Opportunity.objects.create()`/`.save()` direto
em view/form para os campos de etapa/ganho/perda — mesma convenção já
usada em `apps.operations.services.create_movement()` para
`Equipment.current_location`/`current_client`.

Nada aqui escreve em `Client`/`Address` — o CRM só LÊ o `Client` já
existente (FK), nunca modifica seus campos cadastrais (ver
`apps/crm/models.py`, docstring de `Opportunity`).
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import ProtectedError, Q, QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.core.hard_delete import (
    HardDeleteAuthorizationError,
    HardDeleteBlocked,
    HardDeleteImpact,
    describe_protected_error,
)
from apps.crm.models import (
    ActivityType,
    CommercialActivity,
    CommercialSource,
    LossReason,
    Opportunity,
    OpportunityStage,
    OpportunityStageChange,
)

# ---------------------------------------------------------------------------
# Elegibilidade de responsável comercial (owner)
# ---------------------------------------------------------------------------


def eligible_owner_queryset() -> QuerySet[User]:
    """
    Quem PODE ser `Opportunity.owner` — implementação conservadora
    (pedido explícito: "não presumir que qualquer usuário pode ser
    responsável comercial"): superusuário (bypass administrativo padrão,
    igual ao resto do sistema) OU usuário cujo Cargo/Permission concede
    `crm.add_opportunities` — a mesma permissão que autoriza CRIAR
    oportunidades, por ser o critério mais direto de "atua
    comercialmente no CRM" sem inventar um conceito novo (ex.: uma flag
    `is_salesperson` separada). Cobre tanto a Permission concedida via
    Cargo (`groups__permissions`, o caminho usado por toda a arquitetura
    nova) quanto via `user_permissions` direto (caminho nativo do
    Django, raramente usado neste projeto, mas incorreto ignorar).

    Só usuários ATIVOS (`is_active=True`) — um usuário desativado nunca
    deve aparecer como opção de responsável para uma oportunidade NOVA
    (oportunidades já atribuídas a um usuário desde-desativado
    continuam mostrando-o normalmente, só não aparece mais como opção
    ao criar/reatribuir).
    """
    permission_q = Q(
        groups__permissions__codename="add_opportunities",
        groups__permissions__content_type__app_label="crm",
    ) | Q(
        user_permissions__codename="add_opportunities",
        user_permissions__content_type__app_label="crm",
    )
    return (
        User.objects.filter(is_active=True)
        .filter(Q(is_superuser=True) | permission_q)
        .distinct()
        .order_by("first_name", "last_name", "username")
    )


# ---------------------------------------------------------------------------
# Criar / editar Oportunidade (campos "cadastrais" — nunca etapa/ganho/perda)
# ---------------------------------------------------------------------------


@dataclass
class NewOpportunityData:
    client: Client
    title: str
    owner: User
    source: CommercialSource
    business_type: str
    stage: OpportunityStage
    created_by: User
    expected_close_date: date | None = None
    estimated_value: Decimal | None = None
    notes: str = ""


def _validate_common_fields(*, title: str, estimated_value: Decimal | None) -> None:
    if not title.strip():
        raise ValueError("Título da oportunidade é obrigatório.")
    # Mesma regra das CheckConstraints `crm_opportunity_*_not_negative`
    # (apps.crm.models) — repetida aqui para rejeitar ANTES de qualquer
    # escrita, com mensagem clara (mesmo raciocínio documentado em
    # apps.operations.services._validate_location_client_matches_type).
    if estimated_value is not None and estimated_value < 0:
        raise ValueError("Valor estimado não pode ser negativo.")


@transaction.atomic
def create_opportunity(data: NewOpportunityData) -> Opportunity:
    """
    Cria uma `Opportunity` nova. `stage` inicial é sempre uma etapa que
    NÃO é de ganho nem de perda — uma oportunidade nunca "nasce"
    ganha/perdida: `won_at`/`lost_at` só são escritos por
    `change_opportunity_stage()`, o único caminho que os grava (ver
    docstring de `Opportunity`). Uma oportunidade que precisar já
    nascer ganha/perdida (caso de uso não pedido nesta etapa) exigiria
    criar e então chamar `change_opportunity_stage()` em seguida — dois
    passos deliberados, nunca um atalho aqui.
    """
    _validate_common_fields(title=data.title, estimated_value=data.estimated_value)

    if data.stage.is_won or data.stage.is_lost:
        raise ValueError(
            "Uma oportunidade não pode ser criada diretamente numa etapa de ganho ou perda — "
            "crie na etapa inicial e depois altere a etapa."
        )
    if not data.stage.is_active:
        raise ValueError("Não é possível criar uma oportunidade numa etapa desativada.")

    opportunity = Opportunity(
        client=data.client,
        title=data.title.strip(),
        owner=data.owner,
        source=data.source,
        business_type=data.business_type,
        stage=data.stage,
        expected_close_date=data.expected_close_date,
        estimated_value=data.estimated_value,
        notes=data.notes,
        created_by=data.created_by,
    )
    opportunity._change_reason = "Criação da oportunidade."
    opportunity.save()

    # Primeira linha do histórico estruturado de etapa — `from_stage=None`
    # (não "veio de lugar nenhum", ver docstring de `OpportunityStageChange`).
    OpportunityStageChange.objects.create(
        opportunity=opportunity,
        from_stage=None,
        to_stage=data.stage,
        changed_by=data.created_by,
        reason="Etapa inicial na criação da oportunidade.",
    )
    return opportunity


@dataclass
class OpportunityUpdateData:
    title: str
    owner: User
    source: CommercialSource
    business_type: str
    expected_close_date: date | None = None
    estimated_value: Decimal | None = None
    notes: str = ""


@transaction.atomic
def update_opportunity(*, opportunity: Opportunity, data: OpportunityUpdateData, changed_by: User) -> Opportunity:
    """
    Edita os campos "cadastrais" de uma `Opportunity` já existente —
    NUNCA `client` (uma oportunidade não muda de cliente depois de
    criada; corrigir isso exigiria excluir e recriar, fora do escopo
    desta etapa) e NUNCA etapa/ganho/perda (`stage`/`won_at`/`lost_at`/
    `loss_reason`/`loss_notes`/`closed_value` — exclusividade de
    `change_opportunity_stage()`). Nada aqui toca `opportunity.client`
    nem qualquer campo do `Client` associado.
    """
    _validate_common_fields(title=data.title, estimated_value=data.estimated_value)

    opportunity._change_reason = "Edição da oportunidade."
    opportunity.title = data.title.strip()
    opportunity.owner = data.owner
    opportunity.source = data.source
    opportunity.business_type = data.business_type
    opportunity.expected_close_date = data.expected_close_date
    opportunity.estimated_value = data.estimated_value
    opportunity.notes = data.notes
    opportunity.save()
    return opportunity


# ---------------------------------------------------------------------------
# Mudança de etapa (inclui ganho/perda) — única escrita de stage/won_at/
# lost_at/loss_reason/loss_notes/closed_value em todo o app.
# ---------------------------------------------------------------------------


@transaction.atomic
def change_opportunity_stage(
    *,
    opportunity_id: int,
    new_stage: OpportunityStage,
    changed_by: User,
    reason: str = "",
    loss_reason: LossReason | None = None,
    loss_notes: str = "",
    closed_value: Decimal | None = None,
) -> Opportunity:
    """
    Único caminho suportado para mudar a etapa de uma `Opportunity` —
    inclui marcar como ganha ou perdida (ganhar/perder É mudar de
    etapa, para uma etapa com `is_won`/`is_lost`, não uma ação separada
    no modelo de dados). Sempre roda dentro de uma transação com
    `select_for_update()` na própria `Opportunity` (mesmo padrão de
    `apps.operations.services.create_movement()` em `Equipment`): duas
    requisições concorrentes mudando a etapa da MESMA oportunidade
    serializam aqui — a segunda só enxerga o estado já gravado pela
    primeira, nunca as duas escrevem em cima da mesma leitura
    desatualizada. `OpportunityStageChange` é sempre criado na MESMA
    transação que atualiza `Opportunity` — nunca uma sem a outra
    (atomicidade: um erro no meio desfaz as duas).

    Estados impossíveis prevenidos aqui (dupla camada — já há
    CheckConstraint no banco para os dois primeiros; esta função é a
    validação "com mensagem clara", igual ao resto do projeto):
      - `won_at` e `lost_at` preenchidos ao mesmo tempo;
      - etapa de ganho com `lost_at`/`loss_reason` "sobrando", e
        vice-versa;
      - voltar para uma etapa intermediária (nem ganho nem perda) COM
        `won_at`/`lost_at`/`loss_reason`/`closed_value` ainda
        preenchidos ("reabrir" uma oportunidade sempre limpa o estado
        de fechamento anterior).
    """
    opportunity = Opportunity.objects.select_for_update().get(pk=opportunity_id)
    current_stage = opportunity.stage

    if new_stage.pk == current_stage.pk:
        raise ValueError("A oportunidade já está nesta etapa.")
    if not new_stage.is_active:
        raise ValueError("Não é possível mover a oportunidade para uma etapa desativada.")
    if new_stage.is_won and new_stage.is_lost:
        # Já impossível de existir no banco (CheckConstraint), mas
        # defensivo — nunca confiar só no estado de outra tabela.
        raise ValueError("Etapa de destino inválida: marcada como ganho e perda ao mesmo tempo.")

    now = timezone.now()

    if new_stage.is_won:
        opportunity.won_at = now
        opportunity.lost_at = None
        opportunity.loss_reason = None
        opportunity.loss_notes = ""
        if closed_value is not None and closed_value < 0:
            raise ValueError("Valor de fechamento não pode ser negativo.")
        opportunity.closed_value = closed_value
    elif new_stage.is_lost:
        if loss_reason is None:
            raise ValueError("Motivo de perda é obrigatório ao marcar a oportunidade como perdida.")
        opportunity.lost_at = now
        opportunity.won_at = None
        opportunity.loss_reason = loss_reason
        opportunity.loss_notes = loss_notes
        opportunity.closed_value = None
    else:
        # Etapa intermediária — reabre a oportunidade se ela vinha de um
        # estado ganho/perdido, limpando por completo o estado de
        # fechamento anterior (ver docstring acima).
        opportunity.won_at = None
        opportunity.lost_at = None
        opportunity.loss_reason = None
        opportunity.loss_notes = ""
        opportunity.closed_value = None

    opportunity.stage = new_stage
    opportunity._change_reason = f"Mudança de etapa: {current_stage.name} → {new_stage.name}."
    # `clean()` explícito (não é chamado automaticamente por `save()`) —
    # mesma dupla camada de validação do resto do arquivo: as
    # CheckConstraints do banco são a rede de segurança final, isto é a
    # mensagem clara antes de qualquer escrita.
    opportunity.clean()
    opportunity.save()

    OpportunityStageChange.objects.create(
        opportunity=opportunity,
        from_stage=current_stage,
        to_stage=new_stage,
        changed_by=changed_by,
        reason=reason,
    )
    return opportunity


# ---------------------------------------------------------------------------
# Atividades comerciais — só registro (criar/ver), sem edição nesta etapa.
# ---------------------------------------------------------------------------


@dataclass
class NewActivityData:
    opportunity: Opportunity
    activity_type: str
    created_by: User
    description: str = ""
    occurred_at: datetime | None = None
    scheduled_for: datetime | None = None
    completed_at: datetime | None = None


def create_activity(data: NewActivityData) -> CommercialActivity:
    if data.activity_type not in ActivityType.values:
        raise ValueError(f"Tipo de atividade inválido: {data.activity_type!r}.")

    return CommercialActivity.objects.create(
        opportunity=data.opportunity,
        activity_type=data.activity_type,
        description=data.description,
        occurred_at=data.occurred_at,
        scheduled_for=data.scheduled_for,
        completed_at=data.completed_at,
        created_by=data.created_by,
    )


# ---------------------------------------------------------------------------
# Exclusão definitiva (hard delete) — rodada "AMBIENTE EM DESENVOLVIMENTO /
# HARD DELETE DURANTE DESENVOLVIMENTO", 11/09/2026. Ver docstring de
# `apps.core.hard_delete` para o raciocínio completo (por que
# `is_superuser`, por que não substitui o soft delete existente — aqui
# nem existe: `Opportunity` não é `SoftDeleteModel`, ver docstring do
# model, então até agora não havia NENHUM caminho de exclusão real).
#
# Mapa de relações de `Opportunity` (auditoria da rodada — CASCADE/
# PROTECT/SET_NULL) — este é exatamente o exemplo dado pelo próprio
# usuário no pedido:
#   DEPENDÊNCIA EXCLUSIVA (removida junto — já `CASCADE` no schema,
#   nenhum código extra necessário; o Django cuida sozinho ao excluir a
#   Opportunity):
#     - `OpportunityStageChange.opportunity` (`CASCADE`) — histórico de
#       etapa desta oportunidade, sem sentido órfão.
#     - `CommercialActivity.opportunity` (`CASCADE`) — atividades
#       comerciais desta oportunidade, mesmo raciocínio.
#   REGISTROS COMPARTILHADOS (NUNCA excluídos/alterados por aqui — todas
#   as outras FKs de `Opportunity` apontam PARA fora, então excluir a
#   Opportunity nunca dispara o `on_delete` do lado deles):
#     - `client` (`PROTECT`) — pedido explícito do usuário: "Excluir uma
#       oportunidade NÃO deve excluir o Cliente." Como `Opportunity` é
#       quem tem a FK (não o inverso), excluir a Opportunity nem chega a
#       tocar no Client.
#     - `stage`/`source`/`loss_reason` (`PROTECT`) — configuração
#       comercial reaproveitada por outras oportunidades.
#     - `owner`/`created_by` (`PROTECT`) — `User`, nunca tocado.
# ---------------------------------------------------------------------------


def preview_opportunity_hard_delete(opportunity: Opportunity) -> HardDeleteImpact:
    """Não altera nada — só descreve o que `hard_delete_opportunity()` removeria junto, para a tela de confirmação."""
    dependents = {}
    stage_changes = opportunity.stage_changes.count()
    activities = opportunity.activities.count()
    if stage_changes:
        dependents["histórico de etapas"] = stage_changes
    if activities:
        dependents["atividades comerciais"] = activities
    return HardDeleteImpact(target_label=f'a oportunidade "{opportunity.title}"', dependents=dependents)


@transaction.atomic
def hard_delete_opportunity(*, opportunity_id: int, actor) -> HardDeleteImpact:
    """
    Único caminho suportado para excluir uma `Opportunity` de verdade —
    restrito à "autoridade máxima" (`actor.is_superuser`, checado aqui E
    na view). `OpportunityStageChange`/`CommercialActivity` somem
    automaticamente (CASCADE já no schema); levanta `HardDeleteBlocked`
    se algum relacionamento `PROTECT` inesperado ainda segurar a
    exclusão — nunca cascateia às cegas para resolver.
    """
    if not getattr(actor, "is_superuser", False):
        raise HardDeleteAuthorizationError("Exclusão definitiva requer autoridade máxima (superusuário).")

    opportunity = Opportunity.objects.select_for_update().get(pk=opportunity_id)
    label = f'a oportunidade "{opportunity.title}"'
    dependents = {}
    stage_changes = opportunity.stage_changes.count()
    activities = opportunity.activities.count()
    if stage_changes:
        dependents["histórico de etapas"] = stage_changes
    if activities:
        dependents["atividades comerciais"] = activities

    try:
        opportunity.delete()
    except ProtectedError as exc:
        raise HardDeleteBlocked(describe_protected_error(exc, subject=label)) from exc

    # Ver mesma nota em `apps.clients.services.hard_delete_client()`.
    Opportunity.history.filter(id=opportunity_id).delete()

    return HardDeleteImpact(target_label=label, dependents=dependents)
