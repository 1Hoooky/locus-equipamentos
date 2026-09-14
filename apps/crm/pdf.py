"""
Geração de PDF de Proposta Comercial/Contrato — segue exatamente o mesmo
padrão já usado em `apps.qrcodes.services` (único gerador de PDF que já
existia no projeto antes desta rodada): `render_to_string()` de um
template HTML comum + `weasyprint.HTML(string=...).write_pdf()`. Nenhuma
biblioteca nova, nenhum padrão novo.

Só LÊ campos já congelados (`ProposalVersion.*_snapshot`,
`ProposalItem.description_snapshot`, etc.) — nunca consulta
`Client`/`CompanyProfile`/`EquipmentModel` ao vivo para montar o PDF de
uma versão já emitida (seção 62, "PDF NÃO CONSULTA DADOS MUTÁVEIS").
"""

from django.template.loader import render_to_string
from weasyprint import HTML

from apps.crm.models import Contract, ProposalVersion


def render_proposal_pdf(proposal_version: ProposalVersion) -> bytes:
    html_string = render_to_string(
        "crm/pdf/proposal.html",
        {
            "proposal": proposal_version.proposal,
            "version": proposal_version,
            "items": proposal_version.items.all(),
        },
    )
    return HTML(string=html_string).write_pdf()


def render_contract_pdf(contract: Contract) -> bytes:
    version = contract.proposal_version
    html_string = render_to_string(
        "crm/pdf/contract.html",
        {
            "contract": contract,
            "proposal": version.proposal,
            "version": version,
            "items": version.items.all(),
        },
    )
    return HTML(string=html_string).write_pdf()
