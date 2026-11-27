// One render function per page. Each returns a DOM node.

import { api, query } from "./api.js";
import { ask, badge, h, reasonField, table, toast, when } from "./dom.js";

const MOD = ["moderator", "admin"];
const ADMIN = ["admin"];

function header(title, ...actions) {
  return h("div", { class: "topline" }, h("h1", {}, title), h("div", { class: "row" }, actions));
}

function stat(label, value) {
  return h("div", { class: "stat" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value));
}

async function act(title, fields, call, refresh, done = "Saved") {
  const result = await ask(title, [...fields, reasonField], call);
  if (result) {
    toast(done);
    refresh();
  }
}

const outcomeText = (outcome) =>
  outcome?.reason === "donkey" ? `Donkey: seat ${outcome.seat + 1}` : (outcome?.reason ?? "—");

async function dashboard() {
  const data = await api.get("/admin/dashboard");
  const usage = Object.entries(data.ai_usage).sort(([a], [b]) => a.localeCompare(b));
  return h("div", {},
    header("Dashboard"),
    data.flags.maintenance_notice ? h("div", { class: "card" }, badge("Notice", "warn"), " ", data.flags.maintenance_notice) : null,
    h("div", { class: "grid" },
      stat("Players", data.players),
      stat("New in 24h", data.new_players_24h),
      stat("Matches in 24h", data.matches_24h),
      stat("Live games", data.active_games),
      stat("Open fair-play cases", data.open_fair_play_cases)),
    h("div", { class: "card" },
      h("h2", {}, "AI today"),
      h("p", { class: "row" },
        badge(data.flags.ai_enabled ? "AI on" : "AI off", data.flags.ai_enabled ? "ok" : "bad"),
        badge(data.flags.commentary_enabled ? "Commentary on" : "Commentary off", data.flags.commentary_enabled ? "ok" : "bad")),
      table([{ label: "Counter", render: ([key]) => h("code", {}, key) }, { label: "Today", num: true, render: ([, value]) => value }], usage)));
}

async function players({ param, refresh }) {
  if (param) return playerDetail(param, refresh);
  const search = new URLSearchParams(location.hash.split("?")[1] ?? "").get("q") ?? "";
  const rows = await api.get(`/admin/players${query({ q: search })}`);
  const input = h("input", { type: "search", value: search, placeholder: "Name or player ID", "aria-label": "Search players" });
  const form = h("form", { class: "inline", onsubmit: (event) => {
    event.preventDefault();
    location.hash = `#/players?q=${encodeURIComponent(input.value.trim())}`;
  } }, input, h("button", { type: "submit" }, "Search"));
  return h("div", {},
    header("Players"),
    h("div", { class: "card" }, form),
    h("div", { class: "card" }, table([
      { label: "Name", render: (row) => row.display_name },
      { label: "MMR", num: true, render: (row) => row.mmr },
      { label: "Language", render: (row) => row.language },
      { label: "Status", render: (row) => badge(row.active ? "active" : "banned", row.active ? "ok" : "bad") },
      { label: "Joined", render: (row) => when(row.created_at) },
    ], rows, (row) => (location.hash = `#/players/${row.id}`))));
}

