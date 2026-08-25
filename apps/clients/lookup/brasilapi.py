"""
Provider concreto — BrasilAPI (v1.0, seção 4). Único lugar do projeto que
sabe o formato de resposta da BrasilAPI; qualquer mudança na API externa
fica isolada aqui.
"""

import httpx

from apps.clients.lookup.base import (
    CompanyLookupNotFound,
    CompanyLookupProvider,
    CompanyLookupResult,
    CompanyLookupUnavailable,
)

BRASILAPI_CNPJ_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"

# Timeouts curtos e sem retry, por design (v1.0, seção 4): uma consulta
# externa não pode travar o cadastro manual, que é sempre o fallback.
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 5.0


class BrasilAPICompanyLookupProvider(CompanyLookupProvider):
    """Consulta CNPJ na BrasilAPI (https://brasilapi.com.br)."""

    def lookup(self, cnpj: str) -> CompanyLookupResult:
        url = BRASILAPI_CNPJ_URL.format(cnpj=cnpj)
        timeout = httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=READ_TIMEOUT, pool=READ_TIMEOUT)

        try:
            response = httpx.get(url, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise CompanyLookupUnavailable("Tempo esgotado ao consultar a BrasilAPI.") from exc
        except httpx.HTTPError as exc:
            raise CompanyLookupUnavailable("Falha de rede ao consultar a BrasilAPI.") from exc

        if response.status_code == 404:
            raise CompanyLookupNotFound(f"CNPJ {cnpj} não encontrado na BrasilAPI.")

        if response.status_code != 200:
            raise CompanyLookupUnavailable(
                f"BrasilAPI retornou status inesperado ({response.status_code})."
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise CompanyLookupUnavailable("Resposta da BrasilAPI não é um JSON válido.") from exc

        try:
            return self._parse(cnpj, data)
        except (KeyError, TypeError, AttributeError) as exc:
            raise CompanyLookupUnavailable("Resposta da BrasilAPI em formato inesperado.") from exc

    @staticmethod
    def _parse(cnpj: str, data: dict) -> CompanyLookupResult:
        # Campos conforme documentação pública da BrasilAPI
        # (https://brasilapi.com.br/docs#tag/CNPJ). Tudo opcional/ausente
        # vira string vazia — nunca quebramos por campo faltando.
        phone = ""
        ddd = data.get("ddd_telefone_1") or ""
        if ddd:
            phone = ddd

        return CompanyLookupResult(
            cnpj=cnpj,
            company_name=data.get("razao_social") or "",
            trade_name=data.get("nome_fantasia") or "",
            registration_status=data.get("descricao_situacao_cadastral") or "",
            phone=phone,
            email=data.get("email") or "",
            address_cep=data.get("cep") or "",
            address_logradouro=data.get("logradouro") or "",
            address_numero=data.get("numero") or "",
            address_complemento=data.get("complemento") or "",
            address_bairro=data.get("bairro") or "",
            address_cidade=data.get("municipio") or "",
            address_uf=data.get("uf") or "",
        )
