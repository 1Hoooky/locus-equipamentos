"""
Services de `apps.maintenance` — fundação da próxima etapa da Fase 2
(decisões 1-10 sobre a proposta de 26/08/2026, aprovadas em 27/08/2026).
Único caminho suportado para abrir/concluir/cancelar `Maintenance` e para
registrar/cancelar `Cleaning` — nunca `Maintenance.objects.create()`/
`.save()`/`Cleaning.objects.create()` direto em view/form, mesma
disciplina de `apps.operations.services.create_movement()`.

=============================================================================
MATRIZ 1 — Status da Maintenance (estado anterior → abertura → durante →
fechamento → estado final)
=============================================================================

Precondição de abertura SEM `departure_movement` (manutenção em campo, o
próprio `open_maintenance()` decide mudar o status): `Equipment.status`
precisa estar em {DISPONIVEL, EM_OPERACAO} — MESMA regra de precondição já
usada por `ENVIO_MANUTENCAO` em `apps.operations.services._TRANSITION_RULES`,
por consistência (não inventa um terceiro conjunto de status válidos).

Precondição de abertura COM `departure_movement`: nenhuma precondição de
status "de entrada" no sentido de `_OPEN_WITHOUT_MOVEMENT_STATUSES` — o
`Movement` ENVIO_MANUTENCAO já validou e já mudou o status antes;
`Maintenance` só registra o vínculo. Mas (endurecido em 27/08/2026, ver
"AUDITORIA DE VÍNCULOS" no fim deste docstring) `open_maintenance()` EXIGE
`equipment.status == MANUTENCAO` no momento da abertura quando
`departure_movement` é informado — coerência cronológica: se o status já
não é mais MANUTENCAO, a viagem física daquele Movement já foi encerrada
por um retorno, e vincular um `departure_movement` "velho" a uma ficha
nova seria uma manutenção sobre uma viagem que já terminou.

Linha A — Manutenção em ESTOQUE, sem Movement (conserto no próprio pátio):
    status anterior:  DISPONIVEL
    abertura:         open_maintenance(departure_movement=None) →
                       change_status(MANUTENCAO); status_before=DISPONIVEL
    durante:          MANUTENCAO
    fechamento:       close_maintenance() → restaura status_before
                       → change_status(DISPONIVEL)
    status final:     DISPONIVEL

Linha B — Manutenção em CLIENTE, sem Movement (conserto no local):
    status anterior:  EM_OPERACAO
    abertura:         change_status(MANUTENCAO); status_before=EM_OPERACAO
    durante:          MANUTENCAO
    fechamento:       restaura status_before → change_status(EM_OPERACAO)
    status final:     EM_OPERACAO

Linha C — Manutenção COM ENVIO_MANUTENCAO (o Movement já rodou antes):
    status anterior:  DISPONIVEL ou EM_OPERACAO (o que o Movement exigiu)
    Movement:         ENVIO_MANUTENCAO já mudou status → MANUTENCAO
    abertura:         open_maintenance(departure_movement=<mv>) → NENHUMA
                       chamada a change_status() (já está MANUTENCAO);
                       status_before é só um snapshot informativo (=
                       MANUTENCAO), NÃO é usado para restaurar nada
    durante:           MANUTENCAO
    fechamento SEM return_movement: NENHUMA mudança de status — o
                       equipamento continua fisicamente fora, então o
                       status continua refletindo isso corretamente
    fechamento COM return_movement (RETORNO_MANUTENCAO ou
                       RETORNO_ESTOQUE já registrado): Maintenance só
                       grava o vínculo — o Movement, não a Maintenance,
                       já tinha mudado o status para DISPONIVEL
    status final:      MANUTENCAO (se ainda não voltou) ou DISPONIVEL
                       (quando o Movement de retorno existir — dentro ou
                       fora do fechamento da Maintenance, tanto faz a
                       ordem)

Linha D — Manutenção SEM movimentação física: generalização de A/B acima
    (o que muda é só o valor concreto de status_before, DISPONIVEL numa
    manutenção de estoque ou EM_OPERACAO numa manutenção em cliente).

Linha E — CANCELAMENTO:
    E1 (aberta SEM departure_movement, cancelada): restaura status_before,
        MESMA lógica do fechamento normal — não faz sentido deixar o
        equipamento preso em MANUTENCAO por uma ficha aberta por engano.
    E2 (aberta COM departure_movement, cancelada): NENHUMA mudança de
        status — cancelar a ficha não desfaz o fato físico de que o
        equipamento já foi para a Location de manutenção; só um Movement
        de retorno resolve isso, como na linha C.

Regra de IDEMPOTÊNCIA/corrida (linhas A, B, D, E1 — sempre que
`departure_movement is None`, ou seja, sempre que ESTA Maintenance é quem
"dona" a mudança de status): o fechamento/cancelamento só tenta restaurar
se `Equipment.status` (lido sob `select_for_update()`) AINDA for
MANUTENCAO no momento do fechamento. Ver Matriz 2: é POSSÍVEL um Movement
externo (ex.: RETORNO_ESTOQUE) mudar o status "por fora" enquanto a
Maintenance segue aberta — nesse caso a restauração é pulada em silêncio
(o status já reflete a realidade física mais recente, mais confiável que
o snapshot). Implementado em `_restore_status_if_owned()`.

Estados impossíveis, todos bloqueados por constraint de banco + validação
de service (dupla camada, mesmo padrão do resto do projeto):
    - Duas Maintenance ABERTA E ATIVA para o mesmo equipamento ao mesmo
      tempo (UniqueConstraint condicional `is_active=True` + checagem em
      open_maintenance() — ajuste de 27/08/2026, decisão 4: uma ficha
      soft-deletada nunca bloqueia nada, ver docstring do model).
    - Maintenance CONCLUIDA sem `service_performed` (CheckConstraint).
    - `closed_at` presente com status ABERTA, ou ausente com status
      CONCLUIDA/CANCELADA (CheckConstraint).
    - `departure_movement`/`return_movement` reclamado por duas
      Maintenance diferentes (unique=True na FK + checagem em service).
    - Fechar/cancelar uma Maintenance que não está ABERTA.
    - INSTALACAO/RETIRADA/TRANSFERENCIA/ENVIO_MANUTENCAO enquanto existe
      Maintenance ABERTA E ATIVA para o equipamento — MESMO que
      `Equipment.status` sozinho já permitisse (ver Matriz 2, revisada em
      27/08/2026: isto agora É aplicado por `apps.operations.services`).

=============================================================================
MATRIZ 2 — Maintenance.status (ABERTA) × MovementType — REVISADA 27/08/2026
=============================================================================

Achado do fechamento anterior (27/08/2026, decisão 1): a versão original
desta matriz assumia que as regras de `Equipment.status` já existentes em
`_TRANSITION_RULES` eram suficientes para bloquear os tipos incompatíveis
— MAS isso só vale enquanto `Equipment.status` continuar MANUTENCAO. Um
Movement como RETORNO_ESTOQUE pode trazer o status de volta a DISPONIVEL
"por fora" (ver regra de idempotência acima) SEM fechar a Maintenance —
nesse instante, `INSTALACAO` (que só exige DISPONIVEL) voltaria a passar
pela checagem de status antiga, mesmo com uma ficha técnica ainda aberta.
Corrigido: `apps.operations.services._validate_transition()` agora tem
uma checagem ADICIONAL, explícita, de "existe Maintenance ABERTA E ATIVA
para este equipamento?" — não apenas o status. Ver a seção "Arquitetura
de dependência" abaixo para como isso foi implementado sem inverter a
direção de dependência entre os dois apps.

    MovementType         | precondição de status (já existente)  | bloqueado por Maintenance ABERTA? | efeito final
    ----------------------|-----------------------------------------|--------------------------------------|--------------------------------
    INSTALACAO            | DISPONIVEL                               | SIM (checagem nova)                   | sempre bloqueado com Maintenance aberta, mesmo se status permitisse
    RETIRADA               | EM_OPERACAO                              | SIM (checagem nova)                   | idem
    TRANSFERENCIA          | EM_OPERACAO                              | SIM (checagem nova)                   | idem
    ENVIO_MANUTENCAO       | DISPONIVEL ou EM_OPERACAO                | SIM (checagem nova)                   | idem — evita reenviar/duplicar
    RETORNO_ESTOQUE        | EM_OPERACAO ou MANUTENCAO                | não                                    | permitido sempre que o status já permitir — traz o equipamento de volta mesmo com a ficha ainda aberta
    RETORNO_MANUTENCAO     | MANUTENCAO                                | não                                    | idem — caminho natural de retorno
    OUTRO                  | nenhuma                                   | não                                    | permitido sempre — evento só anotado, nunca muda status

RETORNO_ESTOQUE/RETORNO_MANUTENCAO continuam DELIBERADAMENTE fora do
bloqueio — são exatamente os fatos físicos que trazem o equipamento de
volta; bloqueá-los prenderia o equipamento fisicamente disponível atrás
de uma ficha de papelada ainda aberta, o oposto do que a decisão 1 pediu
("fatos físicos necessários para trazer o equipamento de volta continuam
possíveis"). OUTRO nunca é bloqueado (evento apenas anotado).

Arquitetura de dependência (decisão 2, 27/08/2026): a checagem em
`apps.operations.services._validate_transition()` usa um IMPORT LOCAL
(dentro da função, não no topo do módulo) de
`apps.maintenance.services.has_open_maintenance` — deliberado, não uma
gambiarra. Hoje isso NÃO forma um ciclo real (nada em `apps.maintenance`
importa `apps.operations.services`), mas um import de módulo faria
`apps.operations` — camada mais antiga/mais baixa, existe desde a Fase 1
— declarar em tempo de import uma dependência de `apps.maintenance` —
camada introduzida depois, mais alta. Isso inverteria a direção de
dependência do projeto (domínios "de baixo" não devem conhecer, em
import-time, domínios "de cima" que os consomem) e criaria risco real de
ciclo assim que `apps.maintenance` precisar de algo de
`apps.operations.services` no futuro (bem plausível). O import local
resolve isso sem custo: adiado para o momento da chamada, dentro da MESMA
transação/lock já em vigor (ver Matriz de locking abaixo), e o contrato
exposto por `has_open_maintenance()` é só um predicado booleano — `apps.operations`
não precisa conhecer `MaintenanceStatus`, `is_active` nem qualquer outro
detalhe interno de `Maintenance`.

=============================================================================
MATRIZ DE LOCKING — concorrência entre open_maintenance() e create_movement()
=============================================================================

Os dois já bloqueavam `Equipment` via `select_for_update()` como primeira
operação de banco, antes de qualquer leitura/escrita de
`Maintenance`/`Movement` — isso continua valendo e é o que torna a
checagem nova segura contra corrida, sem precisar de nenhum lock
adicional:

    - `open_maintenance()`: lock em Equipment → checa Maintenance ABERTA
      existente → (grava Maintenance).
    - `create_movement()` → `_validate_transition()`: lock em Equipment
      (já feito antes de chamar `_validate_transition()`) → checa
      Maintenance ABERTA existente (`has_open_maintenance()`) → (grava
      Movement).

Os dois seguem a MESMA ordem (Equipment primeiro, único lock tomado por
qualquer um dos dois) — sem risco de deadlock (nunca há duas transações
esperando lock uma da outra em ordem invertida) e sem janela de corrida:
como as duas transações disputam o MESMO lock de linha antes de ler
`Maintenance`, PostgreSQL serializa as duas por completo — quem obtém o
lock primeiro TERMINA (commit/rollback) antes da outra sequer conseguir
ler o estado de `Maintenance`. Não existe "checa que não existe
Maintenance → a outra abre Maintenance → o Movement prossegue" (decisão
3): as duas leituras cruzadas (`create_movement` lê `Maintenance`;
`open_maintenance` efetivamente decide com base no `Equipment` já
travado) só acontecem depois que uma das duas transações já garantiu
exclusividade sobre o único recurso compartilhado que importa. Teste de
concorrência real: `apps.maintenance.tests.test_maintenance_movement_concurrency`.

=============================================================================
MATRIZ 3 — Estratégia de restauração de status (decisão 3)
=============================================================================

Resumo executivo (o detalhe está na Matriz 1 + docstring de
`_restore_status_if_owned()`): `Maintenance.status_before` é um snapshot
DETERMINÍSTICO de `Equipment.status`, capturado automaticamente por
`open_maintenance()` no instante da abertura — nunca uma adivinhação tipo
"provavelmente DISPONIVEL ou EM_OPERACAO" no fechamento. A restauração só
acontece quando a própria Maintenance foi quem mudou o status (sem
`departure_movement`), e só se o status ainda não tiver sido alterado por
fora entre a abertura e o fechamento.

=============================================================================
DECISÃO 9 — `next_due_at`: pertence ao evento, não a uma agenda separada
=============================================================================

`Maintenance.next_due_at`/`Cleaning.next_due_at` são campos NULOS,
puramente informativos: "a última data planejada conhecida", preenchidos
opcionalmente no fechamento (Maintenance) ou no registro (Cleaning). Não
existe, e não é criado aqui, nenhum motor de recorrência — nenhum
intervalo/frequência, nenhum job, nenhum agendamento automático.

Por que isso NÃO conflita "histórico" com "agenda" a ponto de exigir um
model separado agora: o campo não carrega NENHUM comportamento — não
dispara nada, não é lido por nenhum processo automático nesta etapa
(dashboard/calendário/notificações estão explicitamente fora de escopo).
É só o último plano conhecido, e "qual é a próxima manutenção prevista de
um equipamento" é sempre uma leitura (a Maintenance/Cleaning mais recente
com `next_due_at` preenchido), nunca uma escrita coordenada por outra
tabela.

Se uma fase futura precisar de recorrência de verdade (regra tipo "a cada
90 dias"), a solução correta é um model novo e separado
(`MaintenanceSchedule`/regra de recorrência) — não forçar `Maintenance` a
ser simultaneamente histórico E agenda. Migrar para esse desenho futuro
não exige alterar o campo atual: ele continua fazendo sentido como "o
plano mais recente conhecido", ou é aposentado numa migration futura, sem
conflito com o que existe hoje. Decisão registrada aqui porque envolve
os dois models desta fundação — não é uma mudança estrutural em nenhum
dos dois, por isso não bloqueou a implementação.

=============================================================================
AUDITORIA DE VÍNCULOS Maintenance/Cleaning × Movement (27/08/2026)
=============================================================================

Fortalecimento das validações de `departure_movement`/`return_movement`/
`Cleaning.movement` — nenhuma delas confiava em nada além do
`OneToOneField`/`ForeignKey` para garantir integridade referencial; o
resto (equipamento certo, tipo certo, não reclamado por outra ficha,
coerência cronológica) sempre foi responsabilidade do service, e esta
auditoria adiciona o que faltava sem duplicar nenhum dado.

`_validate_departure_movement()` — checagens, nesta ordem:
    1. `movement.pk is not None` — precisa ser um Movement JÁ REGISTRADO
       (nunca uma instância em memória não salva).
    2. `movement.equipment_id == equipment.pk`.
    3. `movement.movement_type == ENVIO_MANUTENCAO`.
    4. Não reclamado por outra `Maintenance` (`OneToOneField` já garante
       isso no banco — checagem aqui é só para uma mensagem clara, dupla
       camada de sempre).
    5. NOVO: `equipment.status == MANUTENCAO` — coerência cronológica
       (ver acima na Matriz 1).

`_validate_return_movement()` — agora recebe também `maintenance` (não só
`movement`/`equipment`), checagens nesta ordem:
    1. `movement.pk is not None`.
    2. `movement.equipment_id == equipment.pk`.
    3. `movement.movement_type in (RETORNO_MANUTENCAO, RETORNO_ESTOQUE)`
       — os DOIS continuam aceitos, DELIBERADAMENTE (não restrito só a
       RETORNO_MANUTENCAO): os dois são formas fisicamente legítimas de
       trazer o equipamento de volta — `_TRANSITION_RULES`
       (`apps.operations.services`) já aceita MANUTENCAO como status de
       origem para os dois, e nenhuma regra de negócio deste projeto
       distingue "retorno de manutenção" de "retorno ao estoque vindo de
       manutenção" além do rótulo. Restringir a só RETORNO_MANUTENCAO
       bloquearia um caso real: equipamento consertado, mas o time decide
       levá-lo direto ao estoque em vez de devolvê-lo à mesma
       origem — já coberto pela Matriz 2 desde 27/08/2026 (checagem 1).
    4. Não reclamado por outra `Maintenance` (mesma dupla camada).
    5. NOVO: `movement.created_at > maintenance.created_at` — o retorno
       precisa ter acontecido DEPOIS da abertura da ficha (um Movement
       "do passado" não pode ser o retorno de uma ficha aberta depois
       dele).
    6. NOVO, só quando `departure_movement` existe:
       `movement.created_at > departure_movement.created_at` — o retorno
       precisa vir depois do envio, nunca antes/simultâneo.
    7. NOVO: se `departure_movement` é `None` E
       `movement.movement_type == RETORNO_MANUTENCAO`, REJEITADO — "retorno
       da manutenção" pressupõe um envio físico que, para esta ficha (sem
       `departure_movement`, manutenção em campo), nunca aconteceu.
       `RETORNO_ESTOQUE` continua aceito nesse caso (não presume nenhuma
       viagem específica, só "foi levado ao estoque"), então a ficha pode
       legitimamente terminar com o equipamento indo para o estoque
       mesmo tendo sido uma manutenção só em campo.

Cenário conceitualmente impossível (item 3 da revisão, "return_movement
não pode existir sozinho"): confirmado que a única forma de
`return_movement` existir sem `departure_movement` de maneira INCOERENTE
era exatamente a checagem 7 acima (RETORNO_MANUTENCAO sem envio
correspondente) — agora bloqueada. `RETORNO_ESTOQUE` sem
`departure_movement` continua válido porque é uma combinação real e
coerente (manutenção em campo que termina com o equipamento indo ao
estoque).

`status_before` só é usado para restauração quando `departure_movement is
None` (`_restore_status_if_owned()`, inalterado nesta auditoria — já
garantia isso desde a implementação original).

`Cleaning.movement` — SEM restrição de tipo, deliberadamente: não existe
regra de negócio que torne algum `MovementType` incompatível com uma
higienização (higienizar antes de instalar, ao retirar, ao transferir, ao
voltar ao estoque ou da manutenção, ou até um `OUTRO` anotado — todos são
combinações reais). Só o vínculo de equipamento é obrigatório quando
`movement` é informado — mantido exatamente como estava.

CONCORRÊNCIA — por que NENHUM lock novo em `Movement` foi necessário:
`departure_movement`/`return_movement` são sempre validados como
pertencentes ao MESMO `equipment` que já está sob `select_for_update()`
(primeiro lock, sempre) em `open_maintenance()`/`close_maintenance()`.
Como um `Movement` só pode pertencer a UM equipamento, a ÚNICA forma de
duas transações disputarem o mesmo `departure_movement`/`return_movement`
é as duas operarem sobre o MESMO `equipment` — e nesse caso as duas já
disputam o MESMO lock de `Equipment` primeiro. Sob READ COMMITTED
(padrão do Django/PostgreSQL), a transação que perde a corrida pelo lock
de `Equipment` só executa sua leitura de `Maintenance`
(`filter(departure_movement=...)`/`filter(return_movement=...)`) DEPOIS
de a vencedora já ter comitado — vendo o vínculo já reivindicado e
falhando com a mensagem clara, nunca com uma condição de corrida. Para
`return_movement` a garantia é ainda mais forte: só pode existir UMA
`Maintenance` `ABERTA` por equipamento (`UniqueConstraint`), então nunca
há duas fichas do mesmo equipamento disputando fechamento ao mesmo tempo.

Mesmo com essa garantia por ordenação de lock, `open_maintenance()`/
`close_maintenance()` agora capturam `IntegrityError` ao salvar e
convertem para `ValueError` com mensagem de domínio — defesa adicional
explícita (não porque a corrida analisada acima seja alcançável hoje, mas
para nunca deixar um `IntegrityError` cru vazar até uma view futura, por
exemplo se um caminho novo de chamada for adicionado sem preservar a
mesma ordem de locks).

=============================================================================
"""

