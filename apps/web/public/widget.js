(function () {
  "use strict";

  var script = document.currentScript;
  if (!script || !window.fetch) return;
  if (document.body) boot(script);
  else document.addEventListener("DOMContentLoaded", boot.bind(null, script));

  function boot(tag) {
    var key = tag.getAttribute("data-key");
    var api = (tag.getAttribute("data-api") || "").replace(/\/+$/, "");
    if (!key || !api || document.getElementById("satushy-widget")) return;

    var color = tag.getAttribute("data-color") || "#14532d";
    var title = tag.getAttribute("data-title") || "Онлайн-консультант";
    var base = api + "/widget/" + encodeURIComponent(key);
    var storageKey = "satushy:" + key;
    var MAX_HISTORY = 50;

    var state = load();
    if (!state.session) {
      state.session = randomId(32);
      save();
    }

    var host = document.createElement("div");
    host.id = "satushy-widget";
    var root = host.attachShadow({ mode: "open" });
    root.appendChild(styles(color));

    var launcher = el("button", "launcher");
    launcher.type = "button";
    launcher.setAttribute("aria-label", "Открыть чат");
    launcher.setAttribute("aria-expanded", "false");
    launcher.appendChild(chatIcon());

    var panel = el("section", "panel");
    panel.hidden = true;
    panel.setAttribute("aria-label", title);

    var header = el("header", "header");
    var heading = el("span", "title");
    heading.textContent = title;
    var close = el("button", "close");
    close.type = "button";
    close.setAttribute("aria-label", "Закрыть чат");
    close.textContent = "×";
    header.appendChild(heading);
    header.appendChild(close);

    var log = el("div", "log");
    log.setAttribute("role", "log");
    log.setAttribute("aria-live", "polite");

    var typing = el("div", "typing");
    typing.textContent = "Печатает…";
    typing.hidden = true;

    var form = el("form", "form");
    var input = el("textarea", "input");
    input.rows = 1;
    input.maxLength = 2000;
    input.placeholder = "Напишите сообщение…";
    input.setAttribute("aria-label", "Сообщение");
    var submit = el("button", "send");
    submit.type = "submit";
    submit.textContent = "Отправить";
    form.appendChild(input);
    form.appendChild(submit);

    panel.appendChild(header);
    panel.appendChild(log);
    panel.appendChild(typing);
    panel.appendChild(form);
    root.appendChild(panel);
    root.appendChild(launcher);
    document.body.appendChild(host);

    state.messages.forEach(render);

    var stream = null;
    var retryDelay = 1000;
    var retryTimer = null;
    var typingTimer = null;
    var awaiting = false;

    launcher.addEventListener("click", function () {
      setOpen(panel.hidden);
    });
    close.addEventListener("click", function () {
      setOpen(false);
    });
    root.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !panel.hidden) {
        setOpen(false);
        launcher.focus();
      }
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        submitForm();
      }
    });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      submitForm();
    });

    function setOpen(open) {
      panel.hidden = !open;
      launcher.setAttribute("aria-expanded", String(open));
      launcher.setAttribute("aria-label", open ? "Свернуть чат" : "Открыть чат");
      if (open) {
        setUnread(false);
        connect();
        scrollDown();
        input.focus();
      } else if (!awaiting) {
        disconnect();
      }
    }

    function setUnread(unread) {
      launcher.classList.toggle("unread", unread);
      if (unread) launcher.setAttribute("aria-label", "Открыть чат: новое сообщение");
    }

    function wantsStream() {
      return !panel.hidden || awaiting;
    }

    function submitForm() {
      var text = input.value.trim();
      if (!text) return;
      input.value = "";
      remember({ role: "customer", text: text });
      deliver({ id: randomId(16), text: text });
    }

    function deliver(body) {
      showTyping(true);
      fetch(base + "/messages", {
        method: "POST",
        credentials: "omit",
        headers: {
          "Content-Type": "application/json",
          "X-Widget-Session": state.session,
        },
        body: JSON.stringify(body),
      })
        .then(function (response) {
          if (!response.ok) throw new Error(String(response.status));
          connect();
        })
        .catch(function () {
          showTyping(false);
          renderFailure(body);
        });
    }

    function renderFailure(body) {
      var row = el("div", "failure");
      var text = el("span");
      text.textContent = "Не удалось отправить. ";
      var again = el("button", "retry");
      again.type = "button";
      again.textContent = "Повторить";
      again.addEventListener("click", function () {
        row.remove();
        deliver(body);
      });
      row.appendChild(text);
      row.appendChild(again);
      log.appendChild(row);
      scrollDown();
    }

    function connect() {
      if (stream || !wantsStream()) return;
      clearTimeout(retryTimer);
      var controller = new AbortController();
      stream = controller;
      var headers = { "X-Widget-Session": state.session };
      if (state.lastEventId) headers["Last-Event-ID"] = state.lastEventId;
      fetch(base + "/stream", {
        credentials: "omit",
        headers: headers,
        signal: controller.signal,
      })
        .then(function (response) {
          if (!response.ok || !response.body) throw new Error(String(response.status));
          retryDelay = 1000;
          return readEvents(response.body.getReader());
        })
        .catch(function () {
          return undefined;
        })
        .then(function () {
          if (stream !== controller) return;
          stream = null;
          if (wantsStream()) {
            retryTimer = setTimeout(connect, retryDelay);
            retryDelay = Math.min(retryDelay * 2, 15000);
          }
        });
    }

    function disconnect() {
      clearTimeout(retryTimer);
      if (stream) {
        stream.abort();
        stream = null;
      }
    }

    function readEvents(reader) {
      var decoder = new TextDecoder();
      var buffer = "";
      function pump() {
        return reader.read().then(function (chunk) {
          if (chunk.done) return undefined;
          buffer += decoder.decode(chunk.value, { stream: true });
          var parts = buffer.split("\n\n");
          buffer = parts.pop();
          parts.forEach(handleEvent);
          return pump();
        });
      }
      return pump();
    }

    function handleEvent(raw) {
      var id = null;
      var data = "";
      raw.split("\n").forEach(function (line) {
        if (line.indexOf("id: ") === 0) id = line.slice(4);
        else if (line.indexOf("data: ") === 0) data += line.slice(6);
      });
      if (!data) return;
      try {
        var message = JSON.parse(data);
        showTyping(false);
        remember({
          role: "bot",
          text: message.text || "",
          cards: message.cards || [],
        });
      } catch {
        return;
      }
      if (id) {
        state.lastEventId = id;
        save();
      }
      if (panel.hidden) {
        setUnread(true);
        disconnect();
      }
    }

    function remember(message) {
      state.messages.push(message);
      state.messages = state.messages.slice(-MAX_HISTORY);
      save();
      render(message);
    }

    function render(message) {
      if (message.text) {
        var bubble = el("div", "bubble " + message.role);
        bubble.textContent = message.text;
        log.appendChild(bubble);
      }
      (message.cards || []).forEach(function (card) {
        log.appendChild(renderCard(card));
      });
      scrollDown();
    }

    function renderCard(card) {
      var box = el("div", "card");
      if (card.image_url && card.image_url.indexOf("https://") === 0) {
        var image = el("img", "photo");
        image.src = card.image_url;
        image.alt = card.title || "";
        image.loading = "lazy";
        image.addEventListener("error", function () {
          image.remove();
        });
        box.appendChild(image);
      }
      var caption = el("div", "caption");
      caption.textContent = card.caption || "";
      box.appendChild(caption);
      (card.buttons || []).forEach(function (button) {
        var action = el("button", "action");
        action.type = "button";
        action.textContent = button.title;
        action.addEventListener("click", function () {
          action.disabled = true;
          remember({ role: "customer", text: button.title });
          deliver({ id: randomId(16), payload: button.payload });
        });
        box.appendChild(action);
      });
      return box;
    }

    function showTyping(visible) {
      clearTimeout(typingTimer);
      typing.hidden = !visible;
      awaiting = visible;
      if (visible) {
        typingTimer = setTimeout(function () {
          showTyping(false);
          if (panel.hidden) disconnect();
        }, 60000);
      }
      scrollDown();
    }

    function scrollDown() {
      log.scrollTop = log.scrollHeight;
    }

    function load() {
      var empty = { session: null, lastEventId: null, messages: [] };
      try {
        var saved = JSON.parse(window.localStorage.getItem(storageKey));
        if (saved && Array.isArray(saved.messages)) return saved;
      } catch {
        return empty;
      }
      return empty;
    }

    function save() {
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(state));
      } catch {
        return;
      }
    }
  }

  function el(tag, className) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    return node;
  }

  function randomId(size) {
    var bytes = new Uint8Array(size);
    window.crypto.getRandomValues(bytes);
    return Array.prototype.map
      .call(bytes, function (byte) {
        return ("0" + byte.toString(16)).slice(-2);
      })
      .join("");
  }

  function chatIcon() {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "26");
    svg.setAttribute("height", "26");
    svg.setAttribute("aria-hidden", "true");
    var path = document.createElementNS(ns, "path");
    path.setAttribute("fill", "currentColor");
    path.setAttribute(
      "d",
      "M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
    );
    svg.appendChild(path);
    return svg;
  }

  function styles(color) {
    var style = document.createElement("style");
    var accent = /^#[0-9a-fA-F]{3,8}$/.test(color) ? color : "#14532d";
    style.textContent =
      ":host{all:initial;--accent:" +
      accent +
      ";font:15px/1.4 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:#1c1917}" +
      "*{box-sizing:border-box;font:inherit}[hidden]{display:none!important}" +
      "button{cursor:pointer}button:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}" +
      ".launcher{position:fixed;right:20px;bottom:20px;z-index:2147483000;width:56px;height:56px;border:0;border-radius:50%;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 6px 20px rgba(0,0,0,.25)}" +
      ".launcher.unread::after{content:'';position:absolute;top:2px;right:2px;width:14px;height:14px;border-radius:50%;background:#dc2626;border:2px solid #fff}" +
      ".panel{position:fixed;right:20px;bottom:88px;z-index:2147483000;width:360px;height:520px;max-height:calc(100vh - 108px);display:flex;flex-direction:column;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,.25)}" +
      ".header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;background:var(--accent);color:#fff}" +
      ".title{font-weight:600}.close{border:0;background:none;color:inherit;font-size:22px;line-height:1;padding:0 4px}" +
      ".log{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;background:#fafaf9}.log>*{flex-shrink:0}" +
      ".bubble{max-width:85%;padding:8px 12px;border-radius:12px;white-space:pre-wrap;overflow-wrap:anywhere}" +
      ".bubble.customer{align-self:flex-end;background:var(--accent);color:#fff}" +
      ".bubble.bot{align-self:flex-start;background:#fff;border:1px solid #e7e5e4}" +
      ".card{align-self:flex-start;width:85%;background:#fff;border:1px solid #e7e5e4;border-radius:12px;overflow:hidden}" +
      ".photo{display:block;width:100%;height:160px;object-fit:cover}" +
      ".caption{padding:8px 12px;white-space:pre-wrap;overflow-wrap:anywhere}" +
      ".action{display:block;width:calc(100% - 24px);margin:0 12px 10px;padding:7px;border:1px solid var(--accent);border-radius:8px;background:#fff;color:var(--accent);font-weight:600}" +
      ".action:disabled{opacity:.5;cursor:default}" +
      ".typing{padding:0 14px 6px;background:#fafaf9;color:#57534e;font-size:13px}" +
      ".failure{align-self:flex-end;color:#b91c1c;font-size:13px}.retry{border:0;background:none;padding:0;color:inherit;text-decoration:underline}" +
      ".form{display:flex;gap:8px;padding:10px;border-top:1px solid #e7e5e4;background:#fff}" +
      ".input{flex:1;resize:none;min-height:38px;max-height:96px;padding:8px 10px;border:1px solid #d6d3d1;border-radius:8px;color:#1c1917;background:#fff;font-size:16px}" +
      ".send{border:0;border-radius:8px;padding:0 12px;background:var(--accent);color:#fff;font-weight:600}" +
      "@media (max-width:480px){.panel{right:0;bottom:0;width:100vw;height:100dvh;max-height:none;border-radius:0}.launcher{right:16px;bottom:16px}.panel:not([hidden])~.launcher{display:none}}";
    return style;
  }
})();
