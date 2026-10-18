(function () {
  const root = document.querySelector("#lang-switch");
  const trigger = document.querySelector("#lang-trigger");
  const panel = document.querySelector("#lang-panel");
  const flagEl = document.querySelector("#lang-flag");
  const labelEl = document.querySelector("#lang-label");
  if (!root || !trigger || !panel) return;

  const COOKIE = "googtrans";
  const options = [...panel.querySelectorAll("[data-lang]")];

  function readLang() {
    try {
      const match = document.cookie.match(/(?:^|; )googtrans=\/[^/]+\/([^;]+)/);
      if (match && match[1]) return match[1];
      return localStorage.getItem("flyleaf-lang") || "en";
    } catch (error) {
      return "en";
    }
  }

  function writeCookie(lang) {
    const value = lang === "en" ? "" : "/en/" + lang;
    const expires = "expires=" + new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toUTCString();
    const host = location.hostname;
    document.cookie = COOKIE + "=" + value + "; path=/; " + expires;
    if (host && host.indexOf(".") !== -1) {
      document.cookie = COOKIE + "=" + value + "; path=/; domain=." + host + "; " + expires;
    }
  }

  function setTrigger(lang) {
    const option = options.find((item) => item.dataset.lang === lang) || options[0];
    if (!option) return;
    if (flagEl && option.dataset.flag) {
      const base = root.getAttribute("data-flag-base") || "/static/images/flags";
      flagEl.src = base.replace(/\/$/, "") + "/" + option.dataset.flag + ".svg";
    }
    if (labelEl) labelEl.textContent = option.dataset.label || option.dataset.lang;
    options.forEach((item) => {
      item.setAttribute("aria-selected", item === option ? "true" : "false");
      item.classList.toggle("is-active", item === option);
    });
  }

  function closePanel() {
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  }

  function openPanel() {
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
  }

  function applyLanguage(lang) {
    try {
      localStorage.setItem("flyleaf-lang", lang);
    } catch (error) {}
    writeCookie(lang);
    setTrigger(lang);
    closePanel();
    const combo = document.querySelector(".goog-te-combo");
    if (combo) {
      combo.value = lang === "en" ? "" : lang;
      combo.dispatchEvent(new Event("change"));
      if (lang === "en") {
        writeCookie("en");
        location.reload();
      }
      return;
    }
    location.reload();
  }

  const current = readLang();
  setTrigger(options.some((item) => item.dataset.lang === current) ? current : "en");

  trigger.addEventListener("click", (event) => {
    event.stopPropagation();
    if (panel.hidden) openPanel();
    else closePanel();
  });

  options.forEach((option) => {
    option.addEventListener("click", (event) => {
      event.stopPropagation();
      applyLanguage(option.dataset.lang);
    });
  });

  document.addEventListener("click", (event) => {
    if (!root.contains(event.target)) closePanel();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePanel();
  });

  window.googleTranslateElementInit = function () {
    if (!window.google || !google.translate) return;
    new google.translate.TranslateElement(
      {
        pageLanguage: "en",
        includedLanguages: "en,es,fr,de,zh-CN",
        autoDisplay: false,
        layout: google.translate.TranslateElement.InlineLayout.SIMPLE,
      },
      "google_translate_element",
    );
    const wanted = readLang();
    if (wanted && wanted !== "en") {
      window.setTimeout(() => {
        const combo = document.querySelector(".goog-te-combo");
        if (combo && combo.value !== wanted) {
          combo.value = wanted;
          combo.dispatchEvent(new Event("change"));
        }
      }, 400);
    }
  };

  const script = document.createElement("script");
  script.src = "https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit";
  script.async = true;
  document.body.appendChild(script);
})();
