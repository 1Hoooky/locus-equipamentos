/**
 * Funil Kanban de oportunidades (CRM) — arraste real entre colunas
 * (decisão de produto, 11/09/2026: "Drag-and-drop real entre colunas").
 *
 * Vanilla JS com a API nativa de HTML5 Drag and Drop — sem lib nova
 * (mesma convenção do resto do projeto: nenhuma dependência JS além do
 * que já está em templates/base.html). htmx está carregado na página mas
 * não é usado aqui — a interação de arraste não é uma navegação/troca de
 * HTML parcial, é um evento de mouse nativo do navegador seguido de UM
 * fetch() JSON, então não se encaixa no modelo de hx-* do htmx.
 *
 * Único caminho de escrita: sempre `POST /crm/oportunidades/<pk>/etapa/`
 * (o MESMO endpoint do form "Mudar etapa" da ficha da oportunidade, ver
 * apps/crm/views.py OpportunityStageChangeView) — o cabeçalho
 * `X-Requested-With: XMLHttpRequest` é o único jeito deste script obter
 * JSON em vez de um redirect. O backend valida e aplica a MESMA regra de
 * negócio de sempre (apps.crm.services.change_opportunity_stage) — este
 * script nunca decide sozinho se um arraste é válido, só REAGE ao que o
 * backend responde (sucesso: move o card e atualiza os totais; erro:
 * mantém o card no lugar de origem e mostra o motivo).
 *
 * O DOM do card só é movido de coluna DEPOIS da confirmação do backend
 * (nunca otimista) — evita qualquer estado visualmente "à frente" do que
 * realmente foi salvo, incluindo o caso de duas abas/usuários mudando a
 * mesma oportunidade ao mesmo tempo (o backend serializa via
 * select_for_update(); quem perder a corrida recebe erro claro aqui).
 */