from dataclasses import dataclass
from datetime import date, datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.equipment.models import Condition, Equipment, Status
from apps.equipment.services import change_condition, change_status
from apps.maintenance.models import Cleaning, Maintenance, MaintenanceStatus, MaintenanceType
from apps.operations.models import Movement, MovementType

# Mesmo conjunto de status válido que `ENVIO_MANUTENCAO` já exige em
# `apps.operations.services._TRANSITION_RULES` — reaproveitado aqui por
# consistência, não redefinido do zero.
_OPEN_WITHOUT_MOVEMENT_STATUSES = (Status.DISPONIVEL, Status.EM_OPERACAO)

# Tipos de Movement aceitos como `return_movement` — RETORNO_MANUTENCAO é
# o caminho "normal", mas RETORNO_ESTOQUE também é uma forma legítima de
# trazer o equipamento de volta (ver Matriz 2: os dois aceitam MANUTENCAO
# como precondição de status em `_TRANSITION_RULES`).
_RETURN_MOVEMENT_TYPES = (MovementType.RETORNO_MANUTENCAO, MovementType.RETORNO_ESTOQUE)


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------


@dataclass
class NewMaintenanceData:
    equipment_id: int
    maintenance_type: str
    responsible: User
    created_by: User
    diagnosis: str = ""
    notes: str = ""
    departure_movement: Movement | None = None