async function playerDetail(id, refresh) {
  const data = await api.get(`/admin/players/${encodeURIComponent(id)}`);
  const player = data.player;
  const path = `/admin/players/${player.id}`;
  const actions = [
    player.active
      ? h("button", { class: "danger", onclick: () => act(`Ban ${player.display_name}`, [], (v) => api.post(`${path}/ban`, v), refresh, "Player banned") }, "Ban")
      : h("button", { onclick: () => act(`Unban ${player.display_name}`, [], (v) => api.post(`${path}/unban`, v), refresh, "Player unbanned") }, "Unban"),
    h("button", { onclick: () => act(data.muted_until ? "Lift chat mute" : "Mute chat", data.muted_until ? [] : [{ name: "minutes", label: "Minutes (max 43200)", type: "number", value: "60", parse: Number }], (v) => api.post(`${path}/mute`, { minutes: 0, ...v }), refresh, data.muted_until ? "Mute lifted" : "Player muted") }, data.muted_until ? "Unmute" : "Mute"),
    h("button", { onclick: () => act("Grant or remove coins", [{ name: "amount", label: "Coins (negative removes)", type: "number", parse: Number }], (v) => api.post(`${path}/coins`, v), refresh) }, "Coins"),
    h("button", { onclick: () => act("Grant a cosmetic", [{ name: "sku", label: "Cosmetic SKU" }], (v) => api.post(`${path}/cosmetics`, v), refresh) }, "Cosmetic"),
  ];
  return h("div", {},
    header(player.display_name, h("a", { class: "button", href: "#/players" }, "Back"), actions),
    h("div", { class: "grid" },
      stat("MMR", player.mmr),
      stat("Coins", data.coins),
      stat("Matches", data.stats.games),
      stat("Escapes", data.stats.escapes),
      stat("Donkey", data.stats.donkeys),
      stat("Open cases", data.open_cases),
      stat("Open reports", data.open_reports)),
    h("div", { class: "card" },
      h("h2", {}, "Profile"),
      h("p", {}, h("span", { class: "muted" }, "ID "), h("code", {}, player.id)),
      h("p", {}, badge(player.active ? "active" : "banned", player.active ? "ok" : "bad"), " ", data.muted_until ? badge(`muted until ${when(data.muted_until)}`, "warn") : null, " ", `Language ${player.language} · joined ${when(player.created_at)}`),
      data.skill ? h("p", { class: "muted" }, `Hidden skill μ ${data.skill.mu.toFixed(2)} · σ ${data.skill.sigma.toFixed(2)} · ${data.skill.matches} rated matches`) : null,
      h("p", { class: "muted" }, `Cosmetics: ${data.cosmetics.length ? data.cosmetics.join(", ") : "none"}`)),
    h("div", { class: "card" }, h("h2", {}, "Recent matches"), matchTable(data.recent_matches)));
}

function matchTable(rows) {
  return table([
    { label: "Finished", render: (row) => when(row.finished_at) },
    { label: "Mode", render: (row) => row.mode ?? "custom" },
    { label: "Players", render: (row) => row.players.join(", ") },
    { label: "Result", render: (row) => outcomeText(row.outcome) },
  ], rows, (row) => (location.hash = `#/matches/${row.id}`));
}

async function matches({ param }) {
  if (param) {
    const data = await api.get(`/admin/matches/${encodeURIComponent(param)}`);
    return h("div", {},
      header("Match", h("a", { class: "button", href: "#/matches" }, "Back")),
      h("div", { class: "grid" },
        stat("Plays", data.total_plays),
        stat("Vettus", data.total_vettus),
        stat("Biggest pile", data.biggest_pile ? data.biggest_pile.cards : 0)),
      h("div", { class: "card" }, h("p", { class: "muted" }, outcomeText(data.outcome)), table([
        { label: "Seat", num: true, render: (s) => s.seat + 1 },
        { label: "Kind", render: (s) => (s.bot ? badge("bot") : badge("human", "ok")) },
        { label: "Plays", num: true, render: (s) => s.plays },
        { label: "Vettus given", num: true, render: (s) => s.cuts_given },
        { label: "Cards picked", num: true, render: (s) => s.cards_picked },
        { label: "Place", render: (s) => (s.donkey ? badge("Donkey", "bad") : (s.place ?? "—")) },
      ], data.seats)));
  }
  return h("div", {}, header("Matches"), h("div", { class: "card" }, matchTable(await api.get("/admin/matches"))));
}

