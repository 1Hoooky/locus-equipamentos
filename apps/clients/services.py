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
from django.db.models import ProtectedError

from apps.clients.models import Client
from apps.clients.validators import validate_document_for_type
from apps.core.hard_delete import (
    HardDeleteAuthorizationError,
    HardDeleteBlocked,
    HardDeleteImpact,
    describe_protected_error,
)
from apps.core.services import AddressData, create_address, update_address


def _validate_document_unique(normalized_document: str, *, exclude_pk: int | None = None) -> None:
    if not normalized_document:
        return
    queryset = Client.objects.filter(document=normalized_document)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    if queryset.exists():
        raise ValueError(f"Já existe um cliente cadastrado com o documento {normalized_document}.")


def _validate_auvo_code_unique(auvo_code: str, *, exclude_pk: int | None = None) -> None:
    if not auvo_code:
        return
    queryset = Client.objects.filter(auvo_code=auvo_code)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    if queryset.exists():
        raise ValueError(f"Já existe um cliente importado com o código Auvo {auvo_code}.")


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
    # Campos de importação Auvo — todos opcionais, string vazia em qualquer
    # fluxo que não seja a importação (ver apps.clients.import_auvo).
    auvo_code: str = ""
    external_code: str = ""
    municipal_registration: str = ""
    icms_taxpayer: str = ""
    billing_email: str = ""
    fiscal_address: AddressData | None = None
    # Nome da unidade inicial — OPCIONAL desde o 2º reteste manual: a
    # Location operacional principal é criada SEMPRE junto com o cliente
    # (na mesma transação), com este nome quando informado ou com
    # DEFAULT_INITIAL_LOCATION_NAME quando em branco. Motivo (relato do
    # usuário): cliente com um único endereço não pode ser obrigado a
    # cadastrar manualmente uma "unidade" com praticamente os mesmos dados
    # só para conseguir instalar um equipamento. A arquitetura
    # Client → Location → Equipment.current_location fica intacta — a
    # mudança é só QUANDO a Location principal nasce (sempre), não ONDE o
    # equipamento aponta.
    initial_location_name: str = ""
    initial_location_address: AddressData | None = None
    change_reason: str = "Cadastro inicial."


# Nome interno padronizado da Location principal criada automaticamente
# quando o usuário não dá um nome à unidade. Na tela de movimentação esse
# nome NÃO aparece para cliente de unidade única (exibe só o nome do
# cliente — ver apps.operations.forms._destination_label); ele só se torna
# visível quando o cliente ganha unidades adicionais e o sufixo passa a
# distinguir uma da outra.
DEFAULT_INITIAL_LOCATION_NAME = "Unidade principal"


