"""
Proteção reutilizável contra reenvio de formulário (double-submit) —
generalização pedida no 2º reteste manual da Fase 2: a proteção criada
para o cadastro de cliente (token de sessão de uso único, mesmo padrão de
`EquipmentBatchConfirmView`) valia só para aquela view; o mesmo bug
continuava reproduzível em "Nova unidade" (Enter repetido criava várias
`Location` idênticas) e, por simetria, em "Registrar movimentação".

Como funciona (server-side, nunca só JS desabilitando botão):

1. O GET que exibe o formulário chama `issue()` — grava um token novo na
   sessão e o devolve para o template pôr num `<input type="hidden"
   name="submission_token">`.
2. O POST de criação chama `consume_if_valid()` ANTES de chamar o
   service: compara o token do POST com o da sessão e, se bater, o
   REMOVE da sessão na mesma chamada (uso único). Um segundo POST com o
   mesmo token (Enter repetido, duplo clique, "voltar" + reenviar) não
   encontra mais nada pendente e é tratado como reenvio — nada é criado.
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


class SubmissionGuard:
    def __init__(self, scope: str):
        self.session_key = f"submission_token:{scope}"

    def issue(self, request) -> str:
        """Emite (e guarda na sessão) um token novo de uso único, substituindo qualquer anterior deste scope."""
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
        Compara o token enviado no POST com o pendente na sessão. Se
        bater, CONSOME (remove da sessão) e retorna True — o chamador pode
        prosseguir com a criação. Qualquer outro caso (sem token na
        sessão, token divergente/forjado/antigo) retorna False sem mudar
        nada: o chamador trata como reenvio e não cria coisa alguma.
        """
        submitted = request.POST.get("submission_token", "")
        expected = request.session.get(self.session_key)
        if not expected or submitted != expected:
            return False
        del request.session[self.session_key]
        return True
