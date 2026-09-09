"""
Testes do parser de importação de clientes do Auvo (`apps.clients.import_auvo`)
— LocusHub, 08/09/2026. Cobre só a camada de leitura/classificação
(NUNCA grava no banco); o fluxo HTTP completo (upload → revisão →
confirmação, permissões, criação real) está em `test_import_auvo_views.py`.
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook

from apps.clients.import_auvo import (
    INVALIDO,
    JA_EXISTENTE,
    NOVO,
    POSSIVEL_DUPLICADO,
    REQUIRED_HEADERS,
    ClientImportError,
    parse_client_workbook,
)
from apps.clients.models import Client, ClientType
from apps.clients.services import NewClientData, create_client

EXPLANATORY_ROW = [
    "Código do cliente gerado automaticamente no Auvo",
    "Código de outro sistema",
    "Nome do cliente",
    "CPF ou o CNPJ do cliente.",
    "Razão social",
    "Endereço do cliente.",
    "Complemento do Endereço",
    "Telefone corporativo.",
    "E-mail corporativo.",
    "Falar com",
    "Segmento do cliente",
    "Observação do cliente.",
    "Observação Interna",
    "Status do cliente. 'Ativo' ou 'Inativo'.",
    "Anotação do cliente.",
    "Data que este cliente foi cadastrado.",
    "Contribuinte do ICMS",
    "Inscrição Estadual",
    "Inscrição Municipal",
    "E-mail de cobrança",
    "CEP de cobrança",
    "Logradouro endereço de cobrança",
    "Número endereço de cobrança",
    "Complemento endereço de cobrança",
    "Bairro de cobrança",
    "Cidade de cobrança",
    "Estado de cobrança",
]


def _row(**values) -> list:
    return [str(values.get(h, "")) for h in REQUIRED_HEADERS]


def _build_workbook_bytes(data_rows, headers=REQUIRED_HEADERS, include_explanatory_row=True):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    if include_explanatory_row:
        ws.append(EXPLANATORY_ROW)
    for row in data_rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()


class _InMemoryUpload:
    """Mesmo wrapper mínimo usado pelos testes do importador de equipamentos legado."""

    def __init__(self, content: bytes):
        self._content = content

    def read(self):
        return self._content


def _parse(data_rows, **kwargs):
    content = _build_workbook_bytes(data_rows, **kwargs)
    return parse_client_workbook(_InMemoryUpload(content))


class FileValidationTest(TestCase):
    def test_invalid_file_content_raises_client_import_error(self):
        with self.assertRaises(ClientImportError):
            parse_client_workbook(_InMemoryUpload(b"isto nao e uma planilha excel"))

    def test_missing_required_columns_raises_client_import_error(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Nome", "Alguma outra coluna"])
        ws.append(["explicativa", "explicativa"])
        ws.append(["Cliente X", "valor"])
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        with self.assertRaises(ClientImportError):
            parse_client_workbook(_InMemoryUpload(buffer.read()))

    def test_columns_in_different_order_are_still_recognized(self):
        """Colunas resolvidas pelo nome do cabeçalho, não pela posição."""
        shuffled_headers = list(reversed(REQUIRED_HEADERS))
        values = {"Nome": "Cliente Invertido", "CPF ou CNPJ": "11.222.333/0001-81"}
        row = [str(values.get(h, "")) for h in shuffled_headers]
        parsed = _parse([row], headers=shuffled_headers)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].nome, "Cliente Invertido")

    def test_explanatory_row_right_below_header_is_always_ignored(self):
        rows = [_row(Nome="Cliente Um", **{"CPF ou CNPJ": "11.222.333/0001-81"})]
        parsed = _parse(rows, include_explanatory_row=True)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].row_number, 3)
        self.assertEqual(parsed[0].nome, "Cliente Um")

    def test_completely_blank_row_is_silently_skipped(self):
        rows = [
            _row(),  # linha totalmente vazia, tipo sobra de formatação no fim da planilha
            _row(Nome="Cliente Um", **{"CPF ou CNPJ": "11.222.333/0001-81"}),
        ]
        parsed = _parse(rows)
        self.assertEqual(len(parsed), 1)


class DocumentClassificationTest(TestCase):
    def test_pj_with_valid_cnpj_is_novo(self):
        rows = [_row(Nome="Cliente PJ", **{"CPF ou CNPJ": "11.222.333/0001-81"})]
        parsed = _parse(rows)
        self.assertEqual(parsed[0].classification, NOVO)
        self.assertEqual(parsed[0].payload.client_type, ClientType.PJ)
        self.assertEqual(parsed[0].payload.document, "11222333000181")

    def test_pf_with_valid_cpf_is_novo(self):
        rows = [_row(Nome="Cliente PF", **{"CPF ou CNPJ": "529.982.247-25"})]
        parsed = _parse(rows)
        self.assertEqual(parsed[0].classification, NOVO)
        self.assertEqual(parsed[0].payload.client_type, ClientType.PF)
        self.assertEqual(parsed[0].payload.document, "52998224725")

    def test_invalid_cnpj_checksum_is_invalido(self):
        rows = [_row(Nome="Cliente Ruim", **{"CPF ou CNPJ": "11.222.333/0001-80"})]
        parsed = _parse(rows)
        self.assertEqual(parsed[0].classification, INVALIDO)
        self.assertIn("inválido", parsed[0].reason.lower())

    def test_document_with_wrong_digit_count_is_invalido(self):
        rows = [_row(Nome="Cliente Ruim", **{"CPF ou CNPJ": "12345"})]
        parsed = _parse(rows)
        self.assertEqual(parsed[0].classification, INVALIDO)

    def test_client_without_document_is_novo_when_no_name_clash(self):
        rows = [_row(Nome="Cliente Sem Documento", **{"Razão social": "Cliente Sem Documento LTDA"})]
        parsed = _parse(rows)
        self.assertEqual(parsed[0].classification, NOVO)
        self.assertEqual(parsed[0].payload.document, "")

    def test_missing_name_and_company_name_is_invalido(self):
        # Linha com dado real (telefone) mas sem Nome nem Razão social —
        # diferente de uma linha totalmente vazia (sobra de formatação),
        # que é apenas ignorada (ver test_completely_blank_row_is_silently_skipped).
        rows = [_row(Código="24999999", **{"Telefone corporativo": "44999990000"})]
        parsed = _parse(rows)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].classification, INVALIDO)
        self.assertIn("Nome e razão social ausentes", parsed[0].reason)


class DeduplicationTest(TestCase):
    def test_existing_document_is_ja_existente(self):
        create_client(NewClientData(client_type=ClientType.PJ, company_name="Já Cadastrado LTDA", document="11.222.333/0001-81"))
        rows = [_row(Nome="Já Cadastrado", **{"CPF ou CNPJ": "11.222.333/0001-81"})]
        parsed = _parse(rows)
        self.assertEqual(parsed[0].classification, JA_EXISTENTE)

    def test_existing_auvo_code_is_ja_existente_even_with_different_document(self):
        create_client(
            NewClientData(client_type=ClientType.PJ, company_name="Reimportado LTDA", document="11.222.333/0001-81", auvo_code="AUVO-1"),
        )
        rows = [_row(Nome="Reimportado", Código="AUVO-1", **{"CPF ou CNPJ": "11.444.777/0001-61"})]
        parsed = _parse(rows)
        self.assertEqual(parsed[0].classification, JA_EXISTENTE)
        self.assertIn("AUVO-1", parsed[0].reason)

    def test_two_documentless_rows_with_near_identical_name_are_possivel_duplicado(self):
        rows = [
            _row(Nome="Sicredi Unidade Norte", **{"Razão social": "Cooperativa Sicredi Central LTDA"}),
            _row(Nome="Sicredi Unidade Sul", **{"Razão social": "Cooperativa Sicredi Central LTDA"}),
        ]
        parsed = _parse(rows)
        self.assertEqual(parsed[0].classification, NOVO)
        self.assertEqual(parsed[1].classification, POSSIVEL_DUPLICADO)

    def test_documentless_row_against_existing_client_with_similar_name_is_possivel_duplicado(self):
        create_client(NewClientData(client_type=ClientType.PJ, company_name="Cooperativa Sicredi Central LTDA", document=""), require_document=False)
        rows = [_row(Nome="Filial", **{"Razão social": "Cooperativa Sicredi Central LTDA"})]
        parsed = _parse(rows)
        self.assertEqual(parsed[0].classification, POSSIVEL_DUPLICADO)

    def test_documentless_rows_with_unrelated_names_are_both_novo(self):
        rows = [
            _row(Nome="Padaria Bom Pão", **{"Razão social": "Padaria Bom Pão LTDA"}),
            _row(Nome="Auto Peças Silva", **{"Razão social": "Auto Peças Silva ME"}),
        ]
        parsed = _parse(rows)
        self.assertEqual(parsed[0].classification, NOVO)
        self.assertEqual(parsed[1].classification, NOVO)


class FieldMappingTest(TestCase):
    def test_multiple_phones_first_goes_to_phone_rest_to_notes(self):
        rows = [_row(Nome="Cliente", **{"Telefone corporativo": " (44) 3033-0000 ; (44) 99999-0000 ; (44) 3033-0000 "})]
        parsed = _parse(rows)
        payload = parsed[0].payload
        self.assertEqual(payload.phone, "(44) 3033-0000")
        self.assertIn("Telefones adicionais (Auvo): (44) 99999-0000", payload.notes)
        # duplicata exata do telefone principal não aparece de novo em notes
        self.assertNotIn("(44) 3033-0000", payload.notes)

    def test_multiple_emails_first_goes_to_email_rest_to_notes(self):
        rows = [_row(Nome="Cliente", **{"E-mail corporativo": "financeiro@x.com ; contato@x.com"})]
        parsed = _parse(rows)
        payload = parsed[0].payload
        self.assertEqual(payload.email, "financeiro@x.com")
        self.assertIn("E-mails adicionais (Auvo): contato@x.com", payload.notes)

    def test_structured_billing_address_is_used_for_fiscal_address(self):
        rows = [
            _row(
                Nome="Cliente",
                **{
                    "Endereço": "Texto livre que não deve ser usado",
                    "CEP de cobrança": "87.083-304",
                    "Logradouro endereço de cobrança": "Av. Brasil",
                    "Número endereço de cobrança": "100",
                    "Bairro de cobrança": "Centro",
                    "Cidade de cobrança": "Maringá",
                    "Estado de cobrança": "PR",
                },
            )
        ]
        parsed = _parse(rows)
        payload = parsed[0].payload
        # CEP normalizado para o formato canônico "00000-000" — a planilha
        # real do Auvo traz esse mesmo dado em pelo menos 3 formatos
        # diferentes, um deles (com ponto extra) maior do que `Address.cep`
        # comporta (ver `_normalize_cep`).
        self.assertEqual(payload.fiscal_cep, "87083-304")
        self.assertEqual(payload.fiscal_logradouro, "Av. Brasil")
        self.assertEqual(payload.fiscal_cidade, "Maringá")
        # endereço livre não vira parte de notes quando há endereço estruturado
        self.assertNotIn("Endereço original", payload.notes)

    def test_free_text_address_preserved_in_notes_when_no_structured_billing_address(self):
        rows = [_row(Nome="Cliente", **{"Endereço": "Rua das Flores, 123, Centro", "Complemento do Endereço": "Sala 2"})]
        parsed = _parse(rows)
        payload = parsed[0].payload
        self.assertEqual(payload.fiscal_logradouro, "")
        self.assertIn("Endereço original (Auvo): Rua das Flores, 123, Centro — Sala 2", payload.notes)

    def test_fiscal_and_workflow_fields_are_preserved(self):
        rows = [
            _row(
                Nome="Cliente",
                Código="AUVO-42",
                **{
                    "Código externo": "EXT-9",
                    "Falar com": "Maria",
                    "Status": "Ativo",
                    "Contribuinte do ICMS": "1",
                    "Inscrição Estadual": "9099492896",
                    "Inscrição Municipal": "12345",
                    "E-mail de cobrança": "cobranca@x.com",
                },
            )
        ]
        parsed = _parse(rows)
        payload = parsed[0].payload
        self.assertEqual(payload.auvo_code, "AUVO-42")
        self.assertEqual(payload.external_code, "EXT-9")
        self.assertEqual(payload.contact_name, "Maria")
        self.assertEqual(payload.registration_status, "Ativo")
        self.assertEqual(payload.icms_taxpayer, "1")
        self.assertEqual(payload.state_registration, "9099492896")
        self.assertEqual(payload.municipal_registration, "12345")
        self.assertEqual(payload.billing_email, "cobranca@x.com")

    def test_notes_omits_blank_fields_and_ignored_columns(self):
        rows = [_row(Nome="Cliente", **{"Razão social": "Cliente LTDA"})]
        parsed = _parse(rows)
        self.assertEqual(parsed[0].payload.notes, "")

    def test_notes_include_segmento_observacao_anotacao_e_data_cadastro_organizadamente(self):
        rows = [
            _row(
                Nome="Cliente",
                **{
                    "Segmento": "Construção civil",
                    "Observação": "Plano premium",
                    "Observação Interna": "Cliente atrasa pagamento",
                    "Anotação": "Visitado em agosto",
                    "Data de cadastro": "06/08/2026 11:34",
                },
            )
        ]
        parsed = _parse(rows)
        notes = parsed[0].payload.notes
        self.assertTrue(notes.startswith("[Dados importados do Auvo]"))
        self.assertIn("Segmento (Auvo): Construção civil", notes)
        self.assertIn("Observação (Auvo): Plano premium", notes)
        self.assertIn("Observação interna (Auvo): Cliente atrasa pagamento", notes)
        self.assertIn("Anotação (Auvo): Visitado em agosto", notes)
        self.assertIn("Data de cadastro no Auvo: 06/08/2026 11:34", notes)


class RealFileRegressionSmokeTest(TestCase):
    """
    Não substitui a homologação com a planilha real (fora do repositório),
    mas fixa em código o formato mínimo esperado, para não regredir
    silenciosamente se o layout do parser mudar no futuro.
    """

    def test_parses_716_row_shaped_file_without_error(self):
        rows = [_row(Nome=f"Cliente {i}", **{"CPF ou CNPJ": ""}) for i in range(5)]
        parsed = _parse(rows)
        self.assertEqual(len(parsed), 5)
        self.assertTrue(all(r.classification in (NOVO, POSSIVEL_DUPLICADO) for r in parsed))