@transaction.atomic
def create_client(data: NewClientData, *, require_document: bool = True) -> Client:
    """
    Cria um `Client`: normaliza e valida o documento, checa duplicidade,
    cria `fiscal_address` (se informado) e, opcionalmente, a unidade
    inicial — tudo na mesma transação atômica (rollback total em caso de
    falha em qualquer etapa).

    `require_document`: mantém, por padrão (`True`), a regra de negócio já
    em vigor — CNPJ/CPF obrigatório para cadastro manual (decisão revista a
    pedido do usuário, ver comentário em `Client.document`). A única exceção
    suportada é a importação de clientes do Auvo
    (`apps.clients.import_auvo`/`views_import`), que passa
    `require_document=False` explicitamente porque a planilha real de
    origem tem clientes legítimos sem documento cadastrado — a exceção fica
    restrita a esse único caminho, sem afetar `ClientCreateView`/`ClientForm`
    nem qualquer outro chamador que não passe o argumento.
    """
    normalized_document = validate_document_for_type(data.document, data.client_type)
    # Decisão revista a pedido do usuário: o CNPJ/CPF (não a razão social)
    # é o campo obrigatório — o inverso do que valia antes. `company_name`
    # agora é opcional (ver `Client.company_name`/`display_name()`).
    if require_document and not normalized_document:
        raise ValueError("CNPJ é obrigatório.")
    _validate_document_unique(normalized_document)
    _validate_auvo_code_unique(data.auvo_code.strip())

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
        auvo_code=data.auvo_code.strip(),
        external_code=data.external_code.strip(),
        municipal_registration=data.municipal_registration.strip(),
        icms_taxpayer=data.icms_taxpayer.strip(),
        billing_email=data.billing_email.strip(),
        fiscal_address=fiscal_address,
    )
    client._change_reason = data.change_reason  # consumido pelo django-simple-history
    client.save()

    # A Location operacional principal é criada SEMPRE (2º reteste manual)
    # — antes disto, ela só nascia quando o usuário digitava um nome de
    # unidade (campo rotulado como opcional), então o fluxo normal
    # terminava sem NENHUMA Location e instalar um equipamento exigia uma
    # segunda ação manual em "Nova unidade". Reaproveita o service de
    # Location — create_client() nunca cria Location direto;
    # apps.operations.services é o único caminho suportado para isso.
    from apps.operations.models import LocationType
    from apps.operations.services import NewLocationData, create_location

    create_location(
        NewLocationData(
            name=data.initial_location_name.strip() or DEFAULT_INITIAL_LOCATION_NAME,
            type=LocationType.CLIENTE,
            client=client,
            address=data.initial_location_address,
            change_reason="Unidade principal criada automaticamente junto com o cadastro do cliente.",
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
    normalized_document = validate_document_for_type(data.document, data.client_type)
    if not normalized_document:
        raise ValueError("CNPJ é obrigatório.")
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


# ---------------------------------------------------------------------------
# Exclusão definitiva (hard delete) — rodada "AMBIENTE EM DESENVOLVIMENTO /
# HARD DELETE DURANTE DESENVOLVIMENTO", 11/09/2026. Ver docstring de
# `apps.core.hard_delete` para o raciocínio completo (por que
# `is_superuser`, por que não substitui o soft delete existente).
#
# Mapa de relações de `Client` (auditoria da rodada — CASCADE/PROTECT/
# SET_NULL):
#   DEPENDÊNCIA EXCLUSIVA (removida junto, nunca sem o Cliente):
#     - `fiscal_address` (`OneToOneField` para `Address`, hoje
#       `on_delete=PROTECT`): cada linha de `Address` apontada por
#       `fiscal_address` NUNCA é compartilhada com outro Cliente nem com
#       nenhuma `Location` (ver docstring de `apps.core.models.Address`
#       — "nunca a mesma linha compartilhada entre os dois") — é o
#       endereço fiscal DESTE cliente e de mais nenhum registro. O
#       `PROTECT` só protege a direção "excluir o Address enquanto o
#       Client existe" (nunca dispara ao excluir o próprio Client) —
#       por isso precisa de remoção EXPLÍCITA aqui, depois do Client já
#       ter sumido (só então o `PROTECT` do `Address` deixa de ter
#       qualquer referência viva).
#   REGISTROS COMPARTILHADOS (NUNCA excluídos/alterados por aqui — o
#   próprio schema já impede ou já cuida sozinho):
#     - `Equipment.current_client` (`SET_NULL`): o Django zera a
#       referência sozinho — o Equipamento em si NUNCA é tocado (pedido
#       explícito do usuário: "excluir um Cliente não deve excluir um
#       Equipamento simplesmente porque ele teve relação com aquele
#       cliente").
#     - `Location.client` (`PROTECT`): uma Location é um cadastro
#       próprio, com histórico operacional independente (Movements
#       apontam para ela) — NUNCA um dependente exclusivo do Cliente,
#       mesmo pertencendo a ele. Se o Cliente ainda tiver Location(s)
#       ativa(s), a exclusão é BLOQUEADA de propósito (não é um
#       "bloqueio excessivo": o Administrador precisa decidir o que
#       fazer com a(s) Location(s) primeiro — o impacto de apagá-las
#       junto não seria "conhecido e controlado" por definição, já que
#       Movements podem apontar para elas).
#     - `Opportunity.client` (`PROTECT`): mesmo raciocínio — excluir uma
#       Oportunidade nunca exclui o Cliente (pedido explícito do
#       usuário), e o inverso também não cascateia: um Cliente com
#       Oportunidades ainda vinculadas bloqueia a exclusão até o
#       Administrador decidir (ex.: `hard_delete_opportunity()` de cada
#       uma primeiro, se também forem dado de teste).
# ---------------------------------------------------------------------------


def preview_client_hard_delete(client: Client) -> HardDeleteImpact:
    """Não altera nada — só descreve o que `hard_delete_client()` removeria junto, para a tela de confirmação."""
    dependents = {}
    if client.fiscal_address_id is not None:
        dependents["endereço fiscal"] = 1
    return HardDeleteImpact(target_label=f'o cliente "{client.display_name()}"', dependents=dependents)


@transaction.atomic
def hard_delete_client(*, client_id: int, actor) -> HardDeleteImpact:
    """
    Único caminho suportado para excluir um `Client` de verdade (não
    `is_active=False`) — restrito à "autoridade máxima" (`actor.
    is_superuser`, checado aqui E na view — defesa em profundidade, ver
    `apps.core.hard_delete`). Levanta `HardDeleteBlocked` (nunca
    cascateia às cegas) se ainda houver Location/Oportunidade
    compartilhada vinculada.
    """
    if not getattr(actor, "is_superuser", False):
        raise HardDeleteAuthorizationError("Exclusão definitiva requer autoridade máxima (superusuário).")

    client = Client.objects.select_for_update().get(pk=client_id)
    label = f'o cliente "{client.display_name()}"'
    fiscal_address = client.fiscal_address
    dependents = {"endereço fiscal": 1} if fiscal_address is not None else {}

    try:
        client.delete()
    except ProtectedError as exc:
        raise HardDeleteBlocked(describe_protected_error(exc, subject=label)) from exc

    if fiscal_address is not None:
        # Só agora (Client já excluído) o `PROTECT` do Address deixa de
        # ter qualquer referência viva — ver comentário do mapa de
        # relações acima.
        fiscal_address.delete()

    # `django-simple-history` não cria uma FK "viva" (o `id` da linha
    # histórica é só uma cópia do pk original, sem constraint) — excluir
    # o Client não apaga essas linhas sozinho. Para uma exclusão
    # DEFINITIVA de verdade (dado de teste, sem valor de auditoria a
    # preservar), removemos também o snapshot histórico deste registro.
    Client.history.filter(id=client_id).delete()

    return HardDeleteImpact(target_label=label, dependents=dependents)
