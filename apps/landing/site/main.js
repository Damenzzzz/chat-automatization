// Лендинг Satushy: звёзды, журнал «ночной смены» и форма заявки. Без библиотек.
(function () {
  "use strict";

  var root = document.documentElement;
  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var loadedAt = Date.now();
  root.classList.add("js");

  // --- Шапка: фон появляется после прокрутки -------------------------------
  var nav = document.getElementById("nav");
  function paintNav() {
    nav.classList.toggle("nav--solid", window.scrollY > 24);
  }
  window.addEventListener("scroll", paintNav, { passive: true });
  paintNav();

  // --- Звёзды: рисуются один раз, без цикла анимации -------------------------
  var canvas = document.getElementById("stars");
  function drawStars() {
    var box = canvas.getBoundingClientRect();
    var ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(box.width * ratio);
    canvas.height = Math.round(box.height * ratio);
    var ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(ratio, ratio);
    // Свой генератор с постоянным зерном: небо одинаковое при каждой загрузке.
    var seed = 20261113;
    function rnd() {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    }
    var count = Math.round((box.width * box.height) / 5200);
    for (var i = 0; i < count; i += 1) {
      var y = rnd() * box.height;
      var size = rnd() < 0.08 ? 1.6 : rnd() * 0.9 + 0.3;
      ctx.globalAlpha = (0.25 + rnd() * 0.65) * (1 - (y / box.height) * 0.6);
      ctx.fillStyle = rnd() < 0.2 ? "#9eeaf7" : "#ffffff";
      ctx.beginPath();
      ctx.arc(rnd() * box.width, y, size, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  var resizeTimer = 0;
  window.addEventListener("resize", function () {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(drawStars, 200);
  });
  drawStars();

  // --- Журнал ночной смены ---------------------------------------------------
  var clock = document.getElementById("clock");
  var replay = document.getElementById("replay");
  var rows = Array.prototype.slice.call(document.querySelectorAll("#log .shift__row"));
  var NIGHT_START = -19; // 23:41 в минутах от полуночи
  var NIGHT_END = 420; // 07:00
  var timers = [];
  var frame = 0;

  function formatClock(minutes) {
    var total = ((Math.round(minutes) % 1440) + 1440) % 1440;
    var h = Math.floor(total / 60);
    var m = total % 60;
    return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
  }

  function setTime(minutes) {
    clock.textContent = formatClock(minutes);
    var progress = (minutes - NIGHT_START) / (NIGHT_END - NIGHT_START);
    // Рассвет начинается ближе к утру, поэтому куб, а не прямая.
    root.style.setProperty("--dawn", Math.pow(Math.max(0, Math.min(1, progress)), 3).toFixed(3));
  }

  function showMorning() {
    rows.forEach(function (row) {
      row.classList.remove("is-waiting");
    });
    setTime(NIGHT_END);
    replay.classList.remove("is-hidden");
  }

  function playNight() {
    timers.forEach(window.clearTimeout);
    timers = [];
    window.cancelAnimationFrame(frame);
    replay.classList.add("is-hidden");
    rows.forEach(function (row) {
      row.classList.add("is-waiting");
    });
    setTime(NIGHT_START);

    var STEP = 1500; // мс на одно событие: часы бегут, затем строка появляется
    var RUN = 850;
    rows.forEach(function (row, index) {
      var from = index === 0 ? NIGHT_START : Number(rows[index - 1].dataset.at);
      var to = Number(row.dataset.at);
      timers.push(
        window.setTimeout(function () {
          var started = performance.now();
          function tick(now) {
            var t = Math.min(1, (now - started) / RUN);
            var eased = 1 - Math.pow(1 - t, 3);
            setTime(from + (to - from) * eased);
            if (t < 1) {
              frame = window.requestAnimationFrame(tick);
            } else {
              row.classList.remove("is-waiting");
              if (index === rows.length - 1) replay.classList.remove("is-hidden");
            }
          }
          frame = window.requestAnimationFrame(tick);
        }, 500 + index * STEP),
      );
    });
  }

  if (reducedMotion || rows.length === 0) {
    showMorning();
  } else {
    playNight();
  }
  replay.addEventListener("click", playNight);

  // --- Форма заявки ------------------------------------------------------------
  var form = document.getElementById("lead-form");
  var submit = document.getElementById("lead-submit");
  var status = document.getElementById("lead-status");

  function say(text, kind) {
    status.textContent = text;
    status.className = "form__status" + (kind ? " is-" + kind : "");
  }

  function check(field, ok) {
    if (ok) {
      field.removeAttribute("aria-invalid");
    } else {
      field.setAttribute("aria-invalid", "true");
    }
    return ok;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var name = form.elements.name;
    var contact = form.elements.contact;
    var nameOk = check(name, name.value.trim().length >= 1);
    var contactOk = check(contact, contact.value.trim().length >= 3);
    if (!nameOk || !contactOk) {
      say("Укажите имя и контакт, по которому с вами связаться.", "error");
      (nameOk ? contact : name).focus();
      return;
    }

    submit.disabled = true;
    say("Отправляем заявку…", "");
    fetch("/api/lead", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name.value.trim(),
        contact: contact.value.trim(),
        company: form.elements.company.value.trim(),
        task: form.elements.task.value.trim(),
        website: form.elements.website.value,
        elapsed: Date.now() - loadedAt,
        page: window.location.pathname,
      }),
    })
      .then(function (response) {
        return response
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            if (!response.ok || !data.ok) {
              throw new Error(data.error || "");
            }
          });
      })
      .then(function () {
        form.reset();
        say("Заявка отправлена. Мы свяжемся с вами по указанному контакту.", "ok");
      })
      .catch(function (error) {
        say(
          error.message ||
            "Заявка не отправилась. Проверьте интернет и нажмите «Отправить заявку» ещё раз.",
          "error",
        );
      })
      .then(function () {
        submit.disabled = false;
      });
  });
})();
