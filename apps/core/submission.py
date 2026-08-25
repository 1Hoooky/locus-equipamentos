"""
Proteção reutilizável contra reenvio de formulário (double-submit) —
generalização pedida no 2º reteste manual e endurecida no 3º.

Histórico do mecanismo:

- 2º reteste: a proteção criada para o cadastro de cliente (token de
  sessão de uso único) foi extraída para cá e aplicada também a
  `Location` e `Movement`.
- 3º reteste: o consumo do token SÓ na sessão tinha uma race condition —
  dois POSTs quase simultâneos (Enter segurado) carregam a mesma sessão
  no início de cada request, ambos veem o token na própria cópia em
  memória, ambos passam na checagem e ambos criam; o `del` de um não
  afeta a cópia já carregada do outro (a sessão só é persistida no fim do
  request, e a última escrita vence). Sessão Django não fornece
  read-modify-write atômico entre requests, então a autoridade do consumo
  foi movida para o banco: `ConsumedSubmissionToken` (apps.core.models),
  cujo índice UNIQUE garante que, de N inserts concorrentes do mesmo
  token, exatamente UM sucede — os demais recebem IntegrityError e são
  tratados como reenvio.

Como funciona (server-side, nunca só JS desabilitando botão):

1. O GET que exibe o formulário chama `issue()` — grava um token novo na
   sessão e o devolve para o template pôr num `<input type="hidden"
   name="submission_token">`.
2. O POST de criação chama `consume_if_valid()` ANTES de chamar o
   service:
   a. compara o token do POST com o da sessão (vínculo com a sessão do
      usuário — um token forjado ou de outra sessão não passa);
   b. INSERE o token em `ConsumedSubmissionToken` — é o insert, protegido
      pelo UNIQUE, que decide a corrida: a primeira requisição a
      conseguir inserir prossegue; qualquer outra com o mesmo token
      (Enter repetido, duplo clique, requisição concorrente) recebe
      IntegrityError e é tratada como reenvio, sem criar nada.
3. Depois de um sucesso, a view faz POST → Redirect → GET normalmente; o
   próximo GET emite um token novo.
4. Um POST que falha validação/regra de negócio chama `issue()` de novo
   ao re-renderizar, para a tentativa de correção seguinte não ser
   barrada como reenvio.

`scope` isola formulários diferentes na mesma sessão (ex.: criar cliente
numa aba e unidade em outra não invalida um ao outro). Para formulários
por objeto (movimentação de UM equipamento), inclua o identificador no
scope — ex.: `SubmissionGuard(f"movement_create:{patrimonio}")`.
"""

import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import ConsumedSubmissionToken

# Depois de quanto tempo uma linha de consumo pode ser expurgada — muito
# maior que a vida útil real de qualquer formulário aberto (o token da
# sessão é substituído a cada GET do formulário).
_CONSUMED_TOKEN_TTL = timedelta(days=7)


class SubmissionGuard:
    def __init__(self, scope: str):
        self.scope = scope
        self.session_key = f"submission_token:{scope}"

    def issue(self, request) -> str:
        """Emite (e guarda na sessão) um token novo de uso único, substituindo qualquer anterior deste scope."""
        # Expurgo oportunista do registro de consumos antigos — mantém a
        # tabela pequena sem exigir tarefa agendada. DELETE indexado por
        # created_at? Não: filtro por created_at sem índice dedicado, mas
        # a tabela só contém tokens JÁ CONSUMIDOS (um por criação bem
        # sucedida), então o volume é o de objetos criados na última
        # semana — pequeno por construção.
        ConsumedSubmissionToken.objects.filter(created_at__lt=timezone.now() - _CONSUMED_TOKEN_TTL).delete()
        token = uuid.uuid4().hex
        request.session[self.session_key] = token
        return token

    def pending(self, request) -> str:
        """
        Token já pendente na sessão para este scope, ou um novo emitido na
        hora se não houver (ex.: sessão expirou no meio do preenchimento).
        Para re-renderizações que NÃO consomem o token — ex.: a ação
        "Consultar CNPJ" do formulário de cliente.
        """
        token = request.session.get(self.session_key)
        if not token:
            token = self.issue(request)
        return token

    def consume_if_valid(self, request) -> bool:
        """
        Retorna True se — e somente se — ESTA requisição é a única a
        consumir o token enviado; o chamador pode então prosseguir com a
        criação. Qualquer outro caso retorna False sem criar nada: token
        ausente/forjado/de outra sessão (checagem contra a sessão) ou já
        consumido por uma requisição anterior OU CONCORRENTE (decidido
        pelo UNIQUE do banco, não pela sessão — ver docstring do módulo).
        """
        submitted = request.POST.get("submission_token", "")
        expected = request.session.get(self.session_key)
        if not expected or submitted != expected:
            return False

        try:
            # O savepoint (`transaction.atomic()`) torna o IntegrityError
            # recuperável mesmo se o chamador estiver dentro de uma
            # transação maior. Fora de transação (o caso das views de
            # criação), o INSERT comita imediatamente — a requisição
            # concorrente bloqueia no índice único até este commit e então
            # recebe o IntegrityError.
            with transaction.atomic():
                ConsumedSubmissionToken.objects.create(token=submitted, scope=self.scope)
        except IntegrityError:
            return False

        # Limpeza da sessão é só higiene (o banco já decidiu) — remove o
        # token para o formulário não continuar "armado" nesta sessão.
        del request.session[self.session_key]
        return True
