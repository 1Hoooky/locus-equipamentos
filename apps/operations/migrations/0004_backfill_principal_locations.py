"""
Backfill do 3º reteste manual: clientes criados ANTES da criação
automática da Location principal (2º reteste) não têm nenhuma
`Location(type=CLIENTE)` ativa — e como o seletor de instalação lista
Locations (não Clients), esses clientes sumiram das opções de destino.
Consequência da evolução do fluxo, corrigida com backfill dos dados
existentes — nunca criando Location dinamicamente ao abrir o formulário.

Inspeção prévia dos dados (obrigação do reteste): no banco deste
repositório não existe NENHUM cliente (os cadastros reais vivem só no
ambiente do usuário), então os casos abaixo foram enumerados a partir do
schema e do relato — a migration cobre todos e os testes de backfill
(`apps/operations/tests/test_backfill_principal_locations.py`) simulam
cada um:

1. Cliente ativo SEM nenhuma Location CLIENTE — o caso relatado: ganha
   exatamente UMA "Unidade principal".
   a. Se alguma Location CLIENTE INATIVA dele tiver endereço, esse
      endereço operacional existente é a fonte preferida (pedido
      explícito: "use o endereço operacional existente quando houver").
   b. Senão, se houver endereço fiscal, os VALORES são copiados para um
      Address NOVO — nunca a mesma linha, preservando a independência
      fiscal × operacional (editar um nunca altera o outro).
   c. Sem endereço nenhum: a Location nasce sem address (mesmo
      comportamento de create_location() com endereço em branco).
2. Cliente ativo COM Location CLIENTE ativa — intocado (nenhuma Location
   extra).
3. Cliente INATIVO — intocado (não deve voltar a aparecer em seleção).

Idempotente por construção: a condição de entrada é "não tem Location
CLIENTE ativa", e a própria execução cria uma — rodar de novo não
encontra mais ninguém elegível. Segura em banco existente: só INSERTs de
Location/Address novos, nenhum UPDATE/DELETE em dados já gravados.
Reverso é no-op (remover as Locations criadas poderia quebrar Movements
que passem a referenciá-las).
"""

from django.db import migrations

PRINCIPAL_NAME = "Unidade principal"


def _copy_address(Address, source):
    """Sempre uma linha NOVA — nunca reaproveita a FK (independência fiscal × operacional)."""
    if source is None:
        return None
    return Address.objects.create(
        cep=source.cep,
        logradouro=source.logradouro,
        numero=source.numero,
        complemento=source.complemento,
        bairro=source.bairro,
        cidade=source.cidade,
        uf=source.uf,
        reference_notes=source.reference_notes,
    )


def backfill_principal_locations(apps, schema_editor):
    Client = apps.get_model("clients", "Client")
    Location = apps.get_model("operations", "Location")
    Address = apps.get_model("core", "Address")

    for client in Client.objects.filter(is_active=True).select_related("fiscal_address"):
        if Location.objects.filter(client=client, type="CLIENTE", is_active=True).exists():
            continue  # caso 2: já tem unidade ativa — nada a fazer

        # Caso 1a: endereço operacional já existente (numa unidade
        # inativa) é a fonte preferida; 1b: valores do fiscal; 1c: nada.
        source_address = None
        inactive_with_address = (
            Location.objects.filter(client=client, type="CLIENTE", is_active=False, address__isnull=False)
            .select_related("address")
            .order_by("-pk")
            .first()
        )
        if inactive_with_address is not None:
            source_address = inactive_with_address.address
        elif client.fiscal_address_id is not None:
            source_address = client.fiscal_address

        Location.objects.create(
            name=PRINCIPAL_NAME,
            type="CLIENTE",
            client=client,
            address=_copy_address(Address, source_address),
            is_active=True,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0003_seed_internal_locations"),
        ("clients", "0003_alter_client_company_name_alter_client_document_and_more"),
        ("core", "0002_consumedsubmissiontoken"),
    ]

    operations = [
        migrations.RunPython(backfill_principal_locations, migrations.RunPython.noop),
    ]
