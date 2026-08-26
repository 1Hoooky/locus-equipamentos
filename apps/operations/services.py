"""
Services de operação — Fase 2 (arquitetura v1.0 seção 8/9 + delta v1.1
seções 6-10, e a regra adicional de compatibilidade destino×tipo de
movimentação, autorizada junto com o início da implementação). Único
caminho suportado para criar/editar `Location` e para criar `Movement` —
nunca `Location.objects.create()`/`Movement.objects.create()` direto em
view/form, nem qualquer caminho paralelo que altere
`Equipment.current_location`/`current_client` fora de `create_movement()`.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Count

from apps.accounts.models import User
from apps.clients.models import Client
from apps.core.services import AddressData, create_address, update_address
from apps.equipment.models import Equipment, Status
from apps.equipment.services import change_status
from apps.operations.models import Location, LocationType, Movement, MovementType

# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


@dataclass
class NewLocationData:
    name: str
    type: str
    client: Client | None = None
    address: AddressData | None = None
    change_reason: str = "Cadastro de unidade/localização."


def _validate_location_client_matches_type(*, type_: str, client: Client | None) -> None:
    # Mesma regra da CheckConstraint `location_client_matches_type`
    # (apps.operations.models) — repetida aqui para rejeitar ANTES de
    # qualquer escrita, com uma mensagem clara, em vez de depender só do
    # IntegrityError do banco (dupla camada, mesmo padrão já usado em
    # change_status()/change_condition()).
    if type_ == LocationType.CLIENTE and client is None:
        raise ValueError("Localização do tipo Cliente exige um cliente vinculado.")
    if type_ != LocationType.CLIENTE and client is not None:
        raise ValueError("Só localizações do tipo Cliente podem ter um cliente vinculado.")


@transaction.atomic
def create_location(data: NewLocationData) -> Location:
    """
    Cria uma `Location` — usada tanto para a unidade inicial de um cliente
    (chamada por `apps.clients.services.create_client()`) quanto para
    unidades adicionais/estoque/manutenção cadastradas depois.
    """
    if not data.name.strip():
        raise ValueError("Nome da localização é obrigatório.")
    if data.type not in LocationType.values:
        raise ValueError(f"Tipo de localização inválido: {data.type!r}.")
    _validate_location_client_matches_type(type_=data.type, client=data.client)

    address = create_address(data.address)

    location = Location(
        name=data.name,
        type=data.type,
        client=data.client,
        address=address,
    )
    location._change_reason = data.change_reason  # consumido pelo django-simple-history
    location.save()
    return location


@dataclass
class LocationUpdateData:
    name: str
    type: str
    client: Client | None = None
    change_reason: str = "Edição de unidade/localização."


@transaction.atomic
def update_location(*, location: Location, data: LocationUpdateData) -> Location:
    """
    Edita nome/tipo/cliente de uma `Location` já existente. Não mexe em
    `address`: editar o endereço operacional é
    `apps.core.services.update_address()` diretamente sobre o `Address` já
    vinculado (mesmo raciocínio de `apps.clients.services.update_client()`
    para o endereço fiscal).
    """
    if not data.name.strip():
        raise ValueError("Nome da localização é obrigatório.")
    if data.type not in LocationType.values:
        raise ValueError(f"Tipo de localização inválido: {data.type!r}.")
    _validate_location_client_matches_type(type_=data.type, client=data.client)

    location._change_reason = data.change_reason
    location.name = data.name
    location.type = data.type
    location.client = data.client
    location.save()
    return location


@transaction.atomic
def update_location_address(
    *, location: Location, data: AddressData, change_reason: str = "Edição de endereço operacional."
) -> Location:
    """Cria (se ainda não houver) ou edita in-place o `address` operacional da unidade — mesmo raciocínio de `apps.clients.services.update_fiscal_address()`."""
    if location.address_id is None:
        location._change_reason = "Endereço operacional cadastrado."
        location.address = create_address(data)
        location.save(update_fields=["address"])
    else:
        update_address(address=location.address, data=data, change_reason=change_reason)
    return location


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TransitionRule:
    required_statuses: tuple[str, ...]
    new_status: str | None  # None = a movimentação não altera o status


# Regras finais status × movimentação (delta v1.1, seção 10). OUTRO
# deliberadamente fora deste dicionário: não tem exigência de status nem
# efeito de status — é só um evento anotado na timeline (ver
# _validate_transition() e o pseudofluxo abaixo).
_TRANSITION_RULES: dict[str, _TransitionRule] = {
    MovementType.INSTALACAO: _TransitionRule(required_statuses=(Status.DISPONIVEL,), new_status=Status.EM_OPERACAO),
    MovementType.RETIRADA: _TransitionRule(required_statuses=(Status.EM_OPERACAO,), new_status=Status.DISPONIVEL),
    MovementType.TRANSFERENCIA: _TransitionRule(required_statuses=(Status.EM_OPERACAO,), new_status=None),
    MovementType.RETORNO_ESTOQUE: _TransitionRule(
        required_statuses=(Status.EM_OPERACAO, Status.MANUTENCAO), new_status=Status.DISPONIVEL
    ),
    MovementType.ENVIO_MANUTENCAO: _TransitionRule(
        required_statuses=(Status.DISPONIVEL, Status.EM_OPERACAO), new_status=Status.MANUTENCAO
    ),
    MovementType.RETORNO_MANUTENCAO: _TransitionRule(
        required_statuses=(Status.MANUTENCAO,), new_status=Status.DISPONIVEL
    ),
}

# Regra explícita acrescentada pelo usuário na autorização de implementação
# desta etapa: o TIPO da Location de destino tem que ser compatível com o
# tipo de movimentação — rejeitado pelo backend antes de qualquer escrita.
# Qualquer combinação fora deste dicionário (só MovementType.OUTRO) não tem
# exigência de tipo de destino.
_REQUIRED_DESTINATION_TYPE: dict[str, str] = {
    MovementType.INSTALACAO: LocationType.CLIENTE,
    MovementType.RETIRADA: LocationType.ESTOQUE,
    MovementType.RETORNO_ESTOQUE: LocationType.ESTOQUE,
    MovementType.ENVIO_MANUTENCAO: LocationType.MANUTENCAO,
    MovementType.RETORNO_MANUTENCAO: LocationType.ESTOQUE,
    MovementType.TRANSFERENCIA: LocationType.CLIENTE,
}


def _validate_transition(*, equipment: Equipment, movement_type: str, destination_location: Location | None) -> str | None:
    """
    Valida a transição pedida contra o estado JÁ BLOQUEADO de `equipment`
    (`select_for_update()`, feito pelo chamador antes desta função).
    Levanta `ValueError` com mensagem clara se a transição não for
    permitida; retorna o novo status (ou `None`, se a movimentação não
    altera o status) quando a transição é válida. Nenhuma escrita
    acontece aqui — só leitura e validação.
    """
    if movement_type not in MovementType.values:
        raise ValueError(f"Tipo de movimentação inválido: {movement_type!r}.")

    if movement_type == MovementType.OUTRO:
        # Sem exigência de status, sem efeito de status, sem exigência de
        # tipo de destino — evento apenas anotado na timeline (motivo
        # obrigatório, checado à parte). Não faz parte de nenhum fluxo de
        # tela autorizado nesta etapa (instalação/retirada/transferência/
        # manutenção); existe só porque o enum já previa o valor.
        return None

    rule = _TRANSITION_RULES[movement_type]
    if equipment.status not in rule.required_statuses:
        raise ValueError(
            f"Não é possível registrar '{MovementType(movement_type).label}' para um equipamento com status "
            f"'{equipment.get_status_display()}'. Status exigido: "
            f"{', '.join(Status(s).label for s in rule.required_statuses)}."
        )

    required_destination_type = _REQUIRED_DESTINATION_TYPE[movement_type]
    if destination_location is None:
        raise ValueError(f"'{MovementType(movement_type).label}' exige uma localização de destino.")
    if destination_location.type != required_destination_type:
        raise ValueError(
            f"'{MovementType(movement_type).label}' exige um destino do tipo "
            f"'{LocationType(required_destination_type).label}' — "
            f"'{destination_location.name}' é do tipo '{destination_location.get_type_display()}'."
        )

    # Bug relatado: era possível registrar uma "Transferência" de uma
    # unidade para ELA MESMA — não é uma movimentação real. Só faz
    # sentido para TRANSFERENCIA (as demais movimentações não têm
    # `current_location` como candidato de destino: instalação/retirada
    # exigem tipos incompatíveis com a origem, e retorno de
    # estoque/manutenção já mudam de tipo por definição).
    if movement_type == MovementType.TRANSFERENCIA and destination_location.pk == equipment.current_location_id:
        raise ValueError("O equipamento já está nesta unidade.")

    return rule.new_status


def _client_display_name(client: Client | None) -> str:
    return client.display_name() if client else ""


@dataclass
class NewMovementData:
    equipment_id: int
    movement_type: str
    created_by: User
    destination_location: Location | None = None
    reason: str = ""


@transaction.atomic
def create_movement(data: NewMovementData) -> Movement:
    """
    Único caminho suportado para registrar uma movimentação operacional —
    instalação, retirada, transferência, retorno ao estoque, envio/retorno
    de manutenção. Nunca `Movement.objects.create()` direto, nunca edição
    direta de `Equipment.current_location`/`current_client` fora daqui
    (delta v1.1, seção 7/8/9).
    """
    equipment = Equipment.objects.select_for_update().get(pk=data.equipment_id)

    # Origem NUNCA vem do chamador — sempre o estado já bloqueado (delta
    # v1.1, seção 6, item 4): elimina por construção a possibilidade de
    # origem divergente do estado real no momento da transação.
    origin_location = equipment.current_location

    new_status = _validate_transition(
        equipment=equipment,
        movement_type=data.movement_type,
        destination_location=data.destination_location,
    )

    if data.movement_type == MovementType.OUTRO and not data.reason.strip():
        raise ValueError("Movimentação do tipo 'Outro' exige motivo/observação.")

    movement = Movement.objects.create(
        equipment=equipment,
        movement_type=data.movement_type,
        origin_location=origin_location,
        destination_location=data.destination_location,
        origin_location_name=origin_location.name if origin_location else "",
        destination_location_name=data.destination_location.name if data.destination_location else "",
        origin_client_name=_client_display_name(origin_location.client) if origin_location else "",
        destination_client_name=_client_display_name(data.destination_location.client)
        if data.destination_location
        else "",
        reason=data.reason,
        created_by=data.created_by,
    )

    if new_status is not None and new_status != equipment.status:
        # Reaproveita change_status() já existente — não duplica a
        # gravação de StatusHistory.
        change_status(
            equipment=equipment,
            new_status=new_status,
            reason=f"Alterado automaticamente por movimentação: {movement.get_movement_type_display()}.",
            changed_by=data.created_by,
        )

    # current_location/current_client sempre escritos juntos, no mesmo
    # save() — nenhuma janela onde um reflete o movimento e o outro não
    # (delta v1.1, seção 7). Para os seis tipos com tela autorizada nesta
    # etapa, `_validate_transition()` já garante `destination_location`
    # não-nulo, então `destination` é sempre o destino informado. Só
    # `MovementType.OUTRO` pode chegar aqui sem destino (não tem tela
    # nesta etapa; existe só porque o enum já previa o valor) — decisão
    # tomada durante a implementação: sem destino informado, OUTRO é
    # tratado como evento apenas anotado, e current_location/current_client
    # permanecem inalterados (mantém o valor já bloqueado), em vez de
    # zerá-los por ausência de destino.
    destination = data.destination_location if data.destination_location is not None else origin_location
    equipment.current_location = destination
    equipment.current_client = destination.client if destination else None
    equipment.save(update_fields=["current_location", "current_client", "updated_at"])

    return movement


# ---------------------------------------------------------------------------
# Diagnóstico — Locations duplicadas (ferramenta TEMPORÁRIA: management
# command `report_duplicate_locations` e a tela somente-leitura
# `apps.operations.views.DuplicateLocationsReportView`, ambos criados para
# investigar/limpar as unidades repetidas deixadas pelos testes manuais de
# double-submit no Render Free — sem acesso a Shell lá, a tela é o único
# jeito de rodar esta consulta em produção). ÚNICA fonte da regra de
# "duplicata": os dois chamadores reaproveitam esta função — nunca uma
# cópia divergente. Não apaga, não edita, não consolida nada; é só leitura.
# ---------------------------------------------------------------------------


@dataclass
class DuplicateLocationEntry:
    location: Location
    movements_as_origin: int
    movements_as_destination: int

    @property
    def has_references(self) -> bool:
        return bool(self.movements_as_origin or self.movements_as_destination)


@dataclass
class DuplicateLocationGroup:
    name: str
    type: str
    client: Client | None
    owner_label: str
    entries: list["DuplicateLocationEntry"] = field(default_factory=list)


def find_duplicate_location_groups() -> list[DuplicateLocationGroup]:
    """
    "Duplicata" = mesmo (name, type, client) com mais de uma `Location`
    ATIVA. Unidades homônimas de clientes DIFERENTES são legítimas por
    decisão de projeto (sem UNIQUE(name)) e não entram no resultado.

    Para cada `Location` do grupo, conta quantos `Movement` a referenciam
    como origem e como destino — quem chama decide como exibir/rotular
    "SEM REFERÊNCIAS"/"COM REFERÊNCIAS" (`DuplicateLocationEntry.has_references`).
    """
    raw_groups = (
        Location.objects.filter(is_active=True)
        .values("name", "type", "client")
        .annotate(quantidade=Count("id"))
        .filter(quantidade__gt=1)
        .order_by("name")
    )

    groups: list[DuplicateLocationGroup] = []
    for raw in raw_groups:
        locations = (
            Location.objects.filter(is_active=True, name=raw["name"], type=raw["type"], client_id=raw["client"])
            .select_related("client")
            .order_by("pk")
        )
        first = locations.first()
        owner_label = first.client.display_name() if first.client_id else "(interna, sem cliente)"
        entries = [
            DuplicateLocationEntry(
                location=location,
                movements_as_origin=Movement.objects.filter(origin_location=location).count(),
                movements_as_destination=Movement.objects.filter(destination_location=location).count(),
            )
            for location in locations
        ]
        groups.append(
            DuplicateLocationGroup(
                name=raw["name"],
                type=raw["type"],
                client=first.client,
                owner_label=owner_label,
                entries=entries,
            )
        )
    return groups


# ---------------------------------------------------------------------------
# Limpeza de Locations duplicadas SEM referências — ferramenta TEMPORÁRIA,
# continuação direta do relatório de diagnóstico acima. Depois de olhar o
# relatório manualmente, o usuário identificou que só os grupos "TESTE",
# "TESTE3" e "teste2" são dados de teste (não decisão automática) e que, de
# tudo isso, só a Location #2 "TESTE" tem Movement referenciando — por
# isso o escopo é restrito a esses três nomes de grupo, nunca "qualquer
# duplicata sem referência" (o que arrastaria dados legítimos de outros
# clientes/futuros grupos).
#
# "Apagar" aqui segue a MESMA convenção do resto do projeto — SoftDeleteModel
# (`is_active=False`), nunca `DELETE` físico: preserva o histórico
# (`HistoricalRecords`), não deixa `Address`/`Client` referenciando uma FK
# apagada, e é reversível manualmente (reativar a linha) se necessário.
# ---------------------------------------------------------------------------

# Únicos nomes de grupo elegíveis — ampliar esta lista é uma decisão
# humana deliberada (editar o código), nunca inferida automaticamente a
# partir do relatório.
DUPLICATE_CLEANUP_TARGET_GROUP_NAMES = ("TESTE", "TESTE3", "teste2")

# Segunda camada de proteção, redundante com o allowlist acima só por
# segurança: mesmo que um desses nomes de grupo algum dia colida com uma
# Location interna de verdade, ela nunca é candidata a remoção.
_DUPLICATE_CLEANUP_PROTECTED_NAMES = ("Estoque Locus", "Manutenção Locus")


@dataclass
class DuplicateLocationCleanupCandidate:
    location: Location
    group_name: str


@dataclass
class DuplicateLocationCleanupPlan:
    """
    O que a limpeza REMOVERIA se executada agora — calculado sem apagar
    nada. Usado tanto pela tela de confirmação (mostra os IDs exatos antes
    de qualquer escrita) quanto, revalidado individualmente linha a linha,
    pela execução de fato (`execute_duplicate_location_cleanup`).
    """

    to_remove: list[DuplicateLocationCleanupCandidate]
    preserved_with_references: list[DuplicateLocationCleanupCandidate]


def plan_duplicate_location_cleanup() -> DuplicateLocationCleanupPlan:
    """
    Restrita aos grupos de duplicatas cujo nome está em
    `DUPLICATE_CLEANUP_TARGET_GROUP_NAMES` — os únicos identificados pelo
    usuário como dados de teste. Dentro desses grupos: Location sem
    NENHUM Movement referenciando (origem OU destino) → candidata a
    remoção; com referência (ex.: #2 "TESTE") → preservada, nunca
    candidata.
    """
    to_remove: list[DuplicateLocationCleanupCandidate] = []
    preserved: list[DuplicateLocationCleanupCandidate] = []

    for group in find_duplicate_location_groups():
        if group.name not in DUPLICATE_CLEANUP_TARGET_GROUP_NAMES:
            continue
        for entry in group.entries:
            if entry.location.name in _DUPLICATE_CLEANUP_PROTECTED_NAMES:
                continue
            candidate = DuplicateLocationCleanupCandidate(location=entry.location, group_name=group.name)
            if entry.has_references:
                preserved.append(candidate)
            else:
                to_remove.append(candidate)

    return DuplicateLocationCleanupPlan(to_remove=to_remove, preserved_with_references=preserved)


@dataclass
class DuplicateLocationCleanupReport:
    removed: list[Location]
    preserved_with_references: list[Location]
    skipped_race: list[Location]


@transaction.atomic
def execute_duplicate_location_cleanup(*, performed_by: User) -> DuplicateLocationCleanupReport:
    """
    Execução de fato da limpeza — só chamada depois da tela de
    confirmação ter mostrado os IDs exatos ao Administrador. Tudo dentro
    de UMA transação: se qualquer erro inesperado ocorrer no meio do
    laço, o Django reverte a transação inteira — nenhuma remoção parcial
    fica gravada (ver `test_rollback_...` em
    `apps.operations.tests.test_duplicate_locations_cleanup`).

    Revalidação individual, imediatamente antes de CADA remoção: nunca
    reaproveita a contagem já calculada em `plan_duplicate_location_cleanup()`
    — o plano pode estar desatualizado (uma Movement pode ter sido
    registrada para uma dessas Locations entre a tela de confirmação e o
    clique em confirmar). Uma Location que virou "com referência" nesse
    intervalo é pulada e registrada no relatório, nunca apagada. Sem bulk
    delete: cada linha é revalidada e desativada individualmente, uma de
    cada vez, nunca um `.update()`/`.delete()` em massa.
    """
    plan = plan_duplicate_location_cleanup()

    removed: list[Location] = []
    skipped_race: list[Location] = []

    for candidate in plan.to_remove:
        location = candidate.location

        # Revalida do zero, contra o banco, não contra o snapshot do plano.
        if not Location.objects.filter(pk=location.pk, is_active=True).exists():
            continue  # já desativada (ex.: outra execução concorrente) — nada a fazer

        origin_count = Movement.objects.filter(origin_location_id=location.pk).count()
        destination_count = Movement.objects.filter(destination_location_id=location.pk).count()
        if origin_count != 0 or destination_count != 0:
            skipped_race.append(location)
            continue

        location._change_reason = (
            f"Limpeza de duplicata de teste (grupo {candidate.group_name!r}), sem Movement referenciando. "
            f"Executada por {performed_by}."
        )
        location.is_active = False
        location.save(update_fields=["is_active", "updated_at"])
        removed.append(location)

    return DuplicateLocationCleanupReport(
        removed=removed,
        preserved_with_references=[c.location for c in plan.preserved_with_references],
        skipped_race=skipped_race,
    )