def has_open_maintenance(equipment: Equipment) -> bool:
    """
    Predicado público — só uma `Maintenance` ATIVA (`is_active=True`) E
    `ABERTA` conta como "aberta" (ajuste de 27/08/2026, decisão 4: uma
    ficha soft-deletada nunca bloqueia nada; mesma condição da
    `UniqueConstraint` do model).

    Ponto de integração único e deliberadamente MÍNIMO para
    `apps.operations.services._validate_transition()` (Matriz 2,
    revisada em 27/08/2026, decisão 1): `apps.operations` chama esta
    função via IMPORT LOCAL (dentro da função, não no topo do módulo) —
    ver a seção "Arquitetura de dependência" no topo deste arquivo para a
    justificativa completa. `apps.operations` só precisa deste booleano;
    nunca importa `Maintenance`/`MaintenanceStatus` diretamente.

    Chamar isto FORA de uma transação que já tenha `Equipment` travado
    (`select_for_update()`) não é seguro contra corrida — ver a Matriz de
    locking no topo deste arquivo. Todos os chamadores atuais
    (`open_maintenance()`, `apps.operations.services._validate_transition()`)
    já garantem isso.
    """
    return Maintenance.objects.filter(equipment=equipment, status=MaintenanceStatus.ABERTA, is_active=True).exists()


