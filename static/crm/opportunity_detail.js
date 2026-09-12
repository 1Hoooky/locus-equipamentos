/*
 * Tela interna da Oportunidade (CRM) — REDESIGN COMPLETO DA TELA INTERNA
 * DA OPORTUNIDADE, 12/09/2026.
 *
 * Só duas responsabilidades, nenhuma delas de negócio (a validação real
 * continua 100% no backend — apps/crm/forms.py + apps/crm/services.py):
 *
 *   1. Abrir/fechar os modais "Registrar perda"/"Orçamento aceito"
 *      (mesmo padrão vanilla já usado no modal de perda do Kanban, ver
 *      static/crm/kanban.js: atributo nativo `hidden` + `aria-hidden`,
 *      Escape fecha, clique no backdrop fecha).
 *
 *   2. Roteamento "inteligente" do seletor rápido de etapa: se a etapa
 *      escolhida é `is_lost`/`is_won`, o formulário NÃO é enviado direto
 *      — abre o MESMO modal de Registrar perda/Orçamento aceito (nunca
 *      dois fluxos diferentes para a mesma transição), pré-selecionando
 *      a etapa escolhida quando o modal tem mais de uma candidata.
 *
 * Cada modal é o `<form method="post">` de sempre — sem fetch()/JSON,
 * sem otimismo: confirmar recarrega a página via o redirect+mensagens já
 * existente em `OpportunityStageChangeView`.
 */
(function () {
  "use strict";

  function byId(id) {
    return document.getElementById(id);
  }

  function openModal(modalId, presetStageId) {
    var modal = byId(modalId);
    if (!modal) return;

    if (presetStageId) {
      var select = modal.querySelector('select[name="stage"]');
      if (select) select.value = presetStageId;
    }

    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");

    var focusable = modal.querySelector("select, textarea, input, button");
    if (focusable) focusable.focus();
  }

  function closeModal(modalId) {
    var modal = byId(modalId);
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
  }

  function allModals() {
    return document.querySelectorAll(".kanban-modal-backdrop");
  }

  // Gatilhos "Registrar perda"/"Orçamento aceito" no cabeçalho.
  document.querySelectorAll("[data-open-modal]").forEach(function (trigger) {
    trigger.addEventListener("click", function () {
      openModal(trigger.getAttribute("data-open-modal"));
    });
  });

  // Botões "Cancelar"/fechar (X) dentro de cada modal.
  document.querySelectorAll("[data-close-modal]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      closeModal(btn.getAttribute("data-close-modal"));
    });
  });

  // Clique no backdrop (fora do card do modal) fecha.
  allModals().forEach(function (backdrop) {
    backdrop.addEventListener("click", function (event) {
      if (event.target === backdrop) closeModal(backdrop.id);
    });
  });

  // Escape fecha qualquer modal aberto.
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    allModals().forEach(function (backdrop) {
      if (!backdrop.hidden) closeModal(backdrop.id);
    });
  });

  // Roteamento inteligente do seletor rápido de etapa (ver docstring
  // acima). `data-is-won`/`data-is-lost` em cada <option> vêm do
  // template (templates/crm/opportunity_detail.html), refletindo a
  // configuração REAL das etapas (nunca um nome hardcoded aqui).
  var quickForm = byId("opp-quick-stage-form");
  var quickSelect = byId("opp-quick-stage-select");
  if (quickForm && quickSelect) {
    quickForm.addEventListener("submit", function (event) {
      var chosen = quickSelect.options[quickSelect.selectedIndex];
      if (!chosen) return;

      var isLost = chosen.getAttribute("data-is-lost") === "true";
      var isWon = chosen.getAttribute("data-is-won") === "true";

      if (isLost && byId("opp-loss-modal")) {
        event.preventDefault();
        openModal("opp-loss-modal", chosen.value);
      } else if (isWon && byId("opp-accept-modal")) {
        event.preventDefault();
        openModal("opp-accept-modal", chosen.value);
      }
      // Etapa comum (nem ganho nem perda): envia o formulário normalmente.
    });
  }
})();
