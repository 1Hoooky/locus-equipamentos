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

from decimal import Decimal

from django.template.loader import render_to_string
from weasyprint import HTML

from apps.crm.extenso import valor_por_extenso
from apps.crm.models import BusinessType, Contract, ProposalItemType, ProposalVersion

_MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def _cidade_data_extenso(proposal_version: ProposalVersion) -> str:
    """
    "Maringá, 23 de setembro de 2026" (seção 33) — construído em Python
    (nunca via filtro `|date` do template) para nunca depender da
    localidade ativa do Django (o projeto não usa `{% load l10n %}` em
    nenhum PDF, ver docstring de `proposal.html`); a data usada é sempre
    `issued_at` (a emissão REAL do documento), nunca `timezone.now()` —
    um PDF histórico nunca muda de data ao ser reaberto/reimpresso.
    """
    cidade = (proposal_version.company_city_snapshot or "").strip()
    uf = (proposal_version.company_uf_snapshot or "").strip()
    local = f"{cidade} - {uf}" if cidade and uf else cidade

    issued_at = proposal_version.issued_at
    if issued_at is None:
        return local
    mes = _MESES_PT[issued_at.month - 1]
    data = f"{issued_at.day} de {mes} de {issued_at.year}"
    return f"{local}, {data}" if local else data


def render_proposal_pdf(proposal_version: ProposalVersion) -> bytes:
    # FECHAMENTO DA PROPOSTA COMERCIAL (23/09/2026, seção 13/25): "valor
    # por extenso" e a tabela de parcelas entram no MESMO contexto
    # existente — nunca uma segunda função/rota de renderização. O valor
    # por extenso é sempre DERIVADO aqui (nunca lido de um campo
    # persistido) a partir do `total` já congelado da versão. Os
    # subtotais de equipamento/serviço (seção 11) também são somados aqui
    # em Python/Decimal — nunca com aritmética no template, que arrisca
    # comparação de string em vez de soma numérica.
    items = list(proposal_version.items.all())
    equipment_total = sum(
        (item.line_total for item in items if item.item_type == ProposalItemType.EQUIPAMENTO), Decimal("0.00")
    )
    services_total = sum(
        (item.line_total for item in items if item.item_type == ProposalItemType.SERVICO), Decimal("0.00")
    )
    html_string = render_to_string(
        "crm/pdf/proposal.html",
        {
            "proposal": proposal_version.proposal,
            "version": proposal_version,
            "items": items,
            "installments": proposal_version.installments.all(),
            "valor_extenso": valor_por_extenso(proposal_version.total),
            "equipment_total": equipment_total,
            "services_total": services_total,
            "is_venda": proposal_version.proposal.opportunity.business_type == BusinessType.VENDA,
            "cidade_data_extenso": _cidade_data_extenso(proposal_version),
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
