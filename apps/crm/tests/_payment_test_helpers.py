"""
Helper compartilhado para testes LEGADOS que emitem uma `ProposalVersion`
(`issue_proposal()`/`generate_documents(document_type=PROPOSTA...)`) sem
configurar pagamento explicitamente — FECHAMENTO DA PROPOSTA COMERCIAL
(23/09/2026, seção 22) introduziu uma validação NOVA e obrigatória:
emissão exige pelo menos 1 parcela cuja soma bata com o total. Testes
escritos ANTES desta rodada (RODADA 3/4, REFINAMENTO VISUAL, etc.) não
tinham motivo para configurar isso — em vez de reescrever cada `setUp()`
manualmente, este helper único adiciona 1 parcela PIX cobrindo o total
exato da versão, mantendo o COMPORTAMENTO ORIGINAL de cada teste (o que
eles queriam testar nunca era pagamento) sem duplicar lógica em ~20
pontos de chamada.
"""

from datetime import date

from apps.crm.services import ProposalInstallmentData, add_installment


def add_full_installment(version, *, due_date=None, payment_method="PIX"):
    """
    Substitui QUALQUER parcela já existente na versão (ex.: clonada de
    uma versão anterior por `create_new_version()`) por 1 única parcela
    cobrindo o total ATUAL — nunca soma em cima do que já existia (o
    objetivo é só "deixar a versão pronta para emitir", não simular uma
    negociação real de múltiplas parcelas).
    """
    version.refresh_from_db()
    version.installments.all().delete()
    add_installment(
        proposal_version=version,
        data=ProposalInstallmentData(
            payment_method=payment_method,
            amount=version.total,
            due_date=due_date or date(2026, 12, 31),
        ),
    )
    return version