(function () {
  "use strict";

  var board = document.getElementById("kanban-board");
  if (!board) return;

  var csrfForm = document.getElementById("kanban-csrf-form");
  var csrfToken = csrfForm ? csrfForm.querySelector("input[name=csrfmiddlewaretoken]").value : "";
  var urlBase = board.getAttribute("data-change-stage-url-base") || ""; // .../oportunidades/0/etapa/
  var filtersQuery = board.getAttribute("data-filters-query") || "";

  var lossReasonsDataEl = document.getElementById("kanban-loss-reasons-data");
  var lossReasons = [];
  if (lossReasonsDataEl) {
    try {
      lossReasons = JSON.parse(lossReasonsDataEl.textContent) || [];
    } catch (e) {
      lossReasons = [];
    }
  }

  function stageChangeUrl(opportunityId) {
    return urlBase.replace("/0/etapa/", "/" + opportunityId + "/etapa/");
  }

  function showToast(message) {
    var existing = document.querySelector(".kanban-toast");
    if (existing) existing.remove();
    var toast = document.createElement("div");
    toast.className = "kanban-toast";
    toast.setAttribute("role", "alert");
    toast.textContent = message;
    document.body.appendChild(toast);
    window.setTimeout(function () {
      toast.remove();
    }, 5000);
  }

  function updateColumnSummary(summary) {
    if (!summary) return;
    var column = board.querySelector('.kanban-column[data-stage-id="' + summary.id + '"]');
    if (!column) return;
    var countEl = column.querySelector(".kanban-column-count");
    var totalEl = column.querySelector(".kanban-column-total");
    if (countEl) countEl.textContent = summary.count;
    if (totalEl) totalEl.textContent = summary.total_value_display;
  }

  function refreshEmptyState(dropZone) {
    var hasCards = dropZone.querySelector(".kanban-card") !== null;
    var emptyMsg = dropZone.querySelector(".kanban-column-empty");
    if (hasCards && emptyMsg) {
      emptyMsg.remove();
    } else if (!hasCards && !emptyMsg) {
      var p = document.createElement("p");
      p.className = "kanban-column-empty";
      p.textContent = "Nenhuma oportunidade nesta etapa.";
      dropZone.appendChild(p);
    }
  }

  // -------------------------------------------------------------------
  // Estado do arraste em curso — um único card por vez (nunca multi-seleção).
  // -------------------------------------------------------------------
  var draggingCard = null;

  board.addEventListener("dragstart", function (event) {
    var card = event.target.closest(".kanban-card");
    if (!card || card.getAttribute("draggable") !== "true") return;
    draggingCard = card;
    card.classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
    // Firefox exige setData para o drag funcionar de verdade.
    event.dataTransfer.setData("text/plain", card.getAttribute("data-opportunity-id") || "");
  });

  board.addEventListener("dragend", function () {
    if (draggingCard) draggingCard.classList.remove("is-dragging");
    draggingCard = null;
    board.querySelectorAll(".kanban-column-body.is-drag-over").forEach(function (el) {
      el.classList.remove("is-drag-over");
    });
  });

  board.addEventListener("dragover", function (event) {
    var dropZone = event.target.closest("[data-drop-zone]");
    if (!dropZone || !draggingCard) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  });

  board.addEventListener("dragenter", function (event) {
    var dropZone = event.target.closest("[data-drop-zone]");
    if (!dropZone || !draggingCard) return;
    dropZone.classList.add("is-drag-over");
  });

  board.addEventListener("dragleave", function (event) {
    var dropZone = event.target.closest("[data-drop-zone]");
    if (!dropZone) return;
    // Só remove o destaque quando o mouse realmente saiu da zona (não ao
    // passar por cima de um card filho, que também dispara dragleave).
    if (!dropZone.contains(event.relatedTarget)) {
      dropZone.classList.remove("is-drag-over");
    }
  });

  board.addEventListener("drop", function (event) {
    var dropZone = event.target.closest("[data-drop-zone]");
    if (!dropZone || !draggingCard) return;
    event.preventDefault();
    dropZone.classList.remove("is-drag-over");

    var card = draggingCard;
    var originZone = card.parentElement;
    var destColumn = dropZone.closest(".kanban-column");
    var originColumn = originZone.closest(".kanban-column");
    if (!destColumn || !originColumn) return;

    if (destColumn === originColumn) return; // soltou na própria coluna — nada a fazer

    var destStageId = destColumn.getAttribute("data-stage-id");
    var destStageName = destColumn.getAttribute("data-stage-name");
    var destIsLost = destColumn.getAttribute("data-stage-is-lost") === "true";
    var opportunityId = card.getAttribute("data-opportunity-id");

    if (destIsLost) {
      openLossModal(opportunityId, destStageId, destStageName, card, originZone, dropZone);
    } else {
      performMove(opportunityId, destStageId, card, originZone, dropZone, {});
    }
  });

  // -------------------------------------------------------------------
  // Envio da mudança de etapa — sempre o mesmo endpoint, nunca outro.
  // -------------------------------------------------------------------
  function performMove(opportunityId, stageId, card, originZone, destZone, extra) {
    var body = new URLSearchParams();
    body.set("stage", stageId);
    body.set("reason", "Movido via arraste no funil Kanban.");
    if (extra.loss_reason) body.set("loss_reason", extra.loss_reason);
    if (extra.loss_notes) body.set("loss_notes", extra.loss_notes);

    card.classList.add("is-pending");

    var url = stageChangeUrl(opportunityId) + (filtersQuery ? "?" + filtersQuery : "");

    fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrfToken,
      },
      body: body.toString(),
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { status: response.status, data: data };
        });
      })
      .then(function (result) {
        card.classList.remove("is-pending");
        if (!result.data.ok) {
          showToast(result.data.error || "Não foi possível mudar a etapa.");
          return;
        }
        destZone.appendChild(card);
        refreshEmptyState(originZone);
        refreshEmptyState(destZone);
        updateColumnSummary(result.data.origin_stage);
        updateColumnSummary(result.data.destination_stage);
      })
      .catch(function () {
        card.classList.remove("is-pending");
        showToast("Falha de comunicação ao mudar a etapa — tente novamente.");
      });
  }

  // -------------------------------------------------------------------
  // Modal "motivo da perda" — obrigatório sempre que o destino é uma
  // etapa is_lost (regra do backend, apps.crm.services.
  // change_opportunity_stage). Um único modal reaproveitado.
  // -------------------------------------------------------------------
  var modal = document.getElementById("kanban-loss-modal");
  var modalStageName = document.getElementById("kanban-loss-modal-stage-name");
  var modalReasonSelect = document.getElementById("kanban-loss-modal-reason");
  var modalNotesInput = document.getElementById("kanban-loss-modal-notes");
  var modalError = document.getElementById("kanban-loss-modal-error");
  var modalConfirmBtn = document.getElementById("kanban-loss-modal-confirm");
  var modalCancelBtn = document.getElementById("kanban-loss-modal-cancel");
  var modalCloseBtn = document.getElementById("kanban-loss-modal-close");

  var pendingMove = null;

  // Estado inicial EXPLÍCITO — nunca depende de o HTML já ter chegado
  // certo do servidor (defesa em profundidade contra o bug corrigido em
  // 11/09/2026: o modal nascia visível porque `.kanban-modal-backdrop`
  // define `display: flex`, que vencia o `display: none` implícito do
  // atributo `hidden` na cascata CSS — ver a regra
  // `.kanban-modal-backdrop[hidden]` em _design_tokens.html para a
  // correção da causa raiz). `pendingMove` também começa explicitamente
  // nulo: nenhum card/etapa fica "em transição" até um drop de verdade
  // acontecer.
  if (modal) {
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
  }
  pendingMove = null;

  if (modal && modalReasonSelect) {
    lossReasons.forEach(function (reason) {
      var option = document.createElement("option");
      option.value = reason.id;
      option.textContent = reason.name;
      modalReasonSelect.appendChild(option);
    });
  }

  function openLossModal(opportunityId, stageId, stageName, card, originZone, destZone) {
    if (!modal) {
      // Sem modal na página (ex.: usuário sem permissão de mudar etapa —
      // o botão nem deveria ter chegado aqui, já que os cards não são
      // arrastáveis nesse caso) — aborta defensivamente.
      return;
    }
    pendingMove = { opportunityId: opportunityId, stageId: stageId, card: card, originZone: originZone, destZone: destZone };
    modalStageName.textContent = stageName || "";
    modalReasonSelect.value = "";
    modalNotesInput.value = "";
    modalError.classList.add("hidden");
    modalError.textContent = "";
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    modalReasonSelect.focus();
  }

  function closeLossModal() {
    // Cancelar/fechar NUNCA toca no backend nem no DOM do card: o card
    // só é movido de coluna dentro de performMove(), depois de um
    // sucesso confirmado pelo servidor — como o drop numa etapa de
    // perda nunca chama performMove() antes da confirmação do modal,
    // não existe nenhuma posição visual para "devolver" aqui, e nenhuma
    // chamada de rede/contador/StageChange foi criada só por abrir o
    // modal.
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    pendingMove = null;
  }

  if (modalCancelBtn) modalCancelBtn.addEventListener("click", closeLossModal);
  if (modalCloseBtn) modalCloseBtn.addEventListener("click", closeLossModal);
  if (modal) {
    modal.addEventListener("click", function (event) {
      if (event.target === modal) closeLossModal();
    });
  }
  // Tecla ESC fecha o modal, igual a qualquer diálogo modal padrão — só
  // quando ele está de fato aberto (nunca intercepta ESC no resto do
  // Kanban).
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && modal && !modal.hidden) {
      closeLossModal();
    }
  });

  if (modalConfirmBtn) {
    modalConfirmBtn.addEventListener("click", function () {
      if (!pendingMove) return;
      var reasonId = modalReasonSelect.value;
      if (!reasonId) {
        modalError.textContent = "Motivo de perda é obrigatório ao marcar a oportunidade como perdida.";
        modalError.classList.remove("hidden");
        return;
      }
      var move = pendingMove;
      closeLossModal();
      performMove(move.opportunityId, move.stageId, move.card, move.originZone, move.destZone, {
        loss_reason: reasonId,
        loss_notes: modalNotesInput.value,
      });
    });
  }
})();
