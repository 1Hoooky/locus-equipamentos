"""
Geração atômica de patrimônio — especificação, seção 8 ("Geração atômica
do patrimônio").

A estratégia é `select_for_update()` na linha do `EquipmentModel`: isso
trava especificamente aquela linha até a transação terminar, então dois
cadastros concorrentes do MESMO modelo são serializados (um espera o
outro), mas cadastros de modelos DIFERENTES não se bloqueiam entre si —
cada `EquipmentModel` tem sua própria fila.

Deliberadamente NÃO fazemos `Equipment.objects.filter(model=model).count()
+ 1` nem `MAX(model_sequence) + 1` — qualquer uma dessas abordagens tem
uma janela real de corrida entre o SELECT e o INSERT. Usamos um contador
dedicado (`EquipmentModel.last_sequence`) justamente para que o lock seja
sobre uma única linha pequena, não sobre a tabela de equipamentos inteira.

A constraint `uniq_model_sequence_per_model` no banco (ver
apps/equipment/models.py) é a segunda linha de defesa: se por qualquer
motivo esta função for contornada, o banco rejeita a gravação em vez de
aceitar um patrimônio duplicado silenciosamente.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from apps.accounts.models import User
from apps.catalog.models import EquipmentModel
from apps.equipment.models import (
    Condition,
    ConditionHistory,
    Equipment,
    Status,
    StatusHistory,
)


def build_patrimonio(code: str, sequence: int) -> str:
    """`LOC-{CODE}-{SEQUENCE}`, com no mínimo 4 dígitos (seção 5)."""
    return f"LOC-{code}-{sequence:04d}" if sequence <= 9999 else f"LOC-{code}-{sequence}"


@dataclass
class NewEquipmentData:
    model_id: int
    created_by: User
    serial_number: str = ""
    legacy_code: str = ""
    supplier: str = ""
    acquisition_date: datetime.date | None = None
    acquisition_value: Decimal | None = None
    status: str = Status.DISPONIVEL
    condition: str = Condition.BOM
    notes: str = ""


@transaction.atomic
def create_equipment(data: NewEquipmentData) -> Equipment:
    """
    Cria um Equipment com patrimônio gerado atomicamente para o modelo
    informado. Esta é a ÚNICA forma suportada de criar um equipamento —
    views e comandos de importação devem sempre passar por aqui, nunca
    instanciar `Equipment(...)` diretamente com um patrimônio calculado
    à mão.
    """
    model = EquipmentModel.objects.select_for_update().get(pk=data.model_id)

    model.last_sequence += 1
    model.save(update_fields=["last_sequence", "updated_at"])

    sequence = model.last_sequence
    patrimonio = build_patrimonio(model.code, sequence)

    return Equipment.objects.create(
        patrimonio=patrimonio,
        model=model,
        model_sequence=sequence,
        category=model.category,
        serial_number=data.serial_number,
        legacy_code=data.legacy_code,
        supplier=data.supplier,
        acquisition_date=data.acquisition_date,
        acquisition_value=data.acquisition_value,
        status=data.status,
        condition=data.condition,
        notes=data.notes,
        created_by=data.created_by,
    )


@transaction.atomic
def reclassify_model(*, equipment: Equipment, new_model: EquipmentModel, reason: str, changed_by: User) -> Equipment:
    """
    Procedimento PADRÃO de correção de classificação (seção 8): corrige
    `model` (e `category`, que é denormalizado a partir dele), mas nunca
    toca em `patrimonio` nem `model_sequence`. A etiqueta física já
    impressa continua identificando a mesma unidade para sempre.

    `reason` é obrigatório por design (a assinatura da função não aceita
    chamada sem ele) — fica registrado no django-simple-history como parte
    do snapshot da alteração.
    """
    if not reason.strip():
        raise ValueError("Reclassificação de modelo exige um motivo (auditoria, seção 8).")

    equipment._change_reason = reason  # consumido pelo django-simple-history
    equipment.model = new_model
    equipment.category = new_model.category
    equipment.save(update_fields=["model", "category", "updated_at"])
    return equipment


@transaction.atomic
def supersede_equipment(*, equipment: Equipment, new_model: EquipmentModel, reason: str, changed_by: User) -> Equipment:
    """
    Procedimento EXCEPCIONAL de reemissão de patrimônio (seção 8): inativa
    o equipamento atual e cria um novo, com patrimônio gerado do zero sob
    o modelo correto. Usar apenas quando a divergência for grande demais
    para conviver com a reclassificação simples — exige reimpressão da
    etiqueta física.
    """
    if not reason.strip():
        raise ValueError("Reemissão de patrimônio exige um motivo (auditoria, seção 8).")

    new_equipment = create_equipment(
        NewEquipmentData(
            model_id=new_model.pk,
            created_by=changed_by,
            serial_number=equipment.serial_number,
            legacy_code=equipment.legacy_code,
            supplier=equipment.supplier,
            acquisition_date=equipment.acquisition_date,
            acquisition_value=equipment.acquisition_value,
            condition=equipment.condition,
            notes=f"Reemitido a partir de {equipment.patrimonio}. Motivo: {reason}",
        )
    )

    equipment._change_reason = f"Superseded por {new_equipment.patrimonio}. Motivo: {reason}"
    equipment.is_active = False
    equipment.status = Status.INATIVO
    equipment.superseded_by = new_equipment
    equipment.save(update_fields=["is_active", "status", "superseded_by", "updated_at"])

    return new_equipment


@transaction.atomic
def change_status(*, equipment: Equipment, new_status: str, reason: str, changed_by: User) -> Equipment:
    """
    Único caminho suportado para mudar `Equipment.status` (fechamento da
    Fase 1, itens 5/6): grava o novo valor e cria o `StatusHistory`
    correspondente na MESMA transação, sempre com motivo — nunca os dois
    passos separados, para não existir mudança de status sem o evento
    estruturado que a acompanha.
    """
    if not reason.strip():
        raise ValueError("Mudança de status exige um motivo.")
    if new_status not in Status.values:
        raise ValueError(f"Status inválido: {new_status!r}.")
    if new_status == equipment.status:
        raise ValueError("O novo status é igual ao status atual.")

    old_status = equipment.status
    equipment._change_reason = f"Status: {old_status} → {new_status}. Motivo: {reason}"
    equipment.status = new_status
    equipment.save(update_fields=["status", "updated_at"])

    StatusHistory.objects.create(
        equipment=equipment,
        old_value=old_status,
        new_value=new_status,
        changed_by=changed_by,
        reason=reason,
    )
    return equipment


@transaction.atomic
def change_condition(*, equipment: Equipment, new_condition: str, reason: str, changed_by: User) -> Equipment:
    """Único caminho suportado para mudar `Equipment.condition` — mesmo raciocínio de `change_status()`."""
    if not reason.strip():
        raise ValueError("Mudança de condição exige um motivo.")
    if new_condition not in Condition.values:
        raise ValueError(f"Condição inválida: {new_condition!r}.")
    if new_condition == equipment.condition:
        raise ValueError("A nova condição é igual à condição atual.")

    old_condition = equipment.condition
    equipment._change_reason = f"Condição: {old_condition} → {new_condition}. Motivo: {reason}"
    equipment.condition = new_condition
    equipment.save(update_fields=["condition", "updated_at"])

    ConditionHistory.objects.create(
        equipment=equipment,
        old_value=old_condition,
        new_value=new_condition,
        changed_by=changed_by,
        reason=reason,
    )
    return equipment


def get_equipment_history_timeline(equipment: Equipment) -> list[dict]:
    """
    Linha do tempo única de eventos do equipamento, para a ficha
    autenticada (seção "Histórico do equipamento"). NÃO é uma nova fonte
    de dados: só lê e funde `StatusHistory`/`ConditionHistory`, que já são
    gravados exclusivamente por `change_status()`/`change_condition()`
    acima — nenhum campo novo, nenhuma tabela nova, nenhum evento novo.

    Cada evento vira um dict num formato comum (`event_type`,
    `event_type_label`, `old_value_display`, `new_value_display`,
    `reason`, `changed_by`, `changed_at`) para que o template possa
    iterar uma única lista homogênea. É esse formato comum — não o
    template — que permite plugar novos tipos de evento no futuro
    (Manutenção/Higienização/Movimentação, Fase 2): basta um novo bloco
    aqui que produza dicts no mesmo formato, sem tocar na página.
    """
    events = []

    for h in equipment.status_history.select_related("changed_by").all():
        events.append(
            {
                "event_type": "status",
                "event_type_label": "Status",
                "old_value_display": h.get_old_value_display(),
                "new_value_display": h.get_new_value_display(),
                "reason": h.reason,
                "changed_by": h.changed_by,
                "changed_at": h.changed_at,
            }
        )

    for h in equipment.condition_history.select_related("changed_by").all():
        events.append(
            {
                "event_type": "condicao",
                "event_type_label": "Condição",
                "old_value_display": h.get_old_value_display(),
                "new_value_display": h.get_new_value_display(),
                "reason": h.reason,
                "changed_by": h.changed_by,
                "changed_at": h.changed_at,
            }
        )

    # `StatusHistory`/`ConditionHistory` já vêm ordenados (`-changed_at`)
    # individualmente pelo Meta de cada model, mas a fusão dos dois
    # precisa de uma reordenação explícita para o conjunto combinado.
    events.sort(key=lambda event: event["changed_at"], reverse=True)
    return events
