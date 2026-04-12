import { bindEvents } from "./events.js";
import { loadBootstrap, refreshTasks } from "./refresh.js";

export async function initApp() {
  bindEvents();
  await loadBootstrap();
  await refreshTasks();
  window.setInterval(() => {
    void refreshTasks();
  }, 3000);
}
