"""
Services de `apps.maintenance` — fundação da próxima etapa da Fase 2
(decisões 1-10 sobre a proposta de 26/08/2026, aprovadas em 27/08/2026).
Único caminho suportado para abrir/concluir/cancelar `Maintenance` e para
registrar/cancelar `Cleaning` — nunca `Maintenance.objects.create()`/
`.save()`/`Cleaning.objects.create()` direto em view/form, mesma
disciplina de `apps.operations.services.create_movement()`.

=============================================================================
MATRIZ 1 — Status da Maintenance (estado anterior → abertura → durante →
fechamento → estado final)
=============================================================================

Precondição de abertura SEM `departure_movement` (manutenção em campo, o
próprio `open_maintenance()` decide mudar o status): `Equipment.status`
precisa estar em {DISPONIVEL, EM_OPERACAO} — MESMA regra de precondição já
usada por `ENVIO_MANUTENCAO` em `apps.operations.services._TRANSITION_RULES`,
por consistência (não inventa um terceiro conjunto de status válidos).

Precondição de abertura COM `departure_movement`: nenhuma precondição de
status é validada por `open_maintenance()` — o `Movement` ENVIO_MANUTENCAO
já validou e já mudou o status antes; `Maintenance` só registra o vínculo.

Linha A — Manutenção em ESTOQUE, sem Movement (conserto no próprio pátio):
    status anterior:  DISPONIVEL
    abertura:         open_maintenance(departure_movement=None) →
                       change_status(MANUTENCAO); status_before=DISPONIVEL
    durante:          MANUTENCAO
    fechamento:       close_maintenance() → restaura status_before
                       → change_status(DISPONIVEL)
    status final:     DISPONIVEL

Linha B — Manutenção em CLIENTE, sem Movement (conserto no local):
    status anterior:  EM_OPERACAO
    abertura:         change_status(MANUTENCAO); status_before=EM_OPERACAO
    durante:          MANUTENCAO
    fechamento:       restaura status_before → change_status(EM_OPERACAO)
    status final:     EM_OPERACAO

Linha C — Manutenção COM ENVIO_MANUTENCAO (o Movement já rodou antes):
    status anterior:  DISPONIVEL ou EM_OPERACAO (o que o Movement exigiu)
    Movement:         ENVIO_MANUTENCAO já mudou status → MANUTENCAO
    abertura:         open_maintenance(departure_movement=<mv>) → NENHUMA
                       chamada a change_status() (já está MANUTENCAO);
                       status_before é só um snapshot informativo (=
                       MANUTENCAO), NÃO é usado para restaurar nada
    durante:           MANUTENCAO
    fechamento SEM return_movement: NENHUMA mudança de status — o
                       equipamento continua fisicamente fora, então o
                       status continua refletindo isso corretamente
    fechamento COM return_movement (RETORNO_MANUTENCAO ou
                       RETORNO_ESTOQUE já registrado): Maintenance só
                       grava o vínculo — o Movement, não a Maintenance,
                       já tinha mudado o status para DISPONIVEL
    status final:      MANUTENCAO (se ainda não voltou) ou DISPONIVEL
                       (quando o Movement de retorno existir — dentro ou
                       fora do fechamento da Maintenance, tanto faz a
                       ordem)

Linha D — Manutenção SEM movimentação física: generalização de A/B acima
    (o que muda é só o valor concreto de status_before, DISPONIVEL numa
    manutenção de estoque ou EM_OPERACAO numa manutenção em cliente).

Linha E — CANCELAMENTO:
    E1 (aberta SEM departure_movement, cancelada): restaura status_before,
        MESMA lógica do fechamento normal — não faz sentido deixar o
        equipamento preso em MANUTENCAO por uma ficha aberta por engano.
    E2 (aberta COM departure_movement, cancelada): NENHUMA mudança de
        status — cancelar a ficha não desfaz o fato físico de que o
        equipamento já foi para a Location de manutenção; só um Movement
        de retorno resolve isso, como na linha C.

Regra de IDEMPOTÊNCIA/corrida (linhas A, B, D, E1 — sempre que
`departure_movement is None`, ou seja, sempre que ESTA Maintenance é quem
"dona" a mudança de status): o fechamento/cancelamento só tenta restaurar
se `Equipment.status` (lido sob `select_for_update()`) AINDA for
MANUTENCAO no momento do fechamento. Ver Matriz 2: é POSSÍVEL um Movement
externo (ex.: RETORNO_ESTOQUE) mudar o status "por fora" enquanto a
Maintenance segue aberta — nesse caso a restauração é pulada em silêncio
(o status já reflete a realidade física mais recente, mais confiável que
o snapshot). Implementado em `_restore_status_if_owned()`.

Estados impossíveis, todos bloqueados por constraint de banco + validação
de service (dupla camada, mesmo padrão do resto do projeto):
    - Duas Maintenance ABERTA para o mesmo equipamento ao mesmo tempo
      (UniqueConstraint condicional + checagem em open_maintenance()).
    - Maintenance CONCLUIDA sem `service_performed` (CheckConstraint).
    - `closed_at` presente com status ABERTA, ou ausente com status
      CONCLUIDA/CANCELADA (CheckConstraint).
    - `departure_movement`/`return_movement` reclamado por duas
      Maintenance diferentes (unique=True na FK + checagem em service).
    - Fechar/cancelar uma Maintenance que não está ABERTA.

=============================================================================
MATRIZ 2 — Maintenance.status (ABERTA) × MovementType
=============================================================================

Nenhuma linha desta matriz precisa de código novo em
`apps.operations.services` — o resultado já emerge das regras que já
existem hoje em `_TRANSITION_RULES` (equipment.status precisa estar em
MANUTENCAO sempre que a Maintenance "dona" o status, ou já está em
MANUTENCAO por causa de um `departure_movement`). Deliberadamente NENHUMA
mudança foi feita em `apps.operations.services` para este fechamento —
Movement continua descentralizado de Maintenance (decisão 4: "Maintenance
aberta NÃO bloqueia automaticamente qualquer Movement").

    MovementType         | precondição de status (já existente)  | compatível com MANUTENCAO? | efeito com Maintenance ABERTA
    ----------------------|-----------------------------------------|------------------------------|--------------------------------
    INSTALACAO            | DISPONIVEL                               | não                          | bloqueado (ValueError já existente)
    RETIRADA               | EM_OPERACAO                              | não                          | bloqueado
    TRANSFERENCIA          | EM_OPERACAO                              | não                          | bloqueado
    RETORNO_ESTOQUE        | EM_OPERACAO ou MANUTENCAO                | sim                          | permitido — muda status p/ DISPONIVEL "por fora"; ver regra de idempotência acima
    ENVIO_MANUTENCAO       | DISPONIVEL ou EM_OPERACAO                | não                          | bloqueado — evita reenviar um equipamento já em manutenção
    RETORNO_MANUTENCAO     | MANUTENCAO                                | sim                          | permitido — caminho natural de retorno; se linkado como return_movement ao fechar, sem mudança de status duplicada
    OUTRO                  | nenhuma                                   | sim (sempre)                 | permitido sempre — evento só anotado, nunca muda status

Observação: RETORNO_ESTOQUE e RETORNO_MANUTENCAO continuam permitidos
"por fora" de uma Maintenance aberta DE PROPÓSITO — alguém pode devolver o
equipamento fisicamente antes de fechar a ficha de manutenção no sistema.
Isso não é um bug: é o motivo da regra de idempotência acima existir.

=============================================================================
MATRIZ 3 — Estratégia de restauração de status (decisão 3)
=============================================================================

Resumo executivo (o detalhe está na Matriz 1 + docstring de
`_restore_status_if_owned()`): `Maintenance.status_before` é um snapshot
DETERMINÍSTICO de `Equipment.status`, capturado automaticamente por
`open_maintenance()` no instante da abertura — nunca uma adivinhação tipo
"provavelmente DISPONIVEL ou EM_OPERACAO" no fechamento. A restauração só
acontece quando a própria Maintenance foi quem mudou o status (sem
`departure_movement`), e só se o status ainda não tiver sido alterado por
fora entre a abertura e o fechamento.

=============================================================================
DECISÃO 9 — `next_due_at`: pertence ao evento, não a uma agenda separada
=============================================================================

`Maintenance.next_due_at`/`Cleaning.next_due_at` são campos NULOS,
puramente informativos: "a última data planejada conhecida", preenchidos
opcionalmente no fechamento (Maintenance) ou no registro (Cleaning). Não
existe, e não é criado aqui, nenhum motor de recorrência — nenhum
intervalo/frequência, nenhum job, nenhum agendamento automático.

Por que isso NÃO conflita "histórico" com "agenda" a ponto de exigir um
model separado agora: o campo não carrega NENHUM comportamento — não
dispara nada, não é lido por nenhum processo automático nesta etapa
(dashboard/calendário/notificações estão explicitamente fora de escopo).
É só o último plano conhecido, e "qual é a próxima manutenção prevista de
um equipamento" é sempre uma leitura (a Maintenance/Cleaning mais recente
com `next_due_at` preenchido), nunca uma escrita coordenada por outra
tabela.

Se uma fase futura precisar de recorrência de verdade (regra tipo "a cada
90 dias"), a solução correta é um model novo e separado
(`MaintenanceSchedule`/regra de recorrência) — não forçar `Maintenance` a
ser simultaneamente histórico E agenda. Migrar para esse desenho futuro
não exige alterar o campo atual: ele continua fazendo sentido como "o
plano mais recente conhecido", ou é aposentado numa migration futura, sem
conflito com o que existe hoje. Decisão registrada aqui porque envolve
os dois models desta fundação — não é uma mudança estrutural em nenhum
dos dois, por isso não bloqueou a implementação.

=============================================================================
"""

