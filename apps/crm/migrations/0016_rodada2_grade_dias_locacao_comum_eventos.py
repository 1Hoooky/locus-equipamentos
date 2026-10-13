# RODADA 2 — INTEGRAÇÃO DA MATRIZ DE PREÇOS COM A PROPOSTA (13/10/2026).
#
# Migra a grade de prazos em DIAS de "Locação Comum" e "Locação Eventos"
# de 1/3/5/7/15 para 1/5/15/30 (decisão de produto confirmada
# explicitamente na revisão do plano técnico da RODADA 2 — seções 2/3).
# NENHUM outro plano é tocado: "Locação Mensal" (30/60/90 dias),
# "Locação Anual" (12/24/36 meses) e "Máquinas Instaladas" (36/48/60
# meses) ficam exatamente como estavam.
#
# NÃO edita `0012_seed_commercial_plans_terms.py` (migration antiga já
# aplicada) — esta é uma migration de dados NOVA, idempotente:
#   - "3 dias"/"7 dias" são INATIVADOS (`is_active=False`), nunca
#     apagados — `PriceTableRate.commercial_term` é `on_delete=PROTECT`
#     (um hard delete seria bloqueado pelo próprio banco se qualquer
#     preço já tivesse sido cadastrado para esses prazos; aqui nem
#     chegamos a tentar). Qualquer `PriceTableRate`/histórico
#     (`HistoricalPriceTableRate`) já vinculado a esses termos permanece
#     intacto no banco — só deixa de aparecer como coluna ativa da
#     matriz e de ser elegível por `get_suggested_rental_price()`
#     (mesmo padrão de "inativar nunca apaga" já usado em todo o resto
#     do catálogo comercial deste app).
#   - "1 dia"/"5 dias"/"15 dias" não são tocados.
#   - "30 dias" é CRIADO se não existir; se já existir mas estiver
#     INATIVO (ex.: alguém rodou esta migration, desativou manualmente,
#     e está rodando de novo), é REATIVADO em vez de duplicado — nunca
#     cria uma segunda linha para o mesmo (plano, duração).
#
# Localização dos termos é SEMPRE por (`commercial_plan`,
# `duration_value`, `duration_unit`) — nunca só pelo texto de `label`
# (que é só exibição e poderia ter sido editado manualmente por alguém).
#
# Idempotente: rodar esta migration mais de uma vez (ex.: re-deploy,
# `migrate` repetido) produz exatamente o mesmo estado final, sem
# duplicar nem perder nada.
#
# Reversibilidade SELETIVA (mesmo raciocínio de
# `0012_seed_commercial_plans_terms.py::remove_plans_and_terms`): o
# `reverse_code` reativa "3 dias"/"7 dias" — mas NUNCA desativa "30
# dias" de volta (se a essa altura já existir algum `PriceTableRate`
# real cadastrado para 30 dias, desfazer isso destruiria uma
# configuração comercial em uso; mais seguro deixar "30 dias" como
# está e documentar a assimetria aqui do que arriscar apagar preço
# configurado).

from django.db import migrations
from django.db.models import Max

PLAN_NAMES = ["Locação Comum", "Locação Eventos"]


def _unit_label(duration_value, duration_unit):
    if duration_unit == "DIAS":
        return "dia" if duration_value == 1 else "dias"
    return "mês" if duration_value == 1 else "meses"


def migrate_grade_forward(apps, schema_editor):
    CommercialPlan = apps.get_model("crm", "CommercialPlan")
    CommercialTerm = apps.get_model("crm", "CommercialTerm")

    for plan_name in PLAN_NAMES:
        plan = CommercialPlan.objects.filter(name=plan_name).first()
        if plan is None:
            # Nunca falha a migration por um plano renomeado/removido
            # manualmente fora deste fluxo — idempotente mesmo num
            # estado inesperado (mesmo espírito defensivo de
            # `0009_seed_hora_tecnica.py`).
            continue

        CommercialTerm.objects.filter(
            commercial_plan=plan, duration_value__in=[3, 7], duration_unit="DIAS"
        ).update(is_active=False)

        thirty_days = CommercialTerm.objects.filter(
            commercial_plan=plan, duration_value=30, duration_unit="DIAS"
        ).first()
        if thirty_days is None:
            next_order = (plan.terms.aggregate(Max("order"))["order__max"] or -1) + 1
            CommercialTerm.objects.create(
                commercial_plan=plan,
                label=f"30 {_unit_label(30, 'DIAS')}",
                duration_value=30,
                duration_unit="DIAS",
                order=next_order,
                is_active=True,
            )
        elif not thirty_days.is_active:
            thirty_days.is_active = True
            thirty_days.save(update_fields=["is_active"])


def migrate_grade_backward(apps, schema_editor):
    CommercialPlan = apps.get_model("crm", "CommercialPlan")
    CommercialTerm = apps.get_model("crm", "CommercialTerm")

    for plan_name in PLAN_NAMES:
        plan = CommercialPlan.objects.filter(name=plan_name).first()
        if plan is None:
            continue
        CommercialTerm.objects.filter(
            commercial_plan=plan, duration_value__in=[3, 7], duration_unit="DIAS"
        ).update(is_active=True)
        # "30 dias" deliberadamente NÃO é desativado aqui — ver
        # docstring do topo do arquivo ("Reversibilidade SELETIVA").


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0015_redesenho_proposta_endereco_granular"),
    ]

    operations = [
        migrations.RunPython(migrate_grade_forward, migrate_grade_backward),
    ]
