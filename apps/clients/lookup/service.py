"""
Orquestração da consulta de CNPJ (v1.0, seção 4):

    CompanyLookupService.lookup(cnpj):
        1. Normaliza e valida o CNPJ (reaproveita apps.clients.validators).
        2. Resolve o provider configurado (settings.COMPANY_LOOKUP_PROVIDER,
           default "brasilapi").
        3. Chama provider.lookup(cnpj) com timeout curto, sem retry.
        4. Qualquer falha vira CompanyLookupUnavailable (ou
           CompanyLookupNotFound quando o provider confirma que não existe).

Views/forms só conhecem esta classe e as exceções de
`apps.clients.lookup.base` — nunca um provider concreto.
"""

from django.conf import settings

from apps.clients.lookup.base import (
    CompanyLookupError,
    CompanyLookupNotFound,
    CompanyLookupProvider,
    CompanyLookupResult,
    CompanyLookupUnavailable,
)
from apps.clients.validators import is_valid_cnpj, normalize_document

# Registro de providers disponíveis. Trocar de fornecedor é acrescentar uma
# entrada aqui — nada em views/forms muda (v1.0, seção 2/4).
_PROVIDER_REGISTRY: dict[str, str] = {
    "brasilapi": "apps.clients.lookup.brasilapi.BrasilAPICompanyLookupProvider",
}


def _resolve_provider() -> CompanyLookupProvider:
    provider_key = getattr(settings, "COMPANY_LOOKUP_PROVIDER", "brasilapi")
    try:
        dotted_path = _PROVIDER_REGISTRY[provider_key]
    except KeyError as exc:
        raise CompanyLookupUnavailable(
            f"Provider de consulta de CNPJ não configurado corretamente: {provider_key!r}."
        ) from exc

    module_path, class_name = dotted_path.rsplit(".", 1)
    from importlib import import_module

    module = import_module(module_path)
    provider_class = getattr(module, class_name)
    return provider_class()


class CompanyLookupService:
    """
    Ponto único de entrada para consulta de CNPJ. Usado pela view/form de
    cadastro de cliente no fluxo "acelerador por CNPJ" (v1.0, seção 2) —
    o resultado é sempre uma revisão editável antes de salvar, nunca um
    `Client`/`Address` já persistido.
    """

    @staticmethod
    def lookup(cnpj: str) -> CompanyLookupResult:
        normalized = normalize_document(cnpj)
        if not is_valid_cnpj(normalized):
            raise CompanyLookupNotFound(f"CNPJ inválido: {cnpj!r}.")

        provider = _resolve_provider()
        try:
            return provider.lookup(normalized)
        except CompanyLookupError:
            # Já é uma das duas exceções esperadas — repassa como está.
            raise
        except Exception as exc:  # noqa: BLE001 — barreira final: nada de um provider mal comportado escapa daqui.
            raise CompanyLookupUnavailable("Falha inesperada ao consultar o CNPJ.") from exc
