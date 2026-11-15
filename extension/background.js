"use strict";

// Meneruskan permintaan dari content.js ke native host (com.rani.action_host).
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.type !== "rani-action") return false;

  const nativeMsg = {
    origin: msg.origin,
    file: msg.file,
    args: msg.args || "",
    exp: msg.exp || "",
    sig: msg.sig || "",
    label: msg.label || "",
  };

  chrome.runtime.sendNativeMessage("com.rani.action_host", nativeMsg, (resp) => {
    const err = chrome.runtime.lastError && chrome.runtime.lastError.message;
    if (err) {
      sendResponse({ ok: false, error: "native host tidak terjangkau: " + err });
      return;
    }
    sendResponse(resp || { ok: false, error: "native host tidak merespons" });
  });
  return true; // respons asinkron
});
