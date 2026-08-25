"""
Bug relatado (#6): não existia nenhuma `Location` interna do tipo Estoque
ou Manutenção para usar em "Retirada"/"Retorno ao estoque"/"Envio para
manutenção" — a regra de compatibilidade destino×tipo estava correta, só
faltava o dado.

Solução arquitetural avaliada antes desta migration: um app/módulo novo
de "estoque"/"manutenção" foi descartado de propósito — o pedido explícito
foi reaproveitar o `Location` já existente (delta v1.1), sem hardcodar
esses conceitos em `Equipment`/`Movement`. Entre uma migration de dados
idempotente e um comando de management manual, a migration venceu: ela
roda automaticamente como parte do próprio `manage.py migrate` (nenhum
passo extra para lembrar em cada ambiente/deploy), e o Django já garante
que cada migration só executa UMA VEZ por banco (`django_migrations`) —
suficiente para "não duplicado a cada deploy". O `get_or_create()` abaixo
é uma camada extra de segurança (idempotência real, não só "não roda de
novo"), pelo mesmo espírito de outras validações redundantes já usadas
neste projeto (ex.: `_validate_location_client_matches_type`).

Reverso deliberadamente um no-op: apagar essas duas `Location` ao reverter
a migration arriscaria derrubar `Movement`s que já apontam para elas
(`on_delete=PROTECT` nem deixaria acontecer) e não haveria como
"desfazer" um possível uso operacional real que já tenha ocorrido.
"""

from django.db import migrations

ESTOQUE = "ESTOQUE"
MANUTENCAO = "MANUTENCAO"

# Nomes sugeridos na autorização desta etapa — só o valor inicial;
# renomear depois pela tela normal de edição de unidade não afeta nada
# aqui (a migration não roda de novo, e mesmo que rodasse, o "get" do
# get_or_create só re-cria se não achar uma linha com este nome
# específico, o que é o comportamento esperado/aceito).
SEED_LOCATIONS = (
    (ESTOQUE, "Estoque Locus"),
    (MANUTENCAO, "Manutenção Locus"),
)


def seed_internal_locations(apps, schema_editor):
    Location = apps.get_model("operations", "Location")
    for type_, name in SEED_LOCATIONS:
        Location.objects.get_or_create(type=type_, client=None, name=name, defaults={"is_active": True})


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0002_historicallocation_movement_alter_location_address_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_internal_locations, migrations.RunPython.noop),
    ]
