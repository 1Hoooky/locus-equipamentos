"""
Services genéricos de `Address` — Fase 2 (Operação, arquitetura v1.0, seção
6): endereço fiscal (`Client.fiscal_address`) e endereço operacional
(`Location.address`) usam o MESMO model `Address`, mas nunca a mesma linha
— cada um é criado/editado independentemente. Este módulo é o único lugar
que sabe criar ou editar um `Address`, reaproveitado tanto por
`apps.clients.services` quanto por `apps.operations.services`, para não
duplicar essa lógica em dois apps.
"""

from dataclasses import dataclass

from apps.core.models import Address, CompanyProfile


@dataclass
class AddressData:
    cep: str = ""
    logradouro: str = ""
    numero: str = ""
    complemento: str = ""
    bairro: str = ""
    cidade: str = ""
    uf: str = ""
    reference_notes: str = ""

    def is_blank(self) -> bool:
        return not any(
            [self.cep, self.logradouro, self.numero, self.complemento, self.bairro, self.cidade, self.uf]
        )


def create_address(data: AddressData | None) -> Address | None:
    """
    Cria um novo `Address` a partir de `data`, ou retorna `None` se `data`
    for `None`/completamente vazio (endereço é opcional em ambos os usos —
    fiscal e operacional). Nunca reaproveita uma linha já existente: cada
    chamada cria uma linha nova e independente, mesmo que os valores sejam
    idênticos a um `Address` já usado em outro lugar (v1.0, seção 6 —
    "usar endereço fiscal como endereço de entrega" cria DOIS registros
    distintos, nunca uma FK compartilhada).
    """
    if data is None or data.is_blank():
        return None
    return Address.objects.create(
        cep=data.cep,
        logradouro=data.logradouro,
        numero=data.numero,
        complemento=data.complemento,
        bairro=data.bairro,
        cidade=data.cidade,
        uf=data.uf,
        reference_notes=data.reference_notes,
    )


def update_address(*, address: Address, data: AddressData, change_reason: str = "Edição de endereço.") -> Address:
    """
    Edita um `Address` já existente in-place — nunca exclui e recria
    (v1.1 delta, seção 5: `on_delete=PROTECT` conta com edição normal
    continuar sendo `address.campo = valor; address.save()`).
    """
    address._change_reason = change_reason  # consumido pelo django-simple-history
    address.cep = data.cep
    address.logradouro = data.logradouro
    address.numero = data.numero
    address.complemento = data.complemento
    address.bairro = data.bairro
    address.cidade = data.cidade
    address.uf = data.uf
    address.reference_notes = data.reference_notes
    address.save()
    return address


# ---------------------------------------------------------------------------
# CompanyProfile — singleton "dados da Locus" (ver apps.core.models).
# ---------------------------------------------------------------------------


def get_company_profile() -> CompanyProfile:
    """
    Único acessor suportado — `get_or_create(pk=1)` (nunca
    `CompanyProfile.objects.create()` solto em view/service): garante que
    sempre existe exatamente uma linha, mesmo antes de qualquer
    Administrador ter preenchido os dados (a tela de edição usa este
    mesmo acessor, então o formulário sempre tem uma instância para
    editar in-place, nunca "criar a primeira vez").
    """
    profile, _ = CompanyProfile.objects.get_or_create(pk=1)
    return profile


@dataclass
class CompanyProfileData:
    company_name: str = ""
    cnpj: str = ""
    logradouro: str = ""
    numero: str = ""
    bairro: str = ""
    cidade: str = ""
    uf: str = ""
    cep: str = ""
    phone: str = ""
    mobile_phone: str = ""
    email: str = ""


def update_company_profile(data: CompanyProfileData) -> CompanyProfile:
    """Edição in-place do singleton — nunca cria uma segunda linha."""
    profile = get_company_profile()
    profile.company_name = data.company_name
    profile.cnpj = data.cnpj
    profile.logradouro = data.logradouro
    profile.numero = data.numero
    profile.bairro = data.bairro
    profile.cidade = data.cidade
    profile.uf = data.uf
    profile.cep = data.cep
    profile.phone = data.phone
    profile.mobile_phone = data.mobile_phone
    profile.email = data.email
    profile.save()
    return profile