from dataclasses import dataclass
from datetime import date, datetime

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.equipment.models import Condition, Equipment, Status
from apps.equipment.services import change_condition, change_status
from apps.maintenance.models import Cleaning, Maintenance, MaintenanceStatus, MaintenanceType
from apps.operations.models import Movement, MovementType

# Mesmo conjunto de status válido que `ENVIO_MANUTENCAO` já exige em
# `apps.operations.services._TRANSITION_RULES` — reaproveitado aqui por
# consistência, não redefinido do zero.
_OPEN_WITHOUT_MOVEMENT_STATUSES = (Status.DISPONIVEL, Status.EM_OPERACAO)

# Tipos de Movement aceitos como `return_movement` — RETORNO_MANUTENCAO é
# o caminho "normal", mas RETORNO_ESTOQUE também é uma forma legítima de
# trazer o equipamento de volta (ver Matriz 2: os dois aceitam MANUTENCAO
# como precondição de status em `_TRANSITION_RULES`).
_RETURN_MOVEMENT_TYPES = (MovementType.RETORNO_MANUTENCAO, MovementType.RETORNO_ESTOQUE)


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------


@dataclass
class NewMaintenanceData:
    equipment_id: int
    maintenance_type: str
    responsible: User
    created_by: User
    diagnosis: str = ""
    notes: str = ""
    departure_movement: Movement | None = None


