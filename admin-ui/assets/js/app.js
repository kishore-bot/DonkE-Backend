// Entry point: sign-in (with optional TOTP), layout and hash routing.

import { api, ApiError, setCsrf } from "./api.js";
import { h, mount, toast } from "./dom.js";
import { VIEWS } from "./views.js";

const root = document.getElementById("app");
const state = { admin: null };

function allowed(view) {
  return !view.roles || view.roles.includes(state.admin.role);
}

function signIn(message = "") {
  const needsCode = { value: false };
  const error = h("p", { class: "error", hidden: !message }, message);
  const code = h("label", { hidden: true }, "Authenticator code",
    h("input", { name: "totp", inputmode: "numeric", pattern: "\\d{6}", maxlength: 6, autocomplete: "one-time-code" }));
  const form = h(
    "form",
    {
      class: "fields",
      onsubmit: async (event) => {
        event.preventDefault();
        const data = new FormData(form);
        const body = { username: data.get("username"), password: data.get("password") };
        if (needsCode.value) body.totp = data.get("totp");
        try {
          const login = await api.post("/admin/auth/login", body);
          start(login);
        } catch (failure) {
          if (failure instanceof ApiError && failure.code === "totp_required") {
            needsCode.value = true;
            code.hidden = false;
            code.querySelector("input").focus();
            error.textContent = "Enter the 6-digit code from your authenticator app.";
          } else {
            error.textContent = failure.message;
          }
          error.hidden = false;
        }
      },
    },
    h("label", {}, "Username", h("input", { name: "username", autocomplete: "username", required: true })),
    h("label", {}, "Password", h("input", { name: "password", type: "password", autocomplete: "current-password", required: true })),
    code,
    error,
    h("button", { class: "primary", type: "submit" }, "Sign in"),
  );
  mount(root, h("div", { class: "login" }, h("div", { class: "card" },
    h("div", { class: "brand" }, "DONKE"),
    h("p", { class: "muted" }, "Kazhutha operations console"),
    form)));
}

function layout() {
  const nav = h("nav", { class: "sidebar", "aria-label": "Admin sections" },
    h("div", { class: "brand" }, "DONKE ADMIN"),
    Object.entries(VIEWS)
      .filter(([, view]) => allowed(view))
      .map(([key, view]) => h("a", { class: "nav-link", href: `#/${key}`, "data-view": key }, view.title)),
    h("div", { class: "who" },
      h("div", {}, `${state.admin.username} · ${state.admin.role}`),
      h("button", { class: "ghost", onclick: logout }, "Sign out")));
  const main = h("main", { class: "main", id: "view" });
  mount(root, h("div", { class: "shell" }, nav, main));
}

async function route() {
  const path = location.hash.replace(/^#\//, "").split("?")[0];
  const key = path.split("/")[0] || "dashboard";
  const view = VIEWS[key] && allowed(VIEWS[key]) ? VIEWS[key] : VIEWS.dashboard;
  for (const link of document.querySelectorAll(".nav-link")) {
    link.classList.toggle("active", link.dataset.view === key);
  }
  const target = document.getElementById("view");
  if (!target) return;
  mount(target, h("p", { class: "muted" }, "Loading…"));
  try {
    const param = decodeURIComponent(path.split("/")[1] ?? "");
    mount(target, await view.render({ admin: state.admin, param, refresh: route }));
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 401) return signIn("Your session ended. Sign in again.");
    mount(target, h("div", { class: "card" }, h("p", { class: "error" }, failure.message)));
  }
}

function start(login) {
  state.admin = login.admin;
  setCsrf(login.csrf_token);
  layout();
  route();
}

async function logout() {
  try {
    await api.post("/admin/auth/logout");
  } catch (failure) {
    toast(failure.message, "bad");
  }
  setCsrf(null);
  state.admin = null;
  signIn("Signed out.");
}

window.addEventListener("hashchange", () => state.admin && route());

try {
  start(await api.get("/admin/auth/me"));
} catch {
  signIn();
}