async function fairPlay({ refresh }) {
  const status = new URLSearchParams(location.hash.split("?")[1] ?? "").get("status") ?? "open";
  const rows = await api.get(`/admin/fair-play${query({ status })}`);
  const filter = h("select", { "aria-label": "Case status", onchange: (event) => (location.hash = `#/fair-play?status=${event.target.value}`) },
    ["open", "dismissed", "confirmed"].map((value) => h("option", { value, selected: value === status }, value)));
  return h("div", {},
    header("Fair play", filter),
    h("p", { class: "muted" }, "The engine only flags. A moderator always decides; nothing is sanctioned automatically."),
    h("div", { class: "card" }, table([
      { label: "Player", render: (row) => h("a", { href: `#/players/${row.player_id}` }, row.player_id.slice(0, 8)) },
      { label: "Score", num: true, render: (row) => badge(row.score, row.score >= 75 ? "bad" : "warn") },
      { label: "Signals", render: (row) => (row.stats.signals ?? []).map((s) => `${s.name} (+${s.points})`).join(", ") },
      { label: "Engine match", render: (row) => (row.stats.engine_match_rate == null ? "—" : `${Math.round(row.stats.engine_match_rate * 100)}%`) },
      { label: "Median think", render: (row) => (row.stats.median_think_ms == null ? "—" : `${Math.round(row.stats.median_think_ms)} ms`) },
      { label: "Opened", render: (row) => when(row.created_at) },
      { label: "", render: (row) => (row.status === "open"
        ? h("button", { onclick: (event) => {
          event.stopPropagation();
          act("Resolve case", [{ name: "decision", label: "Decision", options: [["dismissed", "Dismiss"], ["confirmed", "Confirm cheating"]], value: "dismissed" }],
            (v) => api.post(`/admin/fair-play/${row.id}/resolve`, v), refresh, "Case resolved");
        } }, "Resolve")
        : h("span", { class: "muted" }, row.note ?? row.status)) },
    ], rows)));
}

async function reports({ refresh }) {
  const status = new URLSearchParams(location.hash.split("?")[1] ?? "").get("status") ?? "open";
  const rows = await api.get(`/admin/reports${query({ status })}`);
  const filter = h("select", { "aria-label": "Report status", onchange: (event) => (location.hash = `#/reports?status=${event.target.value}`) },
    ["open", "dismissed", "actioned"].map((value) => h("option", { value, selected: value === status }, value)));
  return h("div", {},
    header("Player reports", filter),
    h("div", { class: "card" }, table([
      { label: "Reported", render: (row) => h("a", { href: `#/players/${row.target_id}` }, row.target_id.slice(0, 8)) },
      { label: "Reason", render: (row) => badge(row.reason, row.reason === "cheating" ? "bad" : "warn") },
      { label: "Note", render: (row) => row.note ?? "—" },
      { label: "Match", render: (row) => (row.game_id ? h("a", { href: `#/matches/${row.game_id}` }, row.game_id.slice(0, 8)) : "—") },
      { label: "Filed", render: (row) => when(row.created_at) },
      { label: "", render: (row) => (row.status === "open"
        ? h("button", { onclick: () => act("Resolve report", [{ name: "decision", label: "Decision", options: [["dismissed", "Dismiss"], ["actioned", "Action taken"]], value: "dismissed" }],
          (v) => api.post(`/admin/reports/${row.id}/resolve`, v), refresh, "Report resolved") }, "Resolve")
        : h("span", { class: "muted" }, row.resolution ?? row.status)) },
    ], rows)));
}

async function seasons({ admin, refresh }) {
  const rows = await api.get("/admin/seasons");
  const isAdmin = admin.role === "admin";
  const create = () => act("Create a season", [
    { name: "theme", label: "Theme (e.g. Onam Ulsavam)", minlength: 3, maxlength: 60 },
    { name: "starts_at", label: "Starts", type: "datetime-local", parse: (value) => new Date(value).toISOString() },
    { name: "ends_at", label: "Ends", type: "datetime-local", parse: (value) => new Date(value).toISOString() },
  ], (v) => api.post("/admin/seasons", v), refresh, "Season created");
  return h("div", {},
    header("Seasons", isAdmin ? h("button", { class: "primary", onclick: create }, "New season") : null),
    h("div", { class: "card" }, table([
      { label: "Theme", render: (row) => row.theme },
      { label: "Starts", render: (row) => when(row.starts_at) },
      { label: "Ends", render: (row) => when(row.ends_at) },
      { label: "Status", render: (row) => (row.closed_at ? badge("closed") : new Date(row.ends_at) < new Date() ? badge("ready to close", "warn") : badge("live", "ok")) },
      { label: "", render: (row) => (isAdmin && !row.closed_at && new Date(row.ends_at) < new Date()
        ? h("button", { onclick: () => act(`Close ${row.theme}`, [], (v) => api.post(`/admin/seasons/${row.id}/close`, v), refresh, "Season closed") }, "Close & pay rewards")
        : null) },
    ], rows)));
}

