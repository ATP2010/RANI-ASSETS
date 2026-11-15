"use strict";

const box = document.getElementById("status");

function setOk(text) {
  box.textContent = "✓ " + text;
  box.className = "ok";
}

function setBad(text) {
  box.textContent = "✗ " + text;
  box.className = "bad";
}

// Ping native host lewat jalur nativeMessaging dengan pesan khusus.
chrome.runtime.sendNativeMessage(
  "com.rani.action_host",
  { origin: "ping", file: "", args: "", exp: "0", sig: "" },
  (resp) => {
    const err = chrome.runtime.lastError && chrome.runtime.lastError.message;
    if (err) {
      setBad("native host tidak terjangkau (" + err + ")");
      return;
    }
    setOk("native host terhubung" + (resp && resp.version ? " (v" + resp.version + ")" : ""));
  }
);
