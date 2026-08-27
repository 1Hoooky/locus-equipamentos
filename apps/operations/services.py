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
from django.db.models import Count, Q

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

    Causa raiz de um 502 em produção (Render + Neon/Postgres remoto): a
    versão anterior desta função fazia, por Location, duas queries
    `Movement.objects.filter(...).count()` dentro de um loop — um N+1
    clássico. Com latência de rede real até o banco (Neon não é
    localhost), cada round-trip soma, e o worker do Gunicorn estourava o
    timeout preso em consultas SQL sequenciais (não OOM — o traceback
    mostrava o worker bloqueado em SQL, o "Perhaps out of memory" do
    Gunicorn é só a mensagem genérica do SIGKILL por timeout, não um
    diagnóstico de memória confirmado).

    Reescrita para NÚMERO DE QUERIES CONSTANTE — sempre exatamente 2,
    não importa quantos grupos ou quantas Locations existam:

      1. A agregação `GROUP BY (name, type, client) HAVING count > 1` de
         sempre (já era 1 query só).
      2. UMA ÚNICA query trazendo TODAS as Locations membras de QUALQUER
         grupo duplicado de uma vez, com as contagens de `Movement` como
         origem/destino calculadas via `annotate(Count(..., distinct=True))`
         — agregação no próprio banco, não em Python, e sem carregar
         nenhum `Movement` inteiro em memória (só os `COUNT()` agregados
         voltam). `distinct=True` em CADA `Count` evita o "fan-out"
         clássico de combinar duas relações reversas (`movements_from`/
         `movements_to`) na mesma query (o JOIN duplo multiplicaria as
         linhas sem isso — padrão documentado do próprio Django para
         "Combining multiple aggregations").

    O agrupamento em `DuplicateLocationGroup`/ordenação dentro de cada
    grupo continuam EXATAMENTE como antes — só a forma de buscar os dados
    mudou, o resultado e o formato são idênticos.
    """
    raw_groups = list(
        Location.objects.filter(is_active=True)
        .values("name", "type", "client")
        .annotate(quantidade=Count("id"))
        .filter(quantidade__gt=1)
        .order_by("name")
    )
    if not raw_groups:
        return []

    # OR de um Q por grupo — o universo é só "as Locations que pertencem
    # a algum dos grupos já identificados acima", nunca "todas as
    # Locations com um desses nomes" (dois clientes diferentes podem
    # compartilhar nome sem formar duplicata — cada Q trava name+type+client
    # juntos, exatamente a chave do grupo).
    group_filter = Q()
    for raw in raw_groups:
        group_filter |= Q(name=raw["name"], type=raw["type"], client_id=raw["client"])

    locations = (
        Location.objects.filter(is_active=True)
        .filter(group_filter)
        .select_related("client")
        .annotate(
            movements_as_origin=Count("movements_from", distinct=True),
            movements_as_destination=Count("movements_to", distinct=True),
        )
        .order_by("pk")
    )

    # Uma única passada em Python (sem query nenhuma) para reagrupar por
    # (name, type, client) — o `entries` de cada grupo sai na mesma ordem
    # de antes (pk crescente) porque `locations` já vem ordenada por pk.
    members_by_key: dict[tuple[str, str, int | None], list[Location]] = {}
    for location in locations:
        key = (location.name, location.type, location.client_id)
        members_by_key.setdefault(key, []).append(location)

    groups: list[DuplicateLocationGroup] = []
    for raw in raw_groups:
        key = (raw["name"], raw["type"], raw["client"])
        members = members_by_key.get(key, [])
        if not members:
            continue  # defensivo: não deveria acontecer (mesmo filtro dos dois lados)
        first = members[0]
        owner_label = first.client.display_name() if first.client_id else "(interna, sem cliente)"
        entries = [
            DuplicateLocationEntry(
                location=location,
                movements_as_origin=location.movements_as_origin,
                movements_as_destination=location.movements_as_destination,
            )
            for location in members
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
# Nota: a ferramenta de ESCRITA (limpeza via navegador, em lotes) que
# existiu temporariamente nesta seção foi REMOVIDA — a tela retornava 502
# Bad Gateway no Render Free mesmo processando em lotes pequenos, e como
# a limpeza dos grupos "TESTE"/"TESTE3"/"teste2" era um evento pontual
# (não uma operação recorrente que precise de UI), ela foi substituída
# pela data migration `apps.operations.migrations.0005_deactivate_test_duplicate_locations`,
# que roda uma única vez dentro do próprio `python manage.py migrate` do
# deploy — sem depender de HTTP/JavaScript/sessão/SubmissionGuard.
#
# `find_duplicate_location_groups()` (acima) continua existindo — é
# somente-leitura, usada pelo management command `report_duplicate_locations`
# e pela tela de diagnóstico (`apps.operations.views.DuplicateLocationsReportView`),
# ambos mantidos por serem úteis para detectar problemas parecidos no
# futuro. Nada mais deste arquivo é capaz de apagar/desativar uma
# Location — a única forma de "limpar" duplicatas de teste agora é
# escrever uma migration nova, deliberadamente, como a 0005.
# ---------------------------------------------------------------------------
