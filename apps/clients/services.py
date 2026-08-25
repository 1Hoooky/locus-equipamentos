"""
Services de cliente — Fase 2 (Operação, arquitetura v1.0 seção 3 + delta
v1.1 seção 1/6). Único caminho suportado para criar ou editar um `Client`
— nunca `Client.objects.create()`/instância editada diretamente em
view/form ou em uma futura importação em lote, mesma disciplina já
aplicada em `apps.equipment.services` desde a Fase 1.

`Client.document` é editável depois da criação (decisão v1.0 seção 15.5,
confirmada na v1.1): tanto `create_client()` quanto `update_client()`
reaproveitam a MESMA validação (`apps.clients.validators`) e a mesma
checagem de duplicidade — nenhuma regra duplicada entre os dois caminhos.
"""

from dataclasses import dataclass

from django.db import transaction

from apps.clients.models import Client
from apps.clients.validators import validate_document_for_type
from apps.core.services import AddressData, create_address, update_address


def _validate_document_unique(normalized_document: str, *, exclude_pk: int | None = None) -> None:
    if not normalized_document:
        return
    queryset = Client.objects.filter(document=normalized_document)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    if queryset.exists():
        raise ValueError(f"Já existe um cliente cadastrado com o documento {normalized_document}.")


@dataclass
class NewClientData:
    client_type: str
    company_name: str
    document: str = ""
    trade_name: str = ""
    registration_status: str = ""
    state_registration: str = ""
    phone: str = ""
    email: str = ""
    contact_name: str = ""
    notes: str = ""
    fiscal_address: AddressData | None = None
    # "Endereço de entrega"/unidade inicial do cadastro simples (v1.0,
    # seção 3) — opcional. Quando informado, cria a primeira `Location`
    # (type=CLIENTE) do cliente na MESMA transação.
    initial_location_name: str = ""
    initial_location_address: AddressData | None = None
    change_reason: str = "Cadastro inicial."


@transaction.atomic
def create_client(data: NewClientData) -> Client:
    """
    Cria um `Client`: normaliza e valida o documento, checa duplicidade,
    cria `fiscal_address` (se informado) e, opcionalmente, a unidade
    inicial — tudo na mesma transação atômica (rollback total em caso de
    falha em qualquer etapa).
    """
    if not data.company_name.strip():
        raise ValueError("Razão social é obrigatória.")

    normalized_document = validate_document_for_type(data.document, data.client_type)
    _validate_document_unique(normalized_document)

    fiscal_address = create_address(data.fiscal_address)

    client = Client(
        client_type=data.client_type,
        document=normalized_document,
        company_name=data.company_name,
        trade_name=data.trade_name,
        registration_status=data.registration_status,
        state_registration=data.state_registration,
        phone=data.phone,
        email=data.email,
        contact_name=data.contact_name,
        notes=data.notes,
        fiscal_address=fiscal_address,
    )
    client._change_reason = data.change_reason  # consumido pelo django-simple-history
    client.save()

    if data.initial_location_name.strip():
        # Reaproveita o service de Location — create_client() nunca cria
        # Location direto; apps.operations.services é o único caminho
        # suportado para isso (mesma disciplina de "nunca criar caminho
        # paralelo" pedida na implementação).
        from apps.operations.models import LocationType
        from apps.operations.services import NewLocationData, create_location

        create_location(
            NewLocationData(
                name=data.initial_location_name,
                type=LocationType.CLIENTE,
                client=client,
                address=data.initial_location_address,
                change_reason="Unidade inicial criada junto com o cadastro do cliente.",
            )
        )

    return client


@dataclass
class ClientUpdateData:
    client_type: str
    company_name: str
    document: str = ""
    trade_name: str = ""
    registration_status: str = ""
    state_registration: str = ""
    phone: str = ""
    email: str = ""
    contact_name: str = ""
    notes: str = ""
    change_reason: str = "Edição de cadastro."


@transaction.atomic
def update_client(*, client: Client, data: ClientUpdateData) -> Client:
    """
    Edita um `Client` já existente, incluindo `document` (permitido desde
    a v1.1 — CNPJ pode ter sido digitado errado, diferente de `patrimonio`
    de equipamento, que é imutável por design). Não mexe em
    `fiscal_address`: editar o endereço é `apps.core.services.update_address()`
    diretamente sobre o `Address` já vinculado — trocar de `Address` inteiro
    não é uma operação suportada aqui.
    """
    if not data.company_name.strip():
        raise ValueError("Razão social é obrigatória.")

    normalized_document = validate_document_for_type(data.document, data.client_type)
    _validate_document_unique(normalized_document, exclude_pk=client.pk)

    client._change_reason = data.change_reason
    client.client_type = data.client_type
    client.document = normalized_document
    client.company_name = data.company_name
    client.trade_name = data.trade_name
    client.registration_status = data.registration_status
    client.state_registration = data.state_registration
    client.phone = data.phone
    client.email = data.email
    client.contact_name = data.contact_name
    client.notes = data.notes
    client.save()
    return client


@transaction.atomic
def update_fiscal_address(*, client: Client, data: AddressData, change_reason: str = "Edição de endereço fiscal.") -> Client:
    """
    Cria (se o cliente ainda não tiver um) ou edita in-place o
    `fiscal_address` do cliente — nunca troca a FK por um `Address`
    diferente depois de já existir um (edição é sempre no mesmo registro,
    v1.1 delta seção 5).
    """
    if client.fiscal_address_id is None:
        client._change_reason = "Endereço fiscal cadastrado."
        client.fiscal_address = create_address(data)
        client.save(update_fields=["fiscal_address"])
    else:
        update_address(address=client.fiscal_address, data=data, change_reason=change_reason)
    return client