def _validate_departure_movement(*, movement: Movement, equipment: Equipment) -> None:
    """Auditoria de 27/08/2026 — ver "AUDITORIA DE VÍNCULOS" no topo deste módulo para a lista completa e a ordem."""
    if movement.pk is None:
        raise ValueError("A movimentação de envio informada precisa já estar registrada.")
    if movement.equipment_id != equipment.pk:
        raise ValueError("A movimentação de envio informada não pertence a este equipamento.")
    if movement.movement_type != MovementType.ENVIO_MANUTENCAO:
        raise ValueError("A movimentação de envio precisa ser do tipo 'Envio para manutenção'.")
    if Maintenance.objects.filter(departure_movement=movement).exists():
        raise ValueError("Esta movimentação de envio já está vinculada a outra manutenção.")
    if equipment.status != Status.MANUTENCAO:
        # Coerência cronológica: se o status já não é mais MANUTENCAO, a
        # viagem física deste Movement já foi encerrada por um retorno —
        # vincular um departure_movement "velho" a uma ficha nova seria
        # uma manutenção sobre uma viagem que já terminou.
        raise ValueError(
            "Esta movimentação de envio não representa mais uma manutenção em andamento — o equipamento já "
            f"retornou (status atual: '{equipment.get_status_display()}'). Verifique se é o Movement correto."
        )


