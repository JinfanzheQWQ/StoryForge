import { elements } from "./dom.js";

let pendingResolve = null;
let listenersBound = false;

function resolvePending(value) {
  if (!pendingResolve) {
    return;
  }
  const resolve = pendingResolve;
  pendingResolve = null;
  elements.confirmDialog.classList.add("hidden");
  elements.confirmDialog.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");
  resolve(value);
}

function bindConfirmDialogEvents() {
  if (listenersBound || !elements.confirmDialog) {
    return;
  }
  listenersBound = true;

  elements.confirmCancelButton.addEventListener("click", () => resolvePending(false));
  elements.confirmSubmitButton.addEventListener("click", () => resolvePending(true));
  elements.confirmDialog.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.closest("[data-confirm-cancel]")) {
      resolvePending(false);
    }
  });
  window.addEventListener("keydown", (event) => {
    if (!pendingResolve) {
      return;
    }
    if (event.key === "Escape") {
      resolvePending(false);
    }
  });
}

function renderDetailItems(details) {
  elements.confirmDetails.innerHTML = "";
  details.forEach((item) => {
    const element = document.createElement("li");
    element.textContent = item;
    elements.confirmDetails.appendChild(element);
  });
}

export function askConfirmation({
  eyebrow = "Confirm",
  title,
  message,
  details = [],
  confirmLabel = "确认",
  cancelLabel = "取消",
}) {
  if (!elements.confirmDialog) {
    return Promise.resolve(window.confirm(message || title || "确认执行这个操作吗？"));
  }

  bindConfirmDialogEvents();
  if (pendingResolve) {
    resolvePending(false);
  }

  elements.confirmEyebrow.textContent = eyebrow;
  elements.confirmTitle.textContent = title;
  elements.confirmMessage.textContent = message;
  elements.confirmSubmitButton.textContent = confirmLabel;
  elements.confirmCancelButton.textContent = cancelLabel;
  renderDetailItems(details);
  elements.confirmDialog.classList.remove("hidden");
  elements.confirmDialog.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  elements.confirmCancelButton.focus();

  return new Promise((resolve) => {
    pendingResolve = resolve;
  });
}

export function askProjectDeleteConfirmation({ title, taskCount }) {
  return askConfirmation({
    eyebrow: "Delete Project",
    title: `删除《${title || "未命名故事"}》？`,
    message: "删除后，这个项目不会再出现在故事资产和任务列表中。",
    details: [
      `会删除 ${taskCount} 条任务记录和项目元数据。`,
      "会同步删除该项目在 outputs 下已经生成的图片、视频和 JSON 产物目录。",
      "如果项目仍有排队中或运行中的任务，后端会拒绝删除。",
    ],
    confirmLabel: "确认删除",
    cancelLabel: "先保留",
  });
}