async function store() {
  const rows = await api.get("/admin/store");
  return h("div", {}, header("Store"), h("p", { class: "muted" }, "Cosmetics are bought with earned coins only. Festival items sell only inside their window."),
    h("div", { class: "card" }, table([
      { label: "Item", render: (row) => row.label },
      { label: "SKU", render: (row) => h("code", {}, row.sku) },
      { label: "Slot", render: (row) => row.slot },
      { label: "Price", num: true, render: (row) => row.price },
      { label: "Festival", render: (row) => row.festival ?? "—" },
      { label: "On sale", render: (row) => badge(row.available ? "yes" : "no", row.available ? "ok" : "") },
      { label: "Owners", num: true, render: (row) => row.owners },
    ], rows)));
}

async function flags({ admin, refresh }) {
  const rows = await api.get("/admin/flags");
  const edit = (row) => {
    const options = typeof row.value === "boolean" ? [["true", "On"], ["false", "Off"]] : null;
    act(`Change ${row.key}`, [{
      name: "value",
      label: row.description,
      value: String(row.value),
      options,
      type: typeof row.value === "number" ? "number" : "text",
      optional: typeof row.value === "string",
      parse: (value) => (options ? value === "true" : typeof row.value === "number" ? Number(value) : value),
    }], (v) => api.put(`/admin/flags/${row.key}`, v), refresh, "Flag updated");
  };
  return h("div", {}, header("Runtime flags"), h("p", { class: "muted" }, "Changes apply to every server within seconds. Secrets and timers are not flags."),
    h("div", { class: "card" }, table([
      { label: "Flag", render: (row) => h("code", {}, row.key) },
      { label: "Value", render: (row) => (typeof row.value === "boolean" ? badge(row.value ? "on" : "off", row.value ? "ok" : "bad") : String(row.value || "—")) },
      { label: "What it does", render: (row) => row.description },
      { label: "", render: (row) => (admin.role === "admin" ? h("button", { onclick: () => edit(row) }, "Change") : null) },
    ], rows)));
}

async function ai({ refresh }) {
  const usage = Object.entries(await api.get("/admin/ai/usage")).sort(([a], [b]) => a.localeCompare(b));
  const reindex = () => act("Re-embed the rules for RAG", [], (v) => api.post("/admin/ai/reindex", v), refresh, "Rules re-indexed");
  return h("div", {}, header("AI", h("button", { onclick: reindex }, "Re-index rules")),
    h("p", { class: "muted" }, "Counters for today: calls, failures, tokens, Gemini vs template wording, rejected outputs and prompt versions."),
    h("div", { class: "card" }, table([
      { label: "Counter", render: ([key]) => h("code", {}, key) },
      { label: "Today", num: true, render: ([, value]) => value },
    ], usage)));
}

