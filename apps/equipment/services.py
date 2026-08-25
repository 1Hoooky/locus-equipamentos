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
    EquipmentBatch,
    Status,
    StatusHistory,
)

# Limite por operação de cadastro em lote (melhoria operacional da Fase 1,
# 25/08/2026). Justificativa: o inventário inicial tem "centenas" de
# equipamentos, mas normalmente em lotes separados por modelo — 500 cobre
# com folga qualquer lote real de um único modelo, sem abrir espaço para
# uma operação acidental ou abusiva travar a linha do EquipmentModel (via
# select_for_update, dentro de create_equipment()) por tempo desproporcional:
# cada unidade custa ~3 consultas ao banco, então 500 unidades já é uma
# transação de centenas de queries — um valor bem maior viraria um risco
# real de lock prolongado sem ganho prático correspondente.
MAX_BATCH_QUANTITY = 500


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


@dataclass
class NewEquipmentBatchData:
    model_id: int
    quantity: int
    created_by: User
    condition: str = Condition.BOM
    supplier: str = ""
    acquisition_date: datetime.date | None = None
    acquisition_value: Decimal | None = None
    notes: str = ""


@transaction.atomic
def create_equipment_batch(data: NewEquipmentBatchData) -> EquipmentBatch:
    """
    Cadastro em lote (melhoria operacional da Fase 1, pedida em
    25/08/2026): cria `data.quantity` unidades independentes do mesmo
    modelo, cada uma com patrimônio próprio e permanente — nunca um único
    `Equipment` com "quantidade".

    Reuso deliberado: chama `create_equipment()` — a MESMA função do
    cadastro individual — `quantity` vezes, dentro desta única transação.
    Não existe um segundo contador nem geração manual de patrimônio aqui.
    Cada chamada a `create_equipment()` já faz `select_for_update()` na
    linha do `EquipmentModel` (ver docstring do módulo); chamá-la em
    sequência, na mesma transação, preserva exatamente a mesma garantia de
    unicidade/sequência sob concorrência que o cadastro individual já tem
    — inclusive contra outro lote ou outro cadastro individual do MESMO
    modelo rodando ao mesmo tempo, que ficam serializados pelo lock da
    mesma linha.

    Atomicidade: por estar inteira dentro de um único `@transaction.atomic`
    (o `@transaction.atomic` de `create_equipment()` só abre um savepoint
    aninhado, não uma transação nova), qualquer exceção no meio do laço
    desfaz TODAS as criações já feitas nesta chamada — nunca sobra um lote
    "pela metade" no banco.

    Não gera QR/etiqueta/ZIP aqui — essas exportações usam os geradores já
    existentes (`apps.qrcodes.services`), sob demanda, só depois que o
    lote já está persistido (pedido explícito do usuário: nada de PDF/PNG/
    ZIP durante a transação de cadastro).
    """
    if data.quantity < 1:
        raise ValueError("A quantidade precisa ser de pelo menos 1 unidade.")
    if data.quantity > MAX_BATCH_QUANTITY:
        raise ValueError(f"A quantidade máxima por operação de lote é {MAX_BATCH_QUANTITY} unidades.")
    if data.condition not in Condition.values:
        raise ValueError(f"Condição inválida: {data.condition!r}.")

    model = EquipmentModel.objects.get(pk=data.model_id)
    if not model.is_active:
        raise ValueError("Não é possível cadastrar equipamentos em lote para um modelo inativo.")

    # first_patrimonio/last_patrimonio só existem depois do laço abaixo —
    # criamos o registro do lote já no início (para servir de FK a cada
    # Equipment conforme vai sendo criado) e completamos esses dois campos
    # ao final, ainda dentro da mesma transação atômica.
    batch = EquipmentBatch.objects.create(
        model=model,
        quantity=data.quantity,
        condition=data.condition,
        created_by=data.created_by,
        first_patrimonio="",
        last_patrimonio="",
    )

    equipment_list = []
    for _ in range(data.quantity):
        equipment = create_equipment(
            NewEquipmentData(
                model_id=data.model_id,
                created_by=data.created_by,
                # Deliberadamente SEM serial_number/legacy_code: são
                # identificadores individuais por unidade física e não
                # podem ser preenchidos em massa para um lote inteiro.
                supplier=data.supplier,
                acquisition_date=data.acquisition_date,
                acquisition_value=data.acquisition_value,
                condition=data.condition,
                notes=data.notes,
            )
        )
        equipment.batch = batch
        equipment.save(update_fields=["batch"])
        equipment_list.append(equipment)

    batch.first_patrimonio = equipment_list[0].patrimonio
    batch.last_patrimonio = equipment_list[-1].patrimonio
    batch.save(update_fields=["first_patrimonio", "last_patrimonio"])

    return batch


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
