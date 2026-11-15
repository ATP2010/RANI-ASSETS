"use strict";

// Aktif hanya di halaman bertanda meta RANI (server merender <meta name="rani" content="app">).
// Di luar itu ekstensi diam total.
const marker = document.querySelector('meta[name="rani"][content="app"]');
if (marker) {
  window.__RANI_ACTIONS__ = true;

  document.addEventListener("click", (event) => {
    const el = event.target.closest("[data-rani-action]");
    if (!el) return;

    event.preventDefault();
    event.stopPropagation();

    const payload = {
      type: "rani-action",
      file: el.getAttribute("data-file") || "",
      args: el.getAttribute("data-args") || "",
      exp: el.getAttribute("data-exp") || "",
      sig: el.getAttribute("data-sig") || "",
      label: el.textContent.trim(),
      origin: window.location.origin,
    };
    if (!payload.file) {
      showToast("RANI Actions: action tidak punya file.");
      return;
    }
    chrome.runtime.sendMessage(payload, (resp) => {
      const err = chrome.runtime.lastError ? chrome.runtime.lastError.message
        : (resp && !resp.ok ? (resp.error || "host menolak mengeksekusi") : null);
      if (err) showToast("RANI Actions: " + err);
    });
  }, true);

  function showToast(msg) {
    const el = document.createElement("div");
    el.textContent = msg;
    el.setAttribute("role", "alert");
    el.style.cssText =
      "position:fixed;bottom:1.25rem;right:1.25rem;z-index:2147483647;" +
      "background:#212529;color:#fff;padding:.55rem .8rem;border-radius:.5rem;" +
      "font-size:.85rem;box-shadow:0 .4rem 1.2rem rgba(0,0,0,.4);max-width:22rem";
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4500);
  }
}
