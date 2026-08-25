"""
Normalização e validação de CNPJ/CPF — Fase 2 (Operação).

Fonte única usada tanto pela validação do model `Client` (`clean()`)
quanto por `CompanyLookupService` (arquitetura v1.0, seção 4: "reaproveita
a MESMA função de normalização usada pelo `Client.document`, para não ter
duas implementações de 'o que é um CNPJ válido' divergindo com o tempo").

Só CNPJ é exigido nesta etapa (Pessoa Jurídica). A validação de CPF já
entra pronta porque `Client.client_type` já prevê Pessoa Física para uma
evolução futura (v1.0, seção 1) — não é escopo novo, é só não deixar a
validação pela metade quando PF for de fato usado.
"""

import re

from django.core.exceptions import ValidationError


def normalize_document(value: str) -> str:
    """Remove tudo que não for dígito. `""`/`None` vira `""`."""
    if not value:
        return ""
    return re.sub(r"\D", "", value)


def _cnpj_checksum_digit(digits: str, weights: list[int]) -> int:
    total = sum(int(d) * w for d, w in zip(digits, weights, strict=True))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def is_valid_cnpj(value: str) -> bool:
    """Valida um CNPJ já normalizado (só dígitos, 14 caracteres) pelo algoritmo oficial de dígitos verificadores."""
    digits = normalize_document(value)
    if len(digits) != 14:
        return False
    if digits == digits[0] * 14:  # todos os dígitos iguais — nunca é um CNPJ válido, apesar de poder "passar" no cálculo
        return False

    first_check = _cnpj_checksum_digit(digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    if first_check != int(digits[12]):
        return False

    second_check = _cnpj_checksum_digit(digits[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return second_check == int(digits[13])


def _cpf_checksum_digit(digits: str, weights: list[int]) -> int:
    total = sum(int(d) * w for d, w in zip(digits, weights, strict=True))
    remainder = (total * 10) % 11
    return 0 if remainder == 10 else remainder


def is_valid_cpf(value: str) -> bool:
    """Valida um CPF já normalizado (só dígitos, 11 caracteres). Preparado para uma futura Fase 2 de Pessoa Física."""
    digits = normalize_document(value)
    if len(digits) != 11:
        return False
    if digits == digits[0] * 11:
        return False

    first_check = _cpf_checksum_digit(digits[:9], [10, 9, 8, 7, 6, 5, 4, 3, 2])
    if first_check != int(digits[9]):
        return False

    second_check = _cpf_checksum_digit(digits[:10], [11, 10, 9, 8, 7, 6, 5, 4, 3, 2])
    return second_check == int(digits[10])


def validate_document_for_type(value: str, client_type: str) -> str:
    """
    Normaliza e valida `value` conforme `client_type` ("PJ"/"PF").
    Retorna o documento normalizado (só dígitos) se válido; levanta
    `ValidationError` caso contrário. Documento em branco é permitido aqui
    (a obrigatoriedade, se houver, é decisão de formulário/serviço, não
    desta função) — só valida o formato quando algo foi informado.
    """
    normalized = normalize_document(value)
    if not normalized:
        return ""

    if client_type == "PJ":
        if not is_valid_cnpj(normalized):
            raise ValidationError("CNPJ inválido — confira os dígitos verificadores.")
    elif client_type == "PF":
        if not is_valid_cpf(normalized):
            raise ValidationError("CPF inválido — confira os dígitos verificadores.")
    else:
        raise ValidationError(f"Tipo de cliente desconhecido: {client_type!r}.")

    return normalized
