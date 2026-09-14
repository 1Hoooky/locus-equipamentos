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
from datetime import date, datetime, time
from decimal import Decimal

from django.db import models, transaction
from django.db.models import Max, ProtectedError, Q, QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.attachments.models import AttachmentCategory, AttachmentSource
from apps.attachments.services import NewAttachmentData, create_attachment
from apps.catalog.models import EquipmentModel
from apps.clients.models import Client
from apps.core.hard_delete import (
    HardDeleteAuthorizationError,
    HardDeleteBlocked,
    HardDeleteImpact,
    describe_protected_error,
)
from apps.core.services import get_company_profile
from apps.crm.models import (
    ActivityType,
    CommercialActivity,
    CommercialSource,
    Contract,
    LossReason,
    NumberingCounter,
    Opportunity,
    OpportunityStage,
    OpportunityStageChange,
    Proposal,
    ProposalItem,
    ProposalVersion,
    ProposalVersionStatus,
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
    """
    Não altera nada — só descreve o que `hard_delete_opportunity()`
    removeria junto, para a tela de confirmação.

    `propostas` inclui `Proposal.CASCADE` (junto com suas versões/itens —
    ver `apps.crm.models.Proposal.opportunity`). Se alguma
    `ProposalVersion` dessas propostas já tiver `Contract` gerado
    (`Contract.proposal_version` é `PROTECT`, deliberado — ver docstring
    de `Contract`), a exclusão é BLOQUEADA pelo banco e
    `hard_delete_opportunity()` traduz isso num `HardDeleteBlocked` com
    mensagem clara, nunca cascateando às cegas por cima de um contrato já
    gerado.
    """
    dependents = {}
    stage_changes = opportunity.stage_changes.count()
    activities = opportunity.activities.count()
    proposals = opportunity.proposals.count()
    if stage_changes:
        dependents["histórico de etapas"] = stage_changes
    if activities:
        dependents["atividades comerciais"] = activities
    if proposals:
        dependents["propostas (com versões e itens)"] = proposals
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
    proposals = opportunity.proposals.count()
    if stage_changes:
        dependents["histórico de etapas"] = stage_changes
    if activities:
        dependents["atividades comerciais"] = activities
    if proposals:
        dependents["propostas (com versões e itens)"] = proposals

    try:
        opportunity.delete()
    except ProtectedError as exc:
        raise HardDeleteBlocked(describe_protected_error(exc, subject=label)) from exc

    # Ver mesma nota em `apps.clients.services.hard_delete_client()`.
    Opportunity.history.filter(id=opportunity_id).delete()

    return HardDeleteImpact(target_label=label, dependents=dependents)


# ---------------------------------------------------------------------------
# Produtos e Serviços / Proposta Comercial + Contrato (14/09/2026).
#
# Regra geral de todo este bloco: BACKEND é autoridade (especificação,
# seção 80) — toda função de escrita recalcula subtotal/desconto/juros/
# frete/total antes de persistir, nunca confia em valor calculado só no
# frontend. Toda escrita numa `ProposalVersion` rejeita
# `status != DRAFT` (seção 60, "versão emitida é imutável") — a única
# forma de mudar uma versão emitida é `create_new_version()`.
# ---------------------------------------------------------------------------


def _require_draft(version: ProposalVersion) -> None:
    if version.status != ProposalVersionStatus.DRAFT:
        raise ValueError(
            "Só é possível editar uma versão em RASCUNHO — versões emitidas são imutáveis "
            "(crie uma nova versão para alterar as condições, seção 60 da especificação)."
        )


@transaction.atomic
def _next_document_number(*, key: str, prefix: str) -> str:
    """
    Numeração segura (seção 82: "Não usar MAX(id)+1 sem proteção") — mesmo
    padrão de `apps.equipment.services.create_equipment()`: contador
    dedicado (`NumberingCounter`), travado por `select_for_update()`
    dentro de uma transação, nunca contado a partir da própria tabela de
    destino.
    """
    counter, _ = NumberingCounter.objects.get_or_create(key=key)
    counter = NumberingCounter.objects.select_for_update().get(pk=counter.pk)
    counter.last_value += 1
    counter.save(update_fields=["last_value"])
    return f"{prefix}-{counter.last_value:06d}"


def calculate_proposal_version(version: ProposalVersion) -> ProposalVersion:
    """
    ÚNICA função que calcula subtotal/total — chamada por toda escrita de
    item/condição, e de novo, defensivamente, no início de
    `issue_proposal()` (seção 80: "Recalcular... antes de
    persistir/emissão"). Ordem exata da seção 24:

      1. bruto de cada item = unit_price × quantity;
      2. aplica desconto do item (percentual);
      3. soma os totais líquidos dos itens = subtotal;
      4. total = subtotal − desconto geral (monetário) + juros + frete.

    Nunca permite total negativo (seção 24/29) — levanta `ValueError` em
    vez de gravar um total truncado/zerado silenciosamente: um desconto
    geral maior que o subtotal disponível é um erro de digitação que o
    usuário precisa corrigir, não um valor que o sistema deveria
    "consertar" sozinho.
    """
    subtotal = Decimal("0.00")
    for item in version.items.all():
        gross = (item.unit_price * item.quantity).quantize(Decimal("0.01"))
        discount_fraction = item.item_discount_percent / Decimal("100")
        line_total = (gross * (Decimal("1") - discount_fraction)).quantize(Decimal("0.01"))
        if line_total != item.line_total:
            item.line_total = line_total
            item.save(update_fields=["line_total"])
        subtotal += line_total

    total = subtotal - version.general_discount + version.interest_amount + version.freight_amount
    if total < 0:
        raise ValueError(
            "O total não pode ficar negativo — reduza o desconto geral/juros ou revise os itens "
            "(subtotal: {subtotal}, desconto geral: {discount}).".format(
                subtotal=subtotal, discount=version.general_discount
            )
        )

    version.subtotal = subtotal
    version.total = total
    version.save(update_fields=["subtotal", "total"])
    return version


# --- Proposal / composição comercial ----------------------------------------


@transaction.atomic
def create_proposal(*, opportunity: Opportunity, created_by: User) -> Proposal:
    """
    Cria uma `Proposal` nova + sua primeira `ProposalVersion` (v1, DRAFT).
    A UI do Hub trabalha com "a composição comercial desta Opportunity" —
    por simplicidade, `get_or_create_active_proposal()` (abaixo) é quem a
    tela realmente chama; esta função pública existe para permitir mais
    de uma `Proposal` por Opportunity no futuro (o model não impõe
    OneToOne), sem forçar essa decisão agora.
    """
    number = _next_document_number(key="proposal", prefix="PROP")
    proposal = Proposal.objects.create(opportunity=opportunity, number=number, created_by=created_by)
    ProposalVersion.objects.create(proposal=proposal, version_number=1, status=ProposalVersionStatus.DRAFT)
    return proposal


def get_or_create_active_proposal(*, opportunity: Opportunity, created_by: User) -> Proposal:
    """
    A composição comercial que a aba "Produtos e Serviços" mostra é
    sempre a `Proposal` mais recente da Opportunity — criada sob demanda
    na primeira vez que alguém abre a aba com permissão de editar
    (`crm.change_opportunities`). GET nunca cria nada por conta própria
    (chamador decide); esta função só existe para o primeiro POST de
    edição não precisar de um passo "criar proposta" explícito e
    separado.
    """
    proposal = opportunity.proposals.order_by("-created_at").first()
    if proposal is not None:
        return proposal
    return create_proposal(opportunity=opportunity, created_by=created_by)


@dataclass
class ProposalItemData:
    equipment_model: EquipmentModel
    quantity: int
    unit_price: Decimal
    item_discount_percent: Decimal = Decimal("0.00")
    notes: str = ""


def _validate_item_fields(data: ProposalItemData) -> None:
    # Seção 17: quantidade inteiro positivo — rejeita 0/negativo (a
    # validação de "decimal inválido" já é papel do form, que usa
    # `IntegerField`, nunca chega aqui como não-inteiro).
    if data.quantity <= 0:
        raise ValueError("Quantidade deve ser um número inteiro positivo.")
    if data.unit_price < 0:
        raise ValueError("Valor unitário não pode ser negativo.")
    if not (Decimal("0") <= data.item_discount_percent <= Decimal("100")):
        raise ValueError("Desconto do item deve estar entre 0% e 100%.")


@transaction.atomic
def add_proposal_item(*, proposal_version: ProposalVersion, data: ProposalItemData) -> ProposalItem:
    _require_draft(proposal_version)
    _validate_item_fields(data)

    next_order = (proposal_version.items.aggregate(Max("order"))["order__max"] or 0) + 1
    item = ProposalItem.objects.create(
        proposal_version=proposal_version,
        equipment_model=data.equipment_model,
        description_snapshot=f"{data.equipment_model.name} ({data.equipment_model.code})",
        quantity=data.quantity,
        unit_price=data.unit_price,
        item_discount_percent=data.item_discount_percent,
        notes=data.notes,
        order=next_order,
    )
    calculate_proposal_version(proposal_version)
    return item


@transaction.atomic
def update_proposal_item(*, item: ProposalItem, data: ProposalItemData) -> ProposalItem:
    _require_draft(item.proposal_version)
    _validate_item_fields(data)

    item.equipment_model = data.equipment_model
    item.description_snapshot = f"{data.equipment_model.name} ({data.equipment_model.code})"
    item.quantity = data.quantity
    item.unit_price = data.unit_price
    item.item_discount_percent = data.item_discount_percent
    item.notes = data.notes
    item.save()
    calculate_proposal_version(item.proposal_version)
    return item


@transaction.atomic
def remove_proposal_item(*, item: ProposalItem) -> None:
    _require_draft(item.proposal_version)
    version = item.proposal_version
    item.delete()
    calculate_proposal_version(version)


@dataclass
class ProposalConditionsData:
    price_table_label: str = ""
    payment_method: str = ""
    payment_method_other: str = ""
    payment_condition: str = ""
    contracted_start_date: date | None = None
    contracted_end_date: date | None = None
    expected_delivery_date: date | None = None
    expected_delivery_time: time | None = None
    expected_pickup_date: date | None = None
    expected_pickup_time: time | None = None
    delivery_location: object | None = None  # apps.operations.models.Location
    general_discount: Decimal = Decimal("0.00")
    interest_amount: Decimal = Decimal("0.00")
    freight_amount: Decimal = Decimal("0.00")
    special_clauses: str = ""
    payment_info_notes: str = ""
    general_notes: str = ""


@transaction.atomic
def update_draft_conditions(*, proposal_version: ProposalVersion, data: ProposalConditionsData) -> ProposalVersion:
    """
    Grava as condições comerciais/período/logística/textos de uma versão
    em RASCUNHO ("Salvar rascunho", seção 5/57) — nunca toca em
    itens/status/snapshots. Recalcula subtotal/total no final (seção 80):
    desconto geral/juros/frete mudam o total mesmo sem nenhum item
    alterado.
    """
    _require_draft(proposal_version)
    if data.general_discount < 0 or data.interest_amount < 0 or data.freight_amount < 0:
        raise ValueError("Desconto geral, juros e frete não podem ser negativos.")

    proposal_version.price_table_label = data.price_table_label
    proposal_version.payment_method = data.payment_method
    proposal_version.payment_method_other = data.payment_method_other
    proposal_version.payment_condition = data.payment_condition
    proposal_version.contracted_start_date = data.contracted_start_date
    proposal_version.contracted_end_date = data.contracted_end_date
    proposal_version.expected_delivery_date = data.expected_delivery_date
    proposal_version.expected_delivery_time = data.expected_delivery_time
    proposal_version.expected_pickup_date = data.expected_pickup_date
    proposal_version.expected_pickup_time = data.expected_pickup_time
    proposal_version.delivery_location = data.delivery_location
    proposal_version.general_discount = data.general_discount
    proposal_version.interest_amount = data.interest_amount
    proposal_version.freight_amount = data.freight_amount
    proposal_version.special_clauses = data.special_clauses
    proposal_version.payment_info_notes = data.payment_info_notes
    proposal_version.general_notes = data.general_notes
    proposal_version.save()

    calculate_proposal_version(proposal_version)
    return proposal_version


# --- Consulta de disponibilidade (informativa — seção 11/12/76/77) ----------


@dataclass
class AvailabilityResult:
    requested: int
    available: int

    @property
    def missing(self) -> int:
        return max(self.requested - self.available, 0)


def check_availability(*, equipment_model: EquipmentModel, requested_quantity: int) -> AvailabilityResult:
    """
    Só LEITURA — reaproveita `apps.equipment.models.Equipment.status`
    real (seção 76: "reutilizar services/regras operacionais existentes...
    Não assumir total cadastrado = disponível"): "disponível" é
    `Status.DISPONIVEL` entre os equipamentos ATIVOS daquele modelo, não
    o total cadastrado (que inclui em operação/manutenção/inativo).
    Nenhuma reserva, nenhum `Movement`, nenhuma seleção de patrimônio é
    criada aqui (seção 12/77, REGRA CRÍTICA) — é só uma contagem.
    """
    from apps.equipment.models import Equipment, Status

    available = Equipment.objects.filter(model=equipment_model, is_active=True, status=Status.DISPONIVEL).count()
    return AvailabilityResult(requested=requested_quantity, available=available)


# --- Emissão / versionamento / contrato / aceite ----------------------------


def _format_address_snapshot(address) -> str:
    if address is None:
        return ""
    parts = [
        f"{address.logradouro}, {address.numero}".strip(", "),
        address.complemento,
        address.bairro,
        f"{address.cidade}/{address.uf}".strip("/"),
        address.cep,
    ]
    return " — ".join(p for p in parts if p)


def _format_company_address_snapshot(company) -> str:
    parts = [
        f"{company.logradouro}, {company.numero}".strip(", "),
        company.bairro,
        f"{company.cidade}/{company.uf}".strip("/"),
        company.cep,
    ]
    return " — ".join(p for p in parts if p)


@transaction.atomic
def issue_proposal(*, proposal_version: ProposalVersion, issued_by: User) -> ProposalVersion:
    """
    Emissão (seção 58) — evento distinto de salvar (seção 57): valida,
    recalcula (autoridade do backend), CONGELA a versão (snapshots de
    cliente/Locus/vendedor, seção 21/38/39/40), gera o PDF, cria o
    `Attachment` (categoria Orçamento/Proposta, origem SYSTEM — seção 69)
    e marca `issued_at`/`issued_by`. Tudo na MESMA transação (seção 81).

    "Histórico" (seção 70) não ganhou uma tabela de eventos nova — os
    próprios registros (`Proposal.created_at`, `ProposalVersion.issued_at`/
    `accepted_at`, `Contract.created_at`) já são os "eventos"; a aba
    Histórico do Hub os funde numa timeline junto com `OpportunityStageChange`
    (ver `apps.crm.views.OpportunityDetailView`) — evita uma segunda
    arquitetura de auditoria paralela para o mesmo propósito que
    `django-simple-history`/`OpportunityStageChange`/`Movement` já cobrem
    no resto do projeto.
    """
    _require_draft(proposal_version)
    if not proposal_version.items.exists():
        raise ValueError("Não é possível emitir uma proposta sem nenhum item.")

    calculate_proposal_version(proposal_version)

    opportunity = proposal_version.proposal.opportunity
    client = opportunity.client
    company = get_company_profile()

    proposal_version.client_name_snapshot = client.display_name()
    proposal_version.client_document_snapshot = client.document
    proposal_version.client_contact_snapshot = client.contact_name
    proposal_version.client_phone_snapshot = client.phone
    proposal_version.client_email_snapshot = client.email
    proposal_version.client_address_snapshot = _format_address_snapshot(client.fiscal_address)

    proposal_version.company_name_snapshot = company.company_name
    proposal_version.company_document_snapshot = company.cnpj
    proposal_version.company_address_snapshot = _format_company_address_snapshot(company)
    proposal_version.company_phone_snapshot = company.phone
    proposal_version.company_email_snapshot = company.email
    proposal_version.seller_snapshot = str(opportunity.owner)

    proposal_version.status = ProposalVersionStatus.ISSUED
    proposal_version.issued_at = timezone.now()
    proposal_version.issued_by = issued_by
    proposal_version.save()

    from apps.crm.pdf import render_proposal_pdf

    pdf_bytes = render_proposal_pdf(proposal_version)
    create_attachment(
        NewAttachmentData(
            content_object=opportunity,
            category=AttachmentCategory.ORCAMENTO_PROPOSTA,
            created_by=issued_by,
            file_content=pdf_bytes,
            filename=f"{proposal_version.proposal.number}-v{proposal_version.version_number}.pdf",
            source=AttachmentSource.SYSTEM,
            description=f"Proposta Comercial — {proposal_version.proposal.number} v{proposal_version.version_number}",
        )
    )
    return proposal_version


@transaction.atomic
def create_new_version(*, proposal: Proposal, created_by: User) -> ProposalVersion:
    """
    Nova versão (seção 59) — clona condições + itens da versão mais
    recente para uma nova `ProposalVersion` DRAFT; a versão anterior
    NUNCA é editada (seção 60). Só permitido se a versão mais recente já
    não é mais rascunho (emitida ou aceita) — se ainda é DRAFT, já existe
    um rascunho para editar diretamente, criar uma segunda seria
    confuso/duplicado.
    """
    latest = proposal.latest_version
    if latest is None:
        raise ValueError("Esta proposta ainda não tem nenhuma versão.")
    if latest.status == ProposalVersionStatus.DRAFT:
        raise ValueError("Já existe uma versão em rascunho — edite-a diretamente em vez de criar uma nova versão.")

    new_version = ProposalVersion.objects.create(
        proposal=proposal,
        version_number=latest.version_number + 1,
        status=ProposalVersionStatus.DRAFT,
        price_table_label=latest.price_table_label,
        payment_method=latest.payment_method,
        payment_method_other=latest.payment_method_other,
        payment_condition=latest.payment_condition,
        contracted_start_date=latest.contracted_start_date,
        contracted_end_date=latest.contracted_end_date,
        expected_delivery_date=latest.expected_delivery_date,
        expected_delivery_time=latest.expected_delivery_time,
        expected_pickup_date=latest.expected_pickup_date,
        expected_pickup_time=latest.expected_pickup_time,
        delivery_location=latest.delivery_location,
        general_discount=latest.general_discount,
        interest_amount=latest.interest_amount,
        freight_amount=latest.freight_amount,
        special_clauses=latest.special_clauses,
        payment_info_notes=latest.payment_info_notes,
        general_notes=latest.general_notes,
    )
    for item in latest.items.all():
        ProposalItem.objects.create(
            proposal_version=new_version,
            equipment_model=item.equipment_model,
            description_snapshot=item.description_snapshot,
            quantity=item.quantity,
            unit_price=item.unit_price,
            item_discount_percent=item.item_discount_percent,
            notes=item.notes,
            order=item.order,
        )
    calculate_proposal_version(new_version)
    return new_version


@transaction.atomic
def generate_contract(*, proposal_version: ProposalVersion, created_by: User) -> Contract:
    """
    Contrato (seção 63/67) — documento SEPARADO derivado de uma
    `ProposalVersion` já emitida (nunca de uma DRAFT: um contrato precisa
    de uma versão com snapshot congelado, exatamente a mesma garantia que
    o PDF de proposta já exige). `issue_proposal()` já ficou responsável
    por congelar; se a versão ainda é DRAFT, quem chama esta função
    (`generate_documents()`) já a emitiu antes.
    """
    if proposal_version.status == ProposalVersionStatus.DRAFT:
        raise ValueError("É necessário emitir a proposta (congelar a versão) antes de gerar o contrato.")

    number = _next_document_number(key="contract", prefix="CONTR")
    contract = Contract.objects.create(proposal_version=proposal_version, number=number, created_by=created_by)

    from apps.crm.pdf import render_contract_pdf

    pdf_bytes = render_contract_pdf(contract)
    create_attachment(
        NewAttachmentData(
            content_object=proposal_version.proposal.opportunity,
            category=AttachmentCategory.CONTRATO,
            created_by=created_by,
            file_content=pdf_bytes,
            filename=f"{number}.pdf",
            source=AttachmentSource.SYSTEM,
            description=(
                f"Contrato — {number} (a partir de {proposal_version.proposal.number} "
                f"v{proposal_version.version_number})"
            ),
        )
    )
    return contract


class DocumentType(models.TextChoices):
    PROPOSTA = "PROPOSTA", "Proposta Comercial"
    CONTRATO = "CONTRATO", "Contrato"
    PROPOSTA_E_CONTRATO = "PROPOSTA_E_CONTRATO", "Proposta + Contrato"


@transaction.atomic
def generate_documents(*, proposal_version: ProposalVersion, document_type: str, actor: User) -> dict:
    """
    Único ponto de entrada do dropdown "Gerar documento" (seção 6/64/65).
    "Proposta + Contrato" gera DOIS registros/documentos distintos, nunca
    um PDF híbrido (seção 65) — e nenhuma das três opções marca a
    Opportunity como ganha (seção 7/66): só `accept_proposal_version()`
    faz isso.
    """
    if document_type not in DocumentType.values:
        raise ValueError(f"Tipo de documento inválido: {document_type!r}.")

    result: dict = {}
    if document_type in (DocumentType.PROPOSTA, DocumentType.PROPOSTA_E_CONTRATO):
        if proposal_version.status == ProposalVersionStatus.DRAFT:
            issue_proposal(proposal_version=proposal_version, issued_by=actor)
        result["proposal_version"] = proposal_version

    if document_type in (DocumentType.CONTRATO, DocumentType.PROPOSTA_E_CONTRATO):
        # Gerar só o Contrato (sem "Proposta Comercial" selecionada) ainda
        # exige uma versão congelada — a emissão acontece por baixo, do
        # mesmo jeito, mas o Anexo de categoria "Orçamento/Proposta"
        # também é criado nesse caso (é o efeito colateral correto de
        # congelar a versão, não um Anexo espúrio: a versão agora tem um
        # PDF de proposta real, mesmo que o usuário só tenha pedido o
        # contrato).
        if proposal_version.status == ProposalVersionStatus.DRAFT:
            issue_proposal(proposal_version=proposal_version, issued_by=actor)
        result["contract"] = generate_contract(proposal_version=proposal_version, created_by=actor)

    return result


def acceptable_proposal_versions(opportunity: Opportunity) -> QuerySet[ProposalVersion]:
    """Versões candidatas ao aceite (seção 72/73): emitidas e ainda não aceitas, de qualquer Proposal desta Opportunity."""
    return ProposalVersion.objects.filter(
        proposal__opportunity=opportunity, status=ProposalVersionStatus.ISSUED
    ).select_related("proposal").order_by("-issued_at")


@transaction.atomic
def accept_proposal_version(*, proposal_version: ProposalVersion, accepted_by: User, won_stage: OpportunityStage) -> ProposalVersion:
    """
    Aceite (seção 71/74) — o ÚNICO efeito colateral sobre a Opportunity é
    via `change_opportunity_stage()` já existente (nunca uma segunda
    gravação de won_at/closed_value). `closed_value` da Opportunity passa
    a ser sempre `proposal_version.total` quando o aceite ocorre por uma
    versão comercial (decisão da seção 75, documentada em
    `RELATORIO_PRODUTOS_SERVICOS.md`: evita duas fontes conflitantes) — o
    campo `closed_value` manual do modal "Orçamento aceito" antigo
    continua existindo só para o caso de a oportunidade ser ganha SEM
    nenhuma proposta emitida (fora do fluxo desta implementação).
    """
    if proposal_version.status != ProposalVersionStatus.ISSUED:
        raise ValueError("Só uma versão EMITIDA (não rascunho, não já aceita) pode ser aceita.")

    proposal_version.status = ProposalVersionStatus.ACCEPTED
    proposal_version.accepted_at = timezone.now()
    proposal_version.accepted_by = accepted_by
    proposal_version.save()

    change_opportunity_stage(
        opportunity_id=proposal_version.proposal.opportunity_id,
        new_stage=won_stage,
        changed_by=accepted_by,
        reason=f"Proposta {proposal_version.proposal.number} v{proposal_version.version_number} aceita.",
        closed_value=proposal_version.total,
    )
    return proposal_version


# --- Histórico (seção 70) ----------------------------------------------------


@dataclass
class TimelineEntry:
    when: datetime
    label: str
    actor: str = ""


def build_opportunity_timeline(opportunity: Opportunity) -> list[TimelineEntry]:
    """
    "Histórico" = eventos, não arquivos (seção 70) — funde
    `OpportunityStageChange` (já existente) com os eventos que os
    próprios registros de Proposta/Versão/Contrato JÁ representam
    (criação, emissão, aceite, geração de contrato), sem nenhuma tabela
    de eventos nova. Mais recente primeiro.
    """
    entries: list[TimelineEntry] = []
    for change in opportunity.stage_changes.select_related("from_stage", "to_stage", "changed_by"):
        origin = change.from_stage.name if change.from_stage else "(criação)"
        entries.append(
            TimelineEntry(when=change.changed_at, label=f"Etapa: {origin} → {change.to_stage.name}", actor=str(change.changed_by))
        )

    proposals = opportunity.proposals.prefetch_related("versions", "versions__contracts").order_by("created_at")
    for proposal in proposals:
        entries.append(TimelineEntry(when=proposal.created_at, label=f"Proposta {proposal.number} criada.", actor=str(proposal.created_by)))
        for version in proposal.versions.all():
            if version.issued_at:
                entries.append(
                    TimelineEntry(
                        when=version.issued_at,
                        label=f"Proposta {proposal.number} — Versão {version.version_number} emitida.",
                        actor=str(version.issued_by) if version.issued_by else "",
                    )
                )
            if version.accepted_at:
                entries.append(
                    TimelineEntry(
                        when=version.accepted_at,
                        label=f"Proposta {proposal.number} — Versão {version.version_number} aceita.",
                        actor=str(version.accepted_by) if version.accepted_by else "",
                    )
                )
            for contract in version.contracts.all():
                entries.append(
                    TimelineEntry(when=contract.created_at, label=f"Contrato {contract.number} gerado.", actor=str(contract.created_by))
                )

    entries.sort(key=lambda entry: entry.when, reverse=True)
    return entries
