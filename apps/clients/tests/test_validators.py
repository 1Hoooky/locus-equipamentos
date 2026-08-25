"""
Testes de `apps.clients.validators` — normalização e checksum de CNPJ/CPF.
Fonte única reaproveitada por `Client.clean()` e `CompanyLookupService`
(v1.0, seção 4) — testada isoladamente aqui, sem tocar banco.
"""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.clients.validators import (
    is_valid_cnpj,
    is_valid_cpf,
    normalize_document,
    validate_document_for_type,
)

VALID_CNPJ = "11.222.333/0001-81"  # dígitos verificadores corretos
VALID_CPF = "111.444.777-35"  # dígitos verificadores corretos


class NormalizeDocumentTest(SimpleTestCase):
    def test_removes_non_digits(self):
        self.assertEqual(normalize_document("11.222.333/0001-81"), "11222333000181")

    def test_blank_and_none(self):
        self.assertEqual(normalize_document(""), "")
        self.assertEqual(normalize_document(None), "")


class CnpjValidationTest(SimpleTestCase):
    def test_valid_cnpj_formatted_or_not(self):
        self.assertTrue(is_valid_cnpj(VALID_CNPJ))
        self.assertTrue(is_valid_cnpj("11222333000181"))

    def test_invalid_checksum(self):
        self.assertFalse(is_valid_cnpj("11222333000180"))

    def test_wrong_length(self):
        self.assertFalse(is_valid_cnpj("1122233300018"))
        self.assertFalse(is_valid_cnpj("112223330001811"))

    def test_all_same_digit_is_never_valid(self):
        self.assertFalse(is_valid_cnpj("11111111111111"))
        self.assertFalse(is_valid_cnpj("00000000000000"))


class CpfValidationTest(SimpleTestCase):
    def test_valid_cpf(self):
        self.assertTrue(is_valid_cpf(VALID_CPF))
        self.assertTrue(is_valid_cpf("11144477735"))

    def test_invalid_checksum(self):
        self.assertFalse(is_valid_cpf("11144477736"))

    def test_all_same_digit_is_never_valid(self):
        self.assertFalse(is_valid_cpf("11111111111"))


class ValidateDocumentForTypeTest(SimpleTestCase):
    def test_blank_is_allowed(self):
        self.assertEqual(validate_document_for_type("", "PJ"), "")
        self.assertEqual(validate_document_for_type("   ", "PJ"), "")

    def test_valid_pj_returns_normalized(self):
        self.assertEqual(validate_document_for_type(VALID_CNPJ, "PJ"), "11222333000181")

    def test_invalid_pj_raises(self):
        with self.assertRaises(ValidationError):
            validate_document_for_type("11222333000180", "PJ")

    def test_valid_pf_returns_normalized(self):
        self.assertEqual(validate_document_for_type(VALID_CPF, "PF"), "11144477735")

    def test_invalid_pf_raises(self):
        with self.assertRaises(ValidationError):
            validate_document_for_type("11144477736", "PF")

    def test_unknown_client_type_raises(self):
        with self.assertRaises(ValidationError):
            validate_document_for_type(VALID_CNPJ, "MEI")
