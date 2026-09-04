/*
  Modal LIGHT/DARK antes do download em lote de etiquetas (pedido de
  04/09/2026). Injetado só na tela de listagem do Django admin de
  Equipment (`EquipmentAdmin.Media`, apps/equipment/admin.py) — NÃO cria
  nenhuma página nova, só intercepta o envio do form de ações do próprio
  admin quando a ação escolhida é "download_labels_pdf" (a mesma que já
  existia: "Baixar etiquetas em PDF (lote)").

  Fluxo:
    1. Usuário seleciona equipamentos (checkboxes nativos do admin) e
       escolhe a ação "Baixar etiquetas em PDF (lote)" + clica em "Ir"/"Go".
    2. Este script intercepta o submit do #changelist-form ANTES de
       qualquer requisição sair (event.preventDefault()) e abre o modal —
       a seleção de equipamentos continua exatamente como estava, porque
       nenhuma navegação aconteceu ainda.
    3. Usuário escolhe LIGHT ou DARK e clica em "Download".
    4. Este script injeta um <input type="hidden" name="tema"> no MESMO
       form (que já carrega os checkboxes marcados) e chama form.submit()
       de verdade — daí em diante é o fluxo padrão do Django admin
       (POST → apps/equipment/admin.py::download_labels_pdf → redirect
       para qrcodes:label_batch?patrimonio=...&tema=...).
    5. Fechar o modal (X, clique fora, Esc) NUNCA envia o form.

  O backend (apps/qrcodes/views.py::LabelBatchDownloadView) é quem de
  fato valida "tema" — este script só evita o caso comum (esquecer de
  escolher); nunca é a única linha de defesa.
*/
(function () {
  "use strict";

  var ACTION_NAME = "download_labels_pdf";
  var THEME_FIELD_NAME = "tema";
  var BACKDROP_ID = "locus-label-theme-modal-backdrop";

  function ready(fn) {
    if (document.readyState !== "loading") {
      fn();
    } else {
      document.addEventListener("DOMContentLoaded", fn);
    }
  }

  ready(function () {
    var form = document.getElementById("changelist-form");
    if (!form) {
      return;
    }

    form.addEventListener("submit", function (event) {
      var actionSelect = form.querySelector('select[name="action"]');
      if (!actionSelect || actionSelect.value !== ACTION_NAME) {
        return; // outra ação (ou nenhuma) — segue o fluxo padrão do admin.
      }

      if (form.querySelector('input[name="' + THEME_FIELD_NAME + '"]')) {
        // Já passamos pelo modal nesta mesma tentativa (submit
        // programático abaixo) — deixa seguir, senão o form nunca seria
        // enviado de verdade.
        return;
      }

      var selected = form.querySelectorAll('input[name="_selected_action"]:checked');
      if (selected.length === 0) {
        // Nenhum equipamento selecionado — deixa o próprio admin mostrar
        // o erro padrão dele ("Nenhum item selecionado.").
        return;
      }

      event.preventDefault();
      openThemeModal(function (theme) {
        var input = document.createElement("input");
        input.type = "hidden";
        input.name = THEME_FIELD_NAME;
        input.value = theme;
        form.appendChild(input);
        form.submit();
      });
    });
  });

  function openThemeModal(onConfirm) {
    closeExistingModal();

    var chosenTheme = null;
    var previouslyFocused = document.activeElement;

    var backdrop = document.createElement("div");
    backdrop.className = "locus-label-modal-backdrop";
    backdrop.id = BACKDROP_ID;

    var modal = document.createElement("div");
    modal.className = "locus-label-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "locus-label-modal-title");

    modal.innerHTML =
      '<div class="locus-label-modal-header">' +
      '<h2 id="locus-label-modal-title" class="locus-label-modal-title">Impressão de etiquetas</h2>' +
      '<button type="button" class="locus-label-modal-close" aria-label="Fechar">&times;</button>' +
      "</div>" +
      '<div class="locus-label-modal-body">' +
      '<div class="locus-label-theme-options" role="radiogroup" aria-label="Tema da etiqueta">' +
      themeOptionHTML("light", "LIGHT") +
      themeOptionHTML("dark", "DARK") +
      "</div>" +
      '<p class="locus-label-modal-hint">Ao imprimir, utilize tamanho real / escala 100%.</p>' +
      "</div>" +
      '<div class="locus-label-modal-footer">' +
      '<button type="button" class="locus-label-modal-download" disabled>Download</button>' +
      "</div>";

    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    var downloadBtn = modal.querySelector(".locus-label-modal-download");
    var closeBtn = modal.querySelector(".locus-label-modal-close");
    var optionCards = Array.prototype.slice.call(modal.querySelectorAll(".locus-label-theme-option"));

    function selectCard(card) {
      optionCards.forEach(function (c) {
        var isThis = c === card;
        c.classList.toggle("is-selected", isThis);
        c.setAttribute("aria-checked", isThis ? "true" : "false");
      });
      chosenTheme = card.getAttribute("data-theme");
      downloadBtn.disabled = false;
    }

    optionCards.forEach(function (card) {
      card.addEventListener("click", function () {
        selectCard(card);
      });
      card.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectCard(card);
        }
      });
    });

    function close() {
      backdrop.remove();
      document.removeEventListener("keydown", onKeyDown);
      if (previouslyFocused && typeof previouslyFocused.focus === "function") {
        previouslyFocused.focus();
      }
    }

    function onKeyDown(event) {
      if (event.key === "Escape") {
        close();
      }
    }

    closeBtn.addEventListener("click", close);
    backdrop.addEventListener("click", function (event) {
      if (event.target === backdrop) {
        close();
      }
    });
    document.addEventListener("keydown", onKeyDown);

    downloadBtn.addEventListener("click", function () {
      if (!chosenTheme) {
        return;
      }
      var theme = chosenTheme;
      close();
      onConfirm(theme);
    });

    closeBtn.focus();
  }

  function closeExistingModal() {
    var existing = document.getElementById(BACKDROP_ID);
    if (existing) {
      existing.remove();
    }
  }

  function themeOptionHTML(theme, label) {
    var previewClass = "locus-label-preview locus-label-preview-" + theme;
    return (
      '<button type="button" class="locus-label-theme-option" data-theme="' +
      theme +
      '" role="radio" aria-checked="false">' +
      '<span class="' +
      previewClass +
      '">' +
      '<span class="locus-label-preview-id">' +
      '<span class="locus-label-preview-bar"></span>' +
      '<span class="locus-label-preview-text"></span>' +
      "</span>" +
      '<span class="locus-label-preview-qr"></span>' +
      "</span>" +
      '<span class="locus-label-theme-name">' +
      label +
      "</span>" +
      "</button>"
    );
  }
})();
