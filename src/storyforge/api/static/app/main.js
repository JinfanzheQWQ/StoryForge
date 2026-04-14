import { bindEvents } from "./events.js";
import { loadBootstrap, refreshTasks } from "./refresh.js";
import { hydrateStateFromLocation } from "./route_state.js";

export async function initApp() {
  hydrateStateFromLocation();
  bindEvents();
  await loadBootstrap();
  await refreshTasks();
  window.setInterval(() => {
    void refreshTasks();
  }, 3000);
}