@transaction.atomic
def open_maintenance(data: NewMaintenanceData) -> Maintenance:
    """
    Único caminho suportado para abrir uma `Maintenance`. Ver Matriz 1
    (topo deste módulo) para o comportamento completo de status —
    resumo: sem `departure_movement`, esta função MUDA
    `Equipment.status` para MANUTENCAO (via `change_status()`, nunca
    atribuição direta) e grava `status_before` para permitir restauração
    determinística no fechamento; com `departure_movement`, o status já
    foi alterado pelo Movement, e esta função não toca nele.
    """
    if data.maintenance_type not in MaintenanceType.values:
        raise ValueError(f"Tipo de manutenção inválido: {data.maintenance_type!r}.")

    equipment = Equipment.objects.select_for_update().get(pk=data.equipment_id)

    # Dupla camada com a UniqueConstraint condicional do model (mesma
    # condição — status=ABERTA E is_active=True) — mensagem clara em vez
    # de depender só do IntegrityError, mesmo padrão de
    # `_validate_location_client_matches_type()`.
    if has_open_maintenance(equipment):
        raise ValueError("Já existe uma manutenção aberta para este equipamento.")

    status_before = equipment.status

    if data.departure_movement is not None:
        _validate_departure_movement(movement=data.departure_movement, equipment=equipment)
        # Status já foi alterado pelo Movement — Maintenance não mexe aqui
        # (Matriz 1, linha C).
    else:
        if equipment.status not in _OPEN_WITHOUT_MOVEMENT_STATUSES:
            allowed = "/".join(Status(s).label for s in _OPEN_WITHOUT_MOVEMENT_STATUSES)
            raise ValueError(
                "Só é possível abrir manutenção sem movimentação associada para um equipamento com status "
                f"{allowed}. Status atual: {equipment.get_status_display()}."
            )
        change_status(
            equipment=equipment,
            new_status=Status.MANUTENCAO,
            reason=f"Manutenção aberta sem movimentação associada (responsável: {data.responsible}).",
            changed_by=data.created_by,
        )

    maintenance = Maintenance(
        equipment=equipment,
        maintenance_type=data.maintenance_type,
        status=MaintenanceStatus.ABERTA,
        diagnosis=data.diagnosis,
        condition_before=equipment.condition,
        status_before=status_before,
        departure_movement=data.departure_movement,
        responsible=data.responsible,
        notes=data.notes,
        created_by=data.created_by,
    )
    maintenance._change_reason = "Manutenção aberta."
    try:
        maintenance.save()
    except IntegrityError as exc:
        # Defesa adicional (ver "AUDITORIA DE VÍNCULOS" no topo do módulo)
        # — a ordenação de locks já deveria impedir isto na prática; isto
        # é só para nunca deixar um IntegrityError cru vazar até uma view
        # futura caso um caminho de chamada novo não preserve a mesma
        # ordem de locks.
        raise ValueError(
            "Não foi possível registrar esta manutenção — verifique se já não existe outra manutenção aberta "
            "para este equipamento ou se a movimentação de envio já não foi reivindicada por outra ficha."
        ) from exc
    return maintenance