def _validate_departure_movement(*, movement: Movement, equipment: Equipment) -> None:
    if movement.equipment_id != equipment.pk:
        raise ValueError("A movimentação de envio informada não pertence a este equipamento.")
    if movement.movement_type != MovementType.ENVIO_MANUTENCAO:
        raise ValueError("A movimentação de envio precisa ser do tipo 'Envio para manutenção'.")
    if Maintenance.objects.filter(departure_movement=movement).exists():
        raise ValueError("Esta movimentação de envio já está vinculada a outra manutenção.")


@transaction.atomic
def open_maintenance(data: NewMaintenanceData) -> Maintenance:
    """
    Único caminho suportado para abrir uma `Maintenance`. Ver Matriz 1
    (topo deste módulo) para o comportamento completo de status —
    resumo: sem `departure_movement`, esta função MUDA
    `Equipment.status` para MANUTENCAO (via `change_status()`, nunca
    atribuição direta) e grava `status_before` para permitir restauração
    determinística no fechamento; com `departure_movement`, o status já
    foi alterado pelo Movement, e esta função não toca nele.
    """
    if data.maintenance_type not in MaintenanceType.values:
        raise ValueError(f"Tipo de manutenção inválido: {data.maintenance_type!r}.")

    equipment = Equipment.objects.select_for_update().get(pk=data.equipment_id)

    # Dupla camada com a UniqueConstraint condicional do model — mensagem
    # clara em vez de depender só do IntegrityError (mesmo padrão de
    # `_validate_location_client_matches_type()`).
    if Maintenance.objects.filter(equipment=equipment, status=MaintenanceStatus.ABERTA).exists():
        raise ValueError("Já existe uma manutenção aberta para este equipamento.")

    status_before = equipment.status

    if data.departure_movement is not None:
        _validate_departure_movement(movement=data.departure_movement, equipment=equipment)
        # Status já foi alterado pelo Movement — Maintenance não mexe aqui
        # (Matriz 1, linha C).
    else:
        if equipment.status not in _OPEN_WITHOUT_MOVEMENT_STATUSES:
            allowed = "/".join(Status(s).label for s in _OPEN_WITHOUT_MOVEMENT_STATUSES)
            raise ValueError(
                "Só é possível abrir manutenção sem movimentação associada para um equipamento com status "
                f"{allowed}. Status atual: {equipment.get_status_display()}."
            )
        change_status(
            equipment=equipment,
            new_status=Status.MANUTENCAO,
            reason=f"Manutenção aberta sem movimentação associada (responsável: {data.responsible}).",
            changed_by=data.created_by,
        )

    maintenance = Maintenance(
        equipment=equipment,
        maintenance_type=data.maintenance_type,
        status=MaintenanceStatus.ABERTA,
        diagnosis=data.diagnosis,
        condition_before=equipment.condition,
        status_before=status_before,
        departure_movement=data.departure_movement,
        responsible=data.responsible,
        notes=data.notes,
        created_by=data.created_by,
    )
    maintenance._change_reason = "Manutenção aberta."
    maintenance.save()
    return maintenance


