"""
Contrato do "acelerador de cadastro" por CNPJ — arquitetura aprovada
(v1.0, seção 4). Views/forms conhecem só o que está aqui; nenhum detalhe
de fornecedor específico (BrasilAPI ou outro) escapa deste pacote.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class CompanyLookupError(Exception):
    """Classe-base — nunca levantada diretamente, só as duas subclasses abaixo."""


class CompanyLookupUnavailable(CompanyLookupError):
    """Timeout, erro de rede, HTTP não-2xx (exceto 404), resposta malformada — qualquer falha do provider."""


class CompanyLookupNotFound(CompanyLookupError):
    """O provider respondeu normalmente, mas não tem esse CNPJ na base (ex.: HTTP 404 da BrasilAPI)."""


@dataclass
class CompanyLookupResult:
    """
    Dados que QUALQUER provider pode devolver — todos opcionais, porque
    nenhum provider garante preencher tudo. Endereço fiscal vem como
    valores soltos (não um `Address` já persistido): a arquitetura exige
    que o usuário revise antes de salvar (v1.0, seção 2), então nunca
    criamos um `Address` a partir de um resultado de consulta sem
    confirmação explícita.
    """

    cnpj: str
    company_name: str = ""
    trade_name: str = ""
    registration_status: str = ""
    phone: str = ""
    email: str = ""
    address_cep: str = ""
    address_logradouro: str = ""
    address_numero: str = ""
    address_complemento: str = ""
    address_bairro: str = ""
    address_cidade: str = ""
    address_uf: str = ""


class CompanyLookupProvider(ABC):
    """
    Interface que qualquer fornecedor de consulta de CNPJ implementa.
    Trocar BrasilAPI por outro provider no futuro = escrever uma nova
    classe com este único método — nada mais muda (v1.0, seção 2).
    """

    @abstractmethod
    def lookup(self, cnpj: str) -> CompanyLookupResult:
        """
        `cnpj` já chega normalizado (só dígitos, 14 caracteres) —
        `CompanyLookupService` garante isso antes de chamar o provider.
        Deve levantar `CompanyLookupNotFound` ou `CompanyLookupUnavailable`
        em caso de falha; nunca deixar uma exceção de biblioteca HTTP
        escapar deste método.
        """
        raise NotImplementedError