def _validate_return_movement(*, movement: Movement, equipment: Equipment, maintenance: Maintenance) -> None:
    """Auditoria de 27/08/2026 — ver "AUDITORIA DE VÍNCULOS" no topo deste módulo para a lista completa e a ordem."""
    if movement.pk is None:
        raise ValueError("A movimentação de retorno informada precisa já estar registrada.")
    if movement.equipment_id != equipment.pk:
        raise ValueError("A movimentação de retorno informada não pertence a este equipamento.")
    if movement.movement_type not in _RETURN_MOVEMENT_TYPES:
        raise ValueError(
            "A movimentação de retorno precisa ser do tipo 'Retorno da manutenção' ou 'Retorno ao estoque'."
        )
    if Maintenance.objects.filter(return_movement=movement).exists():
        raise ValueError("Esta movimentação de retorno já está vinculada a outra manutenção.")
    if movement.created_at <= maintenance.created_at:
        # Coerência cronológica: o retorno precisa ter acontecido DEPOIS da
        # abertura desta ficha — um Movement "do passado" não pode ser o
        # retorno de uma manutenção aberta depois dele.
        raise ValueError("A movimentação de retorno é anterior à abertura desta manutenção.")
    if maintenance.departure_movement_id is not None:
        if movement.created_at <= maintenance.departure_movement.created_at:
            raise ValueError("A movimentação de retorno é anterior (ou simultânea) à movimentação de envio.")
    elif movement.movement_type == MovementType.RETORNO_MANUTENCAO:
        # Cenário conceitualmente impossível (revisão de 27/08/2026): sem
        # `departure_movement`, esta ficha nunca registrou um envio físico
        # — "retorno da manutenção" pressupõe exatamente esse envio.
        # RETORNO_ESTOQUE continua aceito neste caso (não presume nenhuma
        # viagem específica).
        raise ValueError(
            "Esta manutenção não tem movimentação de envio associada — 'Retorno da manutenção' pressupõe um "
            "envio físico prévio. Use 'Retorno ao estoque' se o equipamento foi levado ao estoque diretamente."
        )