async function seasonCues({ refresh }) {
  const rows = await api.get("/admin/season-cues");
  const create = () => act("Create a seasonal cue", [
    { name: "pack_key", label: "Pack key", placeholder: "grimoire-awakening-v1", maxlength: 80 },
    { name: "character_id", label: "Character ID", placeholder: "ashblade", maxlength: 40 },
    { name: "moment", label: "Scene", options: [["strike", "Strike"], ["victory", "Victory"], ["transform", "Transformation"]], value: "strike" },
  ], (value) => api.post("/admin/season-cues", value), refresh, "Cue created");
  const actions = { english: "Draft English", japanese: "Draft Japanese", review: "Review and publish" };
  const advance = (cue) => {
    const fields = cue.stage === "review" ? [
      { name: "en", label: "English", value: cue.en, maxlength: 180 },
      { name: "ja", label: "Japanese", value: cue.ja, maxlength: 180 },
    ] : [];
    return act(actions[cue.stage], fields, (value) => api.post(
      `/admin/season-cues/${cue.id}/advance`, { ...value, stage: cue.stage },
    ), refresh, cue.stage === "review" ? "Cue published" : "Draft saved");
  };
  return h("div", {}, header("Season cues", h("button", { class: "primary", onclick: create }, "New cue")),
    h("div", { class: "card" }, table([
      { label: "Pack and character", render: (cue) => `${cue.pack_key} · ${cue.character_id}` },
      { label: "Scene", render: (cue) => cue.moment },
      { label: "English", render: (cue) => cue.en ?? "—" },
      { label: "Japanese", render: (cue) => cue.ja ?? "—" },
      { label: "Status", render: (cue) => actions[cue.stage]
        ? h("button", { onclick: () => advance(cue) }, actions[cue.stage])
        : badge("published", "ok") },
    ], rows)));
}

async function users({ admin, refresh }) {
  const rows = await api.get("/admin/users");
  const roles = [["viewer", "Viewer"], ["moderator", "Moderator"], ["admin", "Admin"]];
  const create = () => act("Add an admin account", [
    { name: "username", label: "Username (lowercase)" },
    { name: "password", label: "Temporary password (12+ characters)", type: "password", minlength: 12 },
    { name: "role", label: "Role", options: roles, value: "viewer" },
  ], (v) => api.post("/admin/users", v), refresh, "Account created");
  return h("div", {}, header("Admin users", h("button", { class: "primary", onclick: create }, "Add account")),
    h("div", { class: "card" }, table([
      { label: "Username", render: (row) => row.username },
      { label: "Role", render: (row) => row.role },
      { label: "Status", render: (row) => badge(row.active ? "active" : "disabled", row.active ? "ok" : "bad") },
      { label: "2FA", render: (row) => badge(row.totp_enabled ? "on" : "off", row.totp_enabled ? "ok" : "warn") },
      { label: "Last sign-in", render: (row) => when(row.last_login_at) },
      { label: "", render: (row) => (row.id === admin.id ? h("span", { class: "muted" }, "you") : h("div", { class: "row" },
        h("button", { onclick: () => act(`Role for ${row.username}`, [{ name: "role", label: "Role", options: roles, value: row.role }], (v) => api.put(`/admin/users/${row.id}`, v), refresh) }, "Role"),
        h("button", { class: row.active ? "danger" : "", onclick: () => act(`${row.active ? "Disable" : "Enable"} ${row.username}`, [], (v) => api.put(`/admin/users/${row.id}`, { ...v, active: !row.active }), refresh) }, row.active ? "Disable" : "Enable"))) },
    ], rows)));
}

async function seasonMedia({ refresh }) {
  const rows = await api.get("/admin/season-media");
  const scenes = [["strike", "Strike"], ["victory", "Victory"], ["transform", "Transformation"]];
  const upload = () => act("Upload rig or approved recording", [
    { name: "pack_key", label: "Pack key", placeholder: "grimoire-awakening-v2", maxlength: 80 },
    { name: "character_id", label: "Character ID", placeholder: "ashblade", maxlength: 40 },
    { name: "slot", label: "Asset", options: [
      ["model", "Rigged GLB"],
      ...scenes.flatMap(([id, label]) => [[id + ":en", label + " · English WAV"], [id + ":ja", label + " · Japanese WAV"]]),
    ], value: "model" },
    { name: "file", label: "Asset file", type: "file", accept: ".glb,.wav" },
  ], (value) => {
    const form = new FormData();
    for (const [key, field] of Object.entries(value)) form.append(key, field);
    return api.post("/admin/season-media", form);
  }, refresh, "Uploaded for review");
  const review = (row, decision) => act(
    decision === "publish" ? "Approve and publish this asset" : "Withdraw this asset",
    [],
    (value) => api.post(`/admin/season-media/${row.id}/review`, { ...value, decision }),
    refresh,
  );
  return h("div", {}, header("Season media", h("button", { onclick: upload }, "Upload asset")),
    h("div", { class: "card" }, table([
      { label: "Pack and character", render: (row) => `${row.pack_key} · ${row.character_id}` },
      { label: "Asset", render: (row) => row.slot },
      { label: "Created", render: (row) => when(row.created_at) },
      { label: "Preview", render: (row) => row.withdrawn_at ? null : h("a", {
        href: `/api/v1/admin/season-media/${row.id}/preview`, target: "_blank", rel: "noopener",
      }, row.slot === "model" ? "Open GLB" : "Listen") },
      { label: "Status", render: (row) => row.withdrawn_at ? badge("withdrawn")
        : row.published_at ? badge("published", "ok") : badge("pending review", "warn") },
      { label: "Action", render: (row) => row.withdrawn_at ? null
        : row.published_at ? h("button", { onclick: () => review(row, "withdraw") }, "Withdraw")
          : h("button", { onclick: () => review(row, "publish") }, "Approve") },
    ], rows)));
}