def _validate_return_movement(*, movement: Movement, equipment: Equipment) -> None:
    if movement.equipment_id != equipment.pk:
        raise ValueError("A movimentação de retorno informada não pertence a este equipamento.")
    if movement.movement_type not in _RETURN_MOVEMENT_TYPES:
        raise ValueError(
            "A movimentação de retorno precisa ser do tipo 'Retorno da manutenção' ou 'Retorno ao estoque'."
        )
    if Maintenance.objects.filter(return_movement=movement).exists():
        raise ValueError("Esta movimentação de retorno já está vinculada a outra manutenção.")


def _restore_status_if_owned(*, maintenance: Maintenance, equipment: Equipment, changed_by: User, event_label: str) -> None:
    """
    Só restaura `Equipment.status` quando ESTA Maintenance foi quem o
    alterou na abertura (`departure_movement is None`) — nunca quando a
    mudança veio de um Movement (decisão 3: sem restauração "provável",
    só snapshot determinístico via `status_before`).

    Idempotente/seguro contra corrida (Matriz 2): se o status já tiver
    sido alterado por fora enquanto a manutenção seguia aberta (ex.: um
    RETORNO_ESTOQUE registrado diretamente), esta função não faz nada —
    o status atual já reflete a realidade física mais recente, mais
    confiável que o snapshot da abertura.
    """
    if maintenance.departure_movement_id is not None:
        return
    if not maintenance.status_before:
        return
    if equipment.status != Status.MANUTENCAO:
        return
    if equipment.status == maintenance.status_before:
        return
    change_status(
        equipment=equipment,
        new_status=maintenance.status_before,
        reason=f"Restaurado automaticamente ao fechar manutenção ({event_label}), sem movimentação associada.",
        changed_by=changed_by,
    )


@dataclass
class CloseMaintenanceData:
    service_performed: str
    closed_by: User
    condition_after: str = ""
    return_movement: Movement | None = None