def _restore_status_if_owned(*, maintenance: Maintenance, equipment: Equipment, changed_by: User, event_label: str) -> None:
    """
    Só restaura `Equipment.status` quando ESTA Maintenance foi quem o
    alterou na abertura (`departure_movement is None`) — nunca quando a
    mudança veio de um Movement (decisão 3: sem restauração "provável",
    só snapshot determinístico via `status_before`).

    Idempotente/seguro contra corrida (Matriz 2): se o status já tiver
    sido alterado por fora enquanto a manutenção seguia aberta (ex.: um
    RETORNO_ESTOQUE registrado diretamente), esta função não faz nada —
    o status atual já reflete a realidade física mais recente, mais
    confiável que o snapshot da abertura.
    """
    if maintenance.departure_movement_id is not None:
        return
    if not maintenance.status_before:
        return
    if equipment.status != Status.MANUTENCAO:
        return
    if equipment.status == maintenance.status_before:
        return
    change_status(
        equipment=equipment,
        new_status=maintenance.status_before,
        reason=f"Restaurado automaticamente ao fechar manutenção ({event_label}), sem movimentação associada.",
        changed_by=changed_by,
    )


@dataclass
class CloseMaintenanceData:
    service_performed: str
    closed_by: User
    condition_after: str = ""
    return_movement: Movement | None = None


@transaction.atomic
def close_maintenance(*, maintenance: Maintenance, data: CloseMaintenanceData) -> Maintenance:
    """Único caminho suportado para concluir uma `Maintenance` ABERTA. Ver Matriz 1, linhas A/B/C."""
    maintenance = Maintenance.objects.select_for_update().get(pk=maintenance.pk)
    if maintenance.status != MaintenanceStatus.ABERTA:
        raise ValueError("Só é possível concluir uma manutenção que esteja aberta.")
    if not data.service_performed.strip():
        raise ValueError("Conclusão de manutenção exige o registro do serviço executado.")

    equipment = Equipment.objects.select_for_update().get(pk=maintenance.equipment_id)

    if data.return_movement is not None:
        _validate_return_movement(movement=data.return_movement, equipment=equipment, maintenance=maintenance)
        maintenance.return_movement = data.return_movement

    if data.condition_after:
        if data.condition_after not in Condition.values:
            raise ValueError(f"Condição inválida: {data.condition_after!r}.")
        if data.condition_after != equipment.condition:
            change_condition(
                equipment=equipment,
                new_condition=data.condition_after,
                reason=f"Registrado ao concluir manutenção #{maintenance.pk}.",
                changed_by=data.closed_by,
            )

    _restore_status_if_owned(maintenance=maintenance, equipment=equipment, changed_by=data.closed_by, event_label="concluída")

    maintenance.status = MaintenanceStatus.CONCLUIDA
    maintenance.service_performed = data.service_performed
    maintenance.condition_after = data.condition_after
    maintenance.closed_at = timezone.now()
    maintenance._change_reason = "Manutenção concluída."
    try:
        maintenance.save()
    except IntegrityError as exc:
        # Mesma defesa adicional de `open_maintenance()` — ver "AUDITORIA
        # DE VÍNCULOS" no topo do módulo.
        raise ValueError(
            "Não foi possível concluir esta manutenção — verifique se a movimentação de retorno já não foi "
            "reivindicada por outra ficha."
        ) from exc
    return maintenance


