# RODADA 1 — Planos Comerciais + Prazos + Matriz de Preços de Locação
# (16/09/2026). Semeia os 5 planos comerciais de Locação confirmados na
# especificação e os prazos iniciais de cada um — idempotente
# (`get_or_create`), MESMO padrão já usado em `0009_seed_hora_tecnica.py`.
#
# Nenhum `PriceTableRate` é semeado aqui (seção: "não inventar preço" —
# só a ESTRUTURA de planos/prazos nasce pronta; os valores de cada célula
# da matriz são preenchidos manualmente pelo Administrador/Comercial pela
# tela, exatamente como já acontecia com `PriceTableItem` na V1).
#
# Decisão de produto registrada (duração estruturada dos prazos "Locação
# Mensal", já que a especificação descreve "30/60/90 dias-ou-meses" sem
# fechar a unidade): usamos `DurationUnit.DIAS` com os valores 30/60/90
# (linguagem comercial usual — "aluguel por 30/60/90 dias") em vez de
# `MESES` 1/2/3, para não sugerir arredondamento de mês civil nenhum. Se
# essa decisão precisar mudar, é só editar os 3 `CommercialTerm` — nenhum
# outro dado depende do valor estrutural aqui (o texto de exibição real
# na matriz é sempre `label`).
#
# "Locação Anual" (12/24/36 meses) e "Máquinas Instaladas" (36/48/60
# meses) SOBREPÕEM-SE deliberadamente em 36 meses — são dois
# `CommercialPlan` distintos, então duas linhas `CommercialTerm`
# distintas (`unique_together` é por (plano, label), nunca global) — cada
# uma com seu próprio `PriceTableRate` por equipamento.

from django.db import migrations

PLANS = [
    # (name, order, terms=[(duration_value, duration_unit, order), ...])
    # "Locação Comum" e "Locação Eventos" são DOIS planos distintos (seção:
    # "Comum & Eventos: 1/3/5/7/15 dias como CommercialTerm SEPARADOS por
    # plano") — cada um com seu próprio conjunto de prazos, mesmo que os
    # valores estruturais (1/3/5/7/15 dias) coincidam entre os dois; os
    # `PriceTableRate` de cada plano são independentes.
    (
        "Locação Comum",
        0,
        [(1, "DIAS", 0), (3, "DIAS", 1), (5, "DIAS", 2), (7, "DIAS", 3), (15, "DIAS", 4)],
    ),
    (
        "Locação Eventos",
        1,
        [(1, "DIAS", 0), (3, "DIAS", 1), (5, "DIAS", 2), (7, "DIAS", 3), (15, "DIAS", 4)],
    ),
    (
        "Locação Mensal",
        2,
        [(30, "DIAS", 0), (60, "DIAS", 1), (90, "DIAS", 2)],
    ),
    (
        "Locação Anual",
        3,
        [(12, "MESES", 0), (24, "MESES", 1), (36, "MESES", 2)],
    ),
    (
        "Máquinas Instaladas",
        4,
        [(36, "MESES", 0), (48, "MESES", 1), (60, "MESES", 2)],
    ),
]


def seed_plans_and_terms(apps, schema_editor):
    CommercialPlan = apps.get_model("crm", "CommercialPlan")
    CommercialTerm = apps.get_model("crm", "CommercialTerm")

    def _unit_label(duration_value, duration_unit):
        if duration_unit == "DIAS":
            return "dia" if duration_value == 1 else "dias"
        return "mês" if duration_value == 1 else "meses"

    for name, order, terms in PLANS:
        plan, _ = CommercialPlan.objects.get_or_create(
            name=name,
            defaults={
                "business_type": "LOCACAO",
                "pricing_mode": "ITEM_TERM",
                "order": order,
                "is_active": True,
            },
        )
        for duration_value, duration_unit, term_order in terms:
            label = f"{duration_value} {_unit_label(duration_value, duration_unit)}"
            CommercialTerm.objects.get_or_create(
                commercial_plan=plan,
                label=label,
                defaults={
                    "duration_value": duration_value,
                    "duration_unit": duration_unit,
                    "order": term_order,
                    "is_active": True,
                },
            )


def remove_plans_and_terms(apps, schema_editor):
    # Reversibilidade seletiva (mesmo raciocínio de `0009_seed_hora_
    # tecnica.py`): remove só os planos com EXATAMENTE estes nomes — nunca
    # um plano homônimo criado manualmente depois seria diferenciável, mas
    # nenhuma tela desta rodada permite renomear um plano existente para
    # um destes nomes, então o risco é o mesmo já aceito nas migrations de
    # seed anteriores do app. `CommercialTerm` é CASCADE a partir de
    # `CommercialPlan`, então apagar o plano já remove os prazos.
    CommercialPlan = apps.get_model("crm", "CommercialPlan")
    CommercialPlan.objects.filter(name__in=[name for name, _, _ in PLANS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0011_rodada1_commercial_plans"),
    ]

    operations = [
        migrations.RunPython(seed_plans_and_terms, remove_plans_and_terms),
    ]