@transaction.atomic
def close_maintenance(*, maintenance: Maintenance, data: CloseMaintenanceData) -> Maintenance:
    """Único caminho suportado para concluir uma `Maintenance` ABERTA. Ver Matriz 1, linhas A/B/C."""
    maintenance = Maintenance.objects.select_for_update().get(pk=maintenance.pk)
    if maintenance.status != MaintenanceStatus.ABERTA:
        raise ValueError("Só é possível concluir uma manutenção que esteja aberta.")
    if not data.service_performed.strip():
        raise ValueError("Conclusão de manutenção exige o registro do serviço executado.")

    equipment = Equipment.objects.select_for_update().get(pk=maintenance.equipment_id)

    if data.return_movement is not None:
        _validate_return_movement(movement=data.return_movement, equipment=equipment)
        maintenance.return_movement = data.return_movement

    if data.condition_after:
        if data.condition_after not in Condition.values:
            raise ValueError(f"Condição inválida: {data.condition_after!r}.")
        if data.condition_after != equipment.condition:
            change_condition(
                equipment=equipment,
                new_condition=data.condition_after,
                reason=f"Registrado ao concluir manutenção #{maintenance.pk}.",
                changed_by=data.closed_by,
            )

    _restore_status_if_owned(maintenance=maintenance, equipment=equipment, changed_by=data.closed_by, event_label="concluída")

    maintenance.status = MaintenanceStatus.CONCLUIDA
    maintenance.service_performed = data.service_performed
    maintenance.condition_after = data.condition_after
    maintenance.closed_at = timezone.now()
    maintenance._change_reason = "Manutenção concluída."
    maintenance.save()
    return maintenance


@transaction.atomic
def cancel_maintenance(*, maintenance: Maintenance, cancelled_by: User, reason: str = "") -> Maintenance:
    """Único caminho suportado para cancelar uma `Maintenance` ABERTA (aberta por engano etc). Ver Matriz 1, linha E."""
    maintenance = Maintenance.objects.select_for_update().get(pk=maintenance.pk)
    if maintenance.status != MaintenanceStatus.ABERTA:
        raise ValueError("Só é possível cancelar uma manutenção que esteja aberta.")

    equipment = Equipment.objects.select_for_update().get(pk=maintenance.equipment_id)
    _restore_status_if_owned(maintenance=maintenance, equipment=equipment, changed_by=cancelled_by, event_label="cancelada")

    maintenance.status = MaintenanceStatus.CANCELADA
    maintenance.closed_at = timezone.now()
    if reason.strip():
        maintenance.notes = f"{maintenance.notes}\n\nCancelamento: {reason.strip()}".strip()
    maintenance._change_reason = "Manutenção cancelada."
    maintenance.save()
    return maintenance


# ---------------------------------------------------------------------------
# Cleaning — evento atômico (decisão 5), sem ciclo aberta/concluída.
# ---------------------------------------------------------------------------


@dataclass
class NewCleaningData:
    equipment_id: int
    responsible: User
    created_by: User
    performed_at: datetime | None = None
    notes: str = ""
    next_due_at: date | None = None
    movement: Movement | None = None


@transaction.atomic
def create_cleaning(data: NewCleaningData) -> Cleaning:
    """
    Único caminho suportado para registrar uma `Cleaning`. Evento
    imutável após criado (decisão 10) — nunca atualizado depois; um
    registro incorreto é corrigido com `cancel_cleaning()` (is_active =
    False) seguido de um novo registro correto.
    """
    equipment = Equipment.objects.get(pk=data.equipment_id)

    if data.movement is not None and data.movement.equipment_id != equipment.pk:
        raise ValueError("A movimentação informada não pertence a este equipamento.")

    return Cleaning.objects.create(
        equipment=equipment,
        performed_at=data.performed_at or timezone.now(),
        responsible=data.responsible,
        notes=data.notes,
        next_due_at=data.next_due_at,
        movement=data.movement,
        created_by=data.created_by,
    )


def cancel_cleaning(*, cleaning: Cleaning) -> Cleaning:
    """
    Única forma suportada de "desfazer" um registro de higienização —
    nunca edição direta dos campos do evento em si (decisão 10: "evitando
    UPDATE silencioso após registrado"). Só alterna `is_active`.
    """
    if not cleaning.is_active:
        raise ValueError("Este registro de higienização já está cancelado.")
    cleaning.is_active = False
    cleaning.save(update_fields=["is_active", "updated_at"])
    return cleaning