@transaction.atomic
def cancel_maintenance(*, maintenance: Maintenance, cancelled_by: User, reason: str = "") -> Maintenance:
    """Único caminho suportado para cancelar uma `Maintenance` ABERTA (aberta por engano etc). Ver Matriz 1, linha E."""
    maintenance = Maintenance.objects.select_for_update().get(pk=maintenance.pk)
    if maintenance.status != MaintenanceStatus.ABERTA:
        raise ValueError("Só é possível cancelar uma manutenção que esteja aberta.")

    equipment = Equipment.objects.select_for_update().get(pk=maintenance.equipment_id)
    _restore_status_if_owned(maintenance=maintenance, equipment=equipment, changed_by=cancelled_by, event_label="cancelada")

    maintenance.status = MaintenanceStatus.CANCELADA
    maintenance.closed_at = timezone.now()
    if reason.strip():
        maintenance.notes = f"{maintenance.notes}\n\nCancelamento: {reason.strip()}".strip()
    maintenance._change_reason = "Manutenção cancelada."
    maintenance.save()
    return maintenance


# ---------------------------------------------------------------------------
# Cleaning — evento atômico (decisão 5), sem ciclo aberta/concluída.
# ---------------------------------------------------------------------------


@dataclass
class NewCleaningData:
    equipment_id: int
    responsible: User
    created_by: User
    performed_at: datetime | None = None
    notes: str = ""
    next_due_at: date | None = None
    movement: Movement | None = None


@transaction.atomic
def create_cleaning(data: NewCleaningData) -> Cleaning:
    """
    Único caminho suportado para registrar uma `Cleaning`. Evento
    imutável após criado (decisão 10) — nunca atualizado depois; um
    registro incorreto é corrigido com `cancel_cleaning()` (is_active =
    False) seguido de um novo registro correto.
    """
    equipment = Equipment.objects.get(pk=data.equipment_id)

    if data.movement is not None and data.movement.equipment_id != equipment.pk:
        # Único vínculo exigido (auditoria de 27/08/2026, ver "AUDITORIA DE
        # VÍNCULOS" no topo do módulo): o Movement precisa pertencer ao
        # MESMO equipamento. Nenhuma restrição de MovementType — não existe
        # regra de domínio que torne algum tipo incompatível com uma
        # higienização.
        raise ValueError("A movimentação informada não pertence a este equipamento.")

    return Cleaning.objects.create(
        equipment=equipment,
        performed_at=data.performed_at or timezone.now(),
        responsible=data.responsible,
        notes=data.notes,
        next_due_at=data.next_due_at,
        movement=data.movement,
        created_by=data.created_by,
    )


def cancel_cleaning(*, cleaning: Cleaning) -> Cleaning:
    """
    Única forma suportada de "desfazer" um registro de higienização —
    nunca edição direta dos campos do evento em si (decisão 10: "evitando
    UPDATE silencioso após registrado"). Só alterna `is_active`.
    """
    if not cleaning.is_active:
        raise ValueError("Este registro de higienização já está cancelado.")
    cleaning.is_active = False
    cleaning.save(update_fields=["is_active", "updated_at"])
    return cleaning


# ---------------------------------------------------------------------------
# Leitura — ficha do equipamento (UI, Fase 2, 27/08/2026)
# ---------------------------------------------------------------------------


def get_equipment_maintenance_summary(equipment: Equipment, limit: int = 5) -> dict:
    """
    Resumo COMPACTO para a seção "Manutenção e higienização" da ficha
    autenticada do equipamento — deliberadamente distinto da timeline
    unificada completa (`apps.equipment.services.get_equipment_history_timeline()`):
    aqui só os eventos mais recentes de CADA tipo, com link direto para o
    detalhe, não a timeline inteira. Nenhuma escrita, nenhuma regra de
    domínio — só leitura.

    Duas queries fixas (uma por model), sem N+1: `limit` é aplicado no
    banco (`[:limit]`), nunca em Python sobre uma queryset maior.
    """
    open_maintenance_qs = Maintenance.objects.filter(
        equipment=equipment, status=MaintenanceStatus.ABERTA, is_active=True
    ).select_related("responsible").first()

    recent_maintenances = list(
        Maintenance.objects.filter(equipment=equipment, is_active=True)
        .select_related("responsible")
        .order_by("-created_at")[:limit]
    )
    recent_cleanings = list(
        Cleaning.objects.filter(equipment=equipment, is_active=True)
        .select_related("responsible")
        .order_by("-performed_at")[:limit]
    )

    return {
        "open_maintenance": open_maintenance_qs,
        "recent_maintenances": recent_maintenances,
        "recent_cleanings": recent_cleanings,
    }
