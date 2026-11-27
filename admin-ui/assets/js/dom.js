// Tiny DOM helpers. Text always goes in through textContent, never innerHTML,
// so player names and API data cannot inject markup.

export function h(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs ?? {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      element.addEventListener(key.slice(2), value);
    } else if (key === "class") {
      element.className = value;
    } else if (value === true) {
      element.setAttribute(key, "");
    } else {
      element.setAttribute(key, String(value));
    }
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

export function mount(target, ...children) {
  target.replaceChildren(...children.flat().filter(Boolean));
}

export function toast(message, kind = "") {
  const item = h("div", { class: `toast ${kind}` }, message);
  document.getElementById("toasts").append(item);
  setTimeout(() => item.remove(), 4500);
}

export function badge(text, kind = "") {
  return h("span", { class: `badge ${kind}` }, text);
}

export function when(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

export function table(columns, rows, onRow) {
  if (!rows.length) return h("div", { class: "empty" }, "Nothing here yet.");
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      {},
      h("thead", {}, h("tr", {}, columns.map((column) => h("th", {}, column.label)))),
      h(
        "tbody",
        {},
        rows.map((row) =>
          h(
            "tr",
            { class: onRow ? "clickable" : "", onclick: onRow ? () => onRow(row) : null },
            columns.map((column) =>
              h("td", { class: column.num ? "num" : "" }, column.render(row)),
            ),
          ),
        ),
      ),
    ),
  );
}

// A modal form. Resolves with field values, or null if cancelled.
// `submit` may throw; its message is shown and the dialog stays open.
export function ask(title, fields, submit, confirmLabel = "Confirm") {
  const dialog = document.getElementById("dialog");
  const form = document.getElementById("dialog-form");
  const error = document.getElementById("dialog-error");
  document.getElementById("dialog-title").textContent = title;
  const button = document.getElementById("dialog-submit");
  button.textContent = confirmLabel;
  button.disabled = false;
  const inputs = {};
  mount(
    document.getElementById("dialog-fields"),
    fields.map((field) => {
      let input;
      if (field.options) {
        input = h(
          "select",
          { name: field.name },
          field.options.map(([value, label]) =>
            h("option", { value, selected: value === field.value }, label),
          ),
        );
      } else {
        input = h("input", {
          name: field.name,
          type: field.type ?? "text",
          value: field.value ?? "",
          placeholder: field.placeholder ?? "",
          required: field.optional ? null : true,
          minlength: field.minlength,
          maxlength: field.maxlength ?? 200,
          autocomplete: "off",
          accept: field.accept,
        });
      }
      inputs[field.name] = { input, field };
      return h("label", {}, field.label, input);
    }),
  );
  error.hidden = true;
  return new Promise((resolve) => {
    const cleanup = () => {
      form.onsubmit = null;
      document.getElementById("dialog-cancel").onclick = null;
      dialog.close();
    };
    document.getElementById("dialog-cancel").onclick = () => {
      cleanup();
      resolve(null);
    };
    form.onsubmit = async (event) => {
      event.preventDefault();
      if (button.disabled) return;
      button.disabled = true;
      const values = {};
      for (const [name, { input, field }] of Object.entries(inputs)) {
        values[name] = field.type === "file"
          ? input.files[0]
          : field.parse ? field.parse(input.value) : input.value.trim();
      }
      try {
        const result = submit ? await submit(values) : values;
        cleanup();
        resolve(result ?? values);
      } catch (failure) {
        error.textContent = failure.message;
        error.hidden = false;
      } finally {
        button.disabled = false;
      }
    };
    dialog.showModal();
  });
}

export const reasonField = { name: "reason", label: "Reason (kept in the audit log)", minlength: 3, maxlength: 120 };
