"""
"Valor por extenso" (FECHAMENTO DA PROPOSTA COMERCIAL, 23/09/2026, seção
13): converte um total em R$ para texto em português ("três mil e
sessenta reais"). Auditoria confirmou que este projeto não tinha nenhum
helper equivalente (nem dependência já instalada) — `num2words` (pt_BR)
foi adicionado (`requirements/base.txt`) por já ser a implementação de
referência da conversão cardinal em português, testada e mantida por
terceiros, em vez de reescrever a gramática de números por extenso do
zero (plurais irregulares, "e" entre centenas/dezenas, "cem" vs "cento",
etc.).

Este módulo é só uma casca FINA e determinística por cima do
`Num2Word_PT_BR.to_currency()`: nunca aceita/produz `float` (seção 13,
"nunca usar float") — o valor sempre chega como `Decimal` e a formatação
interna (`'%.2f' % val`) opera sobre o próprio `Decimal` (o operador `%`
do Python aceita `Decimal` sem passar por `float`), preservando exatidão
de centavos. O valor NUNCA é armazenado — é sempre DERIVADO na hora
(nunca um campo editável em `ProposalVersion`/formulário, seção 13).
"""

from decimal import Decimal

from num2words import num2words


def valor_por_extenso(value: Decimal) -> str:
    """
    "R$ 3.060,00" -> "três mil e sessenta reais". Levanta `ValueError`
    para valor negativo (um total de proposta nunca é negativo —
    `calculate_proposal_version()` já impede isso a montante; esta
    função só recusa explicitamente em vez de produzir um texto sem
    sentido do tipo "menos três mil reais" para o cliente).
    """
    if not isinstance(value, Decimal):
        raise TypeError("valor_por_extenso() espera um Decimal — nunca float (seção 13).")
    if value < 0:
        raise ValueError("Não é possível escrever por extenso um valor negativo.")

    text: str = num2words(value, lang="pt_BR", to="currency")
    return text
