"""
Testes de `CompanyLookupService`/`BrasilAPICompanyLookupProvider` — v1.0,
seção 4. Nenhum destes testes faz chamada HTTP real: `httpx.get` é sempre
mockado, então a suíte não depende de rede nem da BrasilAPI estar no ar.

Validação obrigatória #7: sucesso e indisponibilidade da consulta de CNPJ.
"""

from unittest.mock import Mock, patch

import httpx
from django.test import TestCase, override_settings

from apps.clients.lookup import (
    CompanyLookupNotFound,
    CompanyLookupResult,
    CompanyLookupService,
    CompanyLookupUnavailable,
)
from apps.clients.lookup.base import CompanyLookupProvider
from apps.clients.lookup.brasilapi import BrasilAPICompanyLookupProvider
from apps.clients.lookup.service import _PROVIDER_REGISTRY

VALID_CNPJ = "11.222.333/0001-81"


def _fake_response(status_code=200, json_data=None, json_error=False):
    response = Mock()
    response.status_code = status_code
    if json_error:
        response.json.side_effect = ValueError("invalid json")
    else:
        response.json.return_value = json_data or {}
    return response


class BrasilAPIProviderTest(TestCase):
    def test_success_maps_fields(self):
        payload = {
            "razao_social": "Empresa Exemplo LTDA",
            "nome_fantasia": "Exemplo",
            "descricao_situacao_cadastral": "ATIVA",
            "email": "contato@exemplo.com",
            "ddd_telefone_1": "41999999999",
            "cep": "80000000",
            "logradouro": "Rua Exemplo",
            "numero": "100",
            "complemento": "",
            "bairro": "Centro",
            "municipio": "Curitiba",
            "uf": "PR",
        }
        with patch("httpx.get", return_value=_fake_response(200, payload)):
            result = BrasilAPICompanyLookupProvider().lookup("11222333000181")

        self.assertIsInstance(result, CompanyLookupResult)
        self.assertEqual(result.company_name, "Empresa Exemplo LTDA")
        self.assertEqual(result.trade_name, "Exemplo")
        self.assertEqual(result.registration_status, "ATIVA")
        self.assertEqual(result.address_cidade, "Curitiba")
        self.assertEqual(result.address_uf, "PR")

    def test_404_raises_not_found(self):
        with patch("httpx.get", return_value=_fake_response(404)):
            with self.assertRaises(CompanyLookupNotFound):
                BrasilAPICompanyLookupProvider().lookup("11222333000181")

    def test_unexpected_status_raises_unavailable(self):
        with patch("httpx.get", return_value=_fake_response(500)):
            with self.assertRaises(CompanyLookupUnavailable):
                BrasilAPICompanyLookupProvider().lookup("11222333000181")

    def test_timeout_raises_unavailable(self):
        with patch("httpx.get", side_effect=httpx.TimeoutException("timed out")):
            with self.assertRaises(CompanyLookupUnavailable):
                BrasilAPICompanyLookupProvider().lookup("11222333000181")

    def test_connection_error_raises_unavailable(self):
        with patch("httpx.get", side_effect=httpx.ConnectError("connection refused")):
            with self.assertRaises(CompanyLookupUnavailable):
                BrasilAPICompanyLookupProvider().lookup("11222333000181")

    def test_malformed_json_raises_unavailable(self):
        with patch("httpx.get", return_value=_fake_response(200, json_error=True)):
            with self.assertRaises(CompanyLookupUnavailable):
                BrasilAPICompanyLookupProvider().lookup("11222333000181")

    def test_unexpected_payload_shape_raises_unavailable(self):
        """Corpo incompleto/malformado — ex.: a API devolve uma lista em vez de um objeto."""
        with patch("httpx.get", return_value=_fake_response(200, json_data=["não", "é", "um", "objeto"])):
            with self.assertRaises(CompanyLookupUnavailable):
                BrasilAPICompanyLookupProvider().lookup("11222333000181")


class CompanyLookupServiceTest(TestCase):
    def test_invalid_cnpj_never_calls_provider(self):
        with patch("httpx.get") as mock_get:
            with self.assertRaises(CompanyLookupNotFound):
                CompanyLookupService.lookup("11222333000180")  # checksum inválido
            mock_get.assert_not_called()

    def test_success_delegates_to_configured_provider(self):
        payload = {"razao_social": "Empresa Exemplo LTDA"}
        with patch("httpx.get", return_value=_fake_response(200, payload)):
            result = CompanyLookupService.lookup(VALID_CNPJ)
        self.assertEqual(result.company_name, "Empresa Exemplo LTDA")

    def test_provider_unavailable_propagates_as_company_lookup_unavailable(self):
        with patch("httpx.get", side_effect=httpx.TimeoutException("timed out")):
            with self.assertRaises(CompanyLookupUnavailable):
                CompanyLookupService.lookup(VALID_CNPJ)

    @override_settings(COMPANY_LOOKUP_PROVIDER="fake_test_provider")
    def test_swapping_provider_requires_no_change_to_the_service_contract(self):
        """
        v1.0, seção 2: 'trocar BrasilAPI por outro provider = escrever uma
        nova classe com este único método — nada mais muda'. Registra um
        provider falso só para este teste e confirma que
        `CompanyLookupService.lookup()` funciona identicamente, sem
        nenhuma mudança de código além do registro do provider.
        """

        class _FakeProvider(CompanyLookupProvider):
            def lookup(self, cnpj):
                return CompanyLookupResult(cnpj=cnpj, company_name="Vindo Do Provider Falso")

        # Provider precisa ser importável pelo caminho registrado (string
        # "módulo.Classe", resolvido via importlib em _resolve_provider())
        # — como é uma classe local de teste, expomos no módulo atual.
        import sys

        setattr(sys.modules[__name__], "_FakeProvider", _FakeProvider)
        _PROVIDER_REGISTRY["fake_test_provider"] = f"{__name__}._FakeProvider"
        try:
            result = CompanyLookupService.lookup(VALID_CNPJ)
            self.assertEqual(result.company_name, "Vindo Do Provider Falso")
        finally:
            del _PROVIDER_REGISTRY["fake_test_provider"]

    @override_settings(COMPANY_LOOKUP_PROVIDER="nao_existe")
    def test_unconfigured_provider_raises_unavailable(self):
        with self.assertRaises(CompanyLookupUnavailable):
            CompanyLookupService.lookup(VALID_CNPJ)
