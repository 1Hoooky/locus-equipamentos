/*
  Modal de escolha de tema LIGHT/DARK antes do download de etiquetas
  (correção de requisito de 08/09/2026) — versão para as páginas da
  aplicação (equipment/list.html, equipment/batch_result.html), NÃO a
  versão anterior usada só no Django admin
  (static/qrcodes/admin/label_theme_modal.js, que continua existindo e
  intocada — intercepta o form/checkboxes do admin, uma estrutura que
  não existe fora dele).

  Qualquer elemento com `data-label-theme-trigger` é um link comum
  (`<a href="...">`) que já aponta para a rota correta (sem `?tema=`,
  que é sempre "light" por padrão no backend) — este script intercepta o
  clique, abre o modal, e ao confirmar navega para o MESMO href do link,
  só acrescentando `tema=light` ou `tema=dark` na querystring. Nenhuma
  seleção de equipamento é perdida: nenhuma navegação acontece até o
  clique em "Download" dentro do modal — a tela por trás continua
  exatamente como estava (mesmo princípio da versão do admin).

  Delegação de evento no `document` (não um `querySelectorAll` fixo no
  carregamento da página): o botão de etiquetas em lote por modelo é
  renderizado direto no HTML de list.html (não via HTMX), mas delegar o
  clique custa nada e deixa o script robusto a qualquer gatilho
  adicionado no futuro, mesmo que passe a ser carregado dinamicamente.
*/
(function () {
  "use strict";

  var BACKDROP_ID = "locus-label-theme-modal-backdrop";

  function ready(fn) {
    if (document.readyState !== "loading") {
      fn();
    } else {
      document.addEventListener("DOMContentLoaded", fn);
    }
  }

  ready(function () {
    document.addEventListener("click", function (event) {
      var trigger = event.target.closest("[data-label-theme-trigger]");
      if (!trigger) {
        return;
      }
      event.preventDefault();
      openThemeModal(function (theme) {
        var href = trigger.getAttribute("href") || "";
        var separator = href.indexOf("?") === -1 ? "?" : "&";
        window.location.href = href + separator + "tema=" + theme;
      });
    });
  });

  function openThemeModal(onConfirm) {
    closeExistingModal();

    var chosenTheme = null;
    var previouslyFocused = document.activeElement;

    var backdrop = document.createElement("div");
    backdrop.className = "label-theme-modal-backdrop";
    backdrop.id = BACKDROP_ID;

    var modal = document.createElement("div");
    modal.className = "label-theme-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "locus-label-theme-modal-title");

    modal.innerHTML =
      '<div class="label-theme-modal-header">' +
      '<h2 id="locus-label-theme-modal-title" class="label-theme-modal-title">Impressão de etiquetas</h2>' +
      '<button type="button" class="icon-btn-neutral" aria-label="Fechar">&times;</button>' +
      "</div>" +
      '<div class="label-theme-modal-body">' +
      '<div class="label-theme-options" role="radiogroup" aria-label="Tema da etiqueta">' +
      themeOptionHTML("light", "LIGHT") +
      themeOptionHTML("dark", "DARK") +
      "</div>" +
      '<p class="label-theme-modal-hint">Ao imprimir, utilize tamanho real / escala 100%.</p>' +
      "</div>" +
      '<div class="label-theme-modal-footer">' +
      '<button type="button" class="btn-primary label-theme-modal-download" disabled>Download</button>' +
      "</div>";

    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    var downloadBtn = modal.querySelector(".label-theme-modal-download");
    var closeBtn = modal.querySelector(".icon-btn-neutral");
    var optionCards = Array.prototype.slice.call(modal.querySelectorAll(".label-theme-option"));

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
    return (
      '<button type="button" class="label-theme-option" data-theme="' +
      theme +
      '" role="radio" aria-checked="false">' +
      '<span class="label-theme-preview label-theme-preview--' +
      theme +
      '">' +
      '<span class="label-theme-preview-qr"></span>' +
      '<span class="label-theme-preview-line"></span>' +
      "</span>" +
      '<span class="label-theme-option-name">' +
      label +
      "</span>" +
      "</button>"
    );
  }
})();