async function audit() {
  const rows = await api.get("/admin/audit");
  return h("div", {}, header("Audit log"), h("div", { class: "card" }, table([
    { label: "When", render: (row) => when(row.at) },
    { label: "Action", render: (row) => h("code", {}, row.action) },
    { label: "Reason", render: (row) => row.reason },
    { label: "Admin", render: (row) => h("code", {}, row.admin_id.slice(0, 8)) },
    { label: "Request", render: (row) => h("code", {}, row.request_id.slice(0, 8)) },
  ], rows)));
}

async function security({ admin, refresh }) {
  const me = await api.get("/admin/auth/me");
  const body = h("div", { class: "card" });
  if (me.admin.totp_enabled) {
    body.append(h("h2", {}, "Two-factor sign-in"), h("p", {}, badge("On", "ok"), " Your account asks for an authenticator code at sign-in."));
  } else {
    const setup = async () => {
      const data = await api.post("/admin/auth/totp/setup");
      body.replaceChildren(
        h("h2", {}, "Set up two-factor sign-in"),
        h("p", {}, "Add this key to your authenticator app (Google Authenticator, Aegis, 1Password…), then enter the 6-digit code it shows."),
        h("p", { class: "qr-secret mono" }, data.secret),
        h("p", { class: "muted mono qr-secret" }, data.uri),
        h("button", { class: "primary", onclick: async () => {
          const result = await ask("Confirm the code", [{ name: "code", label: "6-digit code", maxlength: 6 }], (v) => api.post("/admin/auth/totp/confirm", v));
          if (result) {
            toast("Two-factor sign-in is on");
            refresh();
          }
        } }, "Enter code"));
    };
    body.append(h("h2", {}, "Two-factor sign-in"), h("p", {}, badge("Off", "warn"), " Protect this account with an authenticator code."),
      h("button", { class: "primary", onclick: setup }, "Set up"));
  }
  return h("div", {}, header("Security"), h("div", { class: "card" }, h("p", {}, `Signed in as ${admin.username} (${admin.role}).`)), body);
}

export const VIEWS = {
  dashboard: { title: "Dashboard", render: dashboard },
  players: { title: "Players", render: players },
  matches: { title: "Matches", render: matches },
  reports: { title: "Reports", render: reports, roles: MOD },
  "fair-play": { title: "Fair play", render: fairPlay, roles: MOD },
  seasons: { title: "Seasons", render: seasons },
  store: { title: "Store", render: store },
  flags: { title: "Runtime flags", render: flags },
  ai: { title: "AI", render: ai, roles: ADMIN },
  "season-cues": { title: "Season cues", render: seasonCues, roles: ADMIN },
  "season-media": { title: "Season media", render: seasonMedia, roles: ADMIN },
  users: { title: "Admin users", render: users, roles: ADMIN },
  audit: { title: "Audit log", render: audit, roles: ADMIN },
  security: { title: "Security", render: security },
};
