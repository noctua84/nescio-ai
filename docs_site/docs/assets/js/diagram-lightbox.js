/* ===========================================================================
   diagram-lightbox.js — the full-size view behind every inlined diagram.

   WHY THIS EXISTS
   ---------------
   The diagrams are authored far wider than the article column, so nescio.css
   caps them to it. That trade costs legibility: the smallest labels land around
   8px on a 1440px window. This script buys it back — one click, one Enter, one
   Space on the artwork and the same SVG opens at its natural size in a modal
   that pans. "Never scale the artwork" was the old rule; it is retired
   deliberately, and this file is the compensation that made retiring it safe.

   NO DEPENDENCIES, BY SPEC
   ------------------------
   design-system.md §3: no CDN, no third-party request at runtime. That is not a
   preference about bundle size, it is the same rule that makes theme.font
   false in mkdocs.yml. Everything below is plain DOM.

   WHY THE SVG IS CLONED AND NOT MOVED
   -----------------------------------
   The inline-SVG mechanism (hooks/inline_svg.py) exists so the page's own
   --diagram-* custom properties reach the artwork and the scheme toggle
   repaints it live. Those properties are declared on the element carrying
   `data-md-color-scheme`, which Material puts on <body>, so a clone appended to
   <body> inherits exactly the same values as the original — the toggle repaints
   the modal and the page together, with no second mechanism to keep in sync.

   Cloning duplicates the SVG's marker ids (`head-end` and friends). A
   `url(#head-end)` reference resolves to the FIRST match in document order,
   which is the original still sitting in the article; the two definitions are
   byte-identical, so both copies draw the same arrowheads. The clone is thrown
   away on close, so the duplication lasts only while the modal is open.

   WHY THE SCROLLBAR WIDTH IS MEASURED HERE AND NOT IN CSS
   ------------------------------------------------------
   Locking the background means `overflow: hidden` on <body>, which removes the
   page scrollbar and shifts the whole layout sideways by its width. The
   compensating padding has to be the real number, and the real number is
   `window.innerWidth - documentElement.clientWidth` — the exact gap nescio.css's
   "no viewport units" rule is about. CSS cannot see it; JS can measure it.
   =========================================================================== */

(function () {
  "use strict";

  var TRIGGER = ".nescio-diagram__trigger";
  var TITLE_ID = "nescio-lightbox-title";

  var overlay = null;      // the fixed-position ground; also the backdrop
  var pane = null;         // role=dialog
  var titleEl = null;
  var stage = null;        // the scrolling/panning surface holding the clone
  var closeButton = null;
  var opener = null;       // the button to hand focus back to
  var lockedScrollTop = 0;

  /* The affordances that are honest only once this script is running: the
     zoom cursor and the hover treatment. Without JS the button is inert, so
     nescio.css gates them on this attribute rather than painting a promise the
     page cannot keep. */
  document.documentElement.setAttribute("data-nescio-lightbox", "ready");

  function build() {
    if (overlay) return;

    overlay = document.createElement("div");
    overlay.className = "nescio-lightbox";
    overlay.hidden = true;

    pane = document.createElement("div");
    pane.className = "nescio-lightbox__pane";
    pane.setAttribute("role", "dialog");
    pane.setAttribute("aria-modal", "true");
    pane.setAttribute("aria-labelledby", TITLE_ID);

    var bar = document.createElement("div");
    bar.className = "nescio-lightbox__bar";

    titleEl = document.createElement("p");
    titleEl.className = "nescio-lightbox__title";
    titleEl.id = TITLE_ID;

    closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "nescio-lightbox__close";
    closeButton.textContent = "Close";

    stage = document.createElement("div");
    stage.className = "nescio-lightbox__stage";
    /* Tabbable on purpose: a scroll container that only a mouse can pan is not
       reachable at all by keyboard. With tabindex="0" the arrow keys work, and
       it doubles as the second stop in the focus trap below. */
    stage.tabIndex = 0;

    bar.appendChild(titleEl);
    bar.appendChild(closeButton);
    pane.appendChild(bar);
    pane.appendChild(stage);
    overlay.appendChild(pane);
    document.body.appendChild(overlay);

    closeButton.addEventListener("click", close);
    /* Backdrop click. The overlay is the backdrop, so a click that lands on the
       overlay itself — never one that bubbled out of the pane — closes. */
    overlay.addEventListener("mousedown", function (event) {
      if (event.target === overlay) close();
    });
  }

  function focusable() {
    return [closeButton, stage];
  }

  function onKeydown(event) {
    if (event.key === "Escape" || event.key === "Esc") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;

    /* Focus trap. Only two stops, so the wrap is a two-line case rather than a
       generic tabbable-node walk — and it cannot go stale when the artwork
       inside the stage changes. */
    var stops = focusable();
    var first = stops[0];
    var last = stops[stops.length - 1];
    var active = document.activeElement;

    if (!pane.contains(active)) {
      event.preventDefault();
      first.focus();
    } else if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function lockBackground() {
    var gutter = window.innerWidth - document.documentElement.clientWidth;
    lockedScrollTop = window.scrollY;
    document.body.style.overflow = "hidden";
    if (gutter > 0) document.body.style.paddingRight = gutter + "px";
  }

  function unlockBackground() {
    document.body.style.overflow = "";
    document.body.style.paddingRight = "";
    window.scrollTo(0, lockedScrollTop);
  }

  function open(trigger) {
    var svg = trigger.querySelector("svg");
    if (!svg) return;

    build();
    opener = trigger;

    titleEl.textContent = trigger.getAttribute("data-diagram-title") || "Diagram";
    stage.textContent = "";
    stage.appendChild(svg.cloneNode(true));
    stage.scrollTop = 0;
    stage.scrollLeft = 0;

    lockBackground();
    overlay.hidden = false;
    document.addEventListener("keydown", onKeydown, true);
    closeButton.focus();
  }

  function close() {
    if (!overlay || overlay.hidden) return;

    document.removeEventListener("keydown", onKeydown, true);
    overlay.hidden = true;
    stage.textContent = "";
    unlockBackground();

    /* Focus returns to the button that opened the modal — otherwise it falls to
       <body> and a keyboard reader loses their place in the page entirely. */
    if (opener && document.contains(opener)) opener.focus();
    opener = null;
  }

  /* Delegated, so it needs no re-binding if the article is ever swapped out
     under us (Material's instant navigation, a future hook). A <button> turns
     Enter and Space into this same click, so there is no keydown branch here. */
  document.addEventListener("click", function (event) {
    var trigger = event.target.closest ? event.target.closest(TRIGGER) : null;
    if (!trigger) return;
    event.preventDefault();
    open(trigger);
  });
})();
