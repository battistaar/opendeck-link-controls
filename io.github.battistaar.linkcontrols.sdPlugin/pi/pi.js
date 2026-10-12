// Shared property-inspector glue: every element with data-setting is loaded from and
// saved to the action's settings. Elements with data-show-if="setting=value" are only
// shown when that setting has that value.
function connectElgatoStreamDeckSocket(port, uuid, registerEvent, info, actionInfo) {
  const ws = new WebSocket("ws://localhost:" + port);
  actionInfo = JSON.parse(actionInfo);
  const settings = actionInfo.payload.settings || {};
  const fields = document.querySelectorAll("[data-setting]");

  ws.onopen = () => ws.send(JSON.stringify({ event: registerEvent, uuid: uuid }));

  const value = (el) => {
    if (el.type === "checkbox") return el.checked;
    if (el.type === "number" || el.type === "range") return Number(el.value);
    return el.value;
  };

  const updateVisibility = () => {
    document.querySelectorAll("[data-show-if]").forEach((el) => {
      const [key, want] = el.dataset.showIf.split("=");
      const field = document.querySelector(`[data-setting="${key}"]`);
      el.classList.toggle("hidden", String(value(field)) !== want);
    });
    document.querySelectorAll("output[for]").forEach((out) => {
      out.textContent = document.getElementById(out.htmlFor).value;
    });
  };

  const save = () => {
    const payload = {};
    fields.forEach((el) => { payload[el.dataset.setting] = value(el); });
    ws.send(JSON.stringify({ event: "setSettings", context: actionInfo.context, payload: payload }));
    updateVisibility();
  };

  fields.forEach((el) => {
    const stored = settings[el.dataset.setting];
    if (stored !== undefined && stored !== "") {
      if (el.type === "checkbox") el.checked = stored === true || stored === "true";
      else el.value = stored;
    }
    el.addEventListener("input", save);
  });
  updateVisibility();
}
