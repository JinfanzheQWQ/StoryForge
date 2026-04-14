async function parseErrorPayload(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function buildApiErrorMessage(response) {
  const payload = await parseErrorPayload(response);

  if (response.status === 422 && Array.isArray(payload?.detail)) {
    const detail = payload.detail
      .map((item) => {
        const location = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "body";
        return `${location}: ${item.msg}`;
      })
      .join("；");
    return `提交失败：${detail}`;
  }

  if (typeof payload?.detail === "string" && payload.detail) {
    return `提交失败：${payload.detail}`;
  }

  return `提交失败，HTTP ${response.status}`;
}

export async function fetchBootstrap() {
  const response = await fetch("/v1/ui/bootstrap");
  if (!response.ok) {
    throw new Error(await buildApiErrorMessage(response));
  }
  return response.json();
}

export async function fetchTasks() {
  const response = await fetch("/v1/tasks");
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

export async function fetchProjects() {
  const response = await fetch("/v1/projects");
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

export async function fetchProjectDetail(projectId) {
  const response = await fetch(`/v1/projects/${projectId}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

export async function deleteProject(projectId) {
  const response = await fetch(`/v1/projects/${projectId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await buildApiErrorMessage(response));
  }
  return response.json();
}

export async function fetchStorySource(projectId, sourceTaskId) {
  const response = await fetch(`/v1/projects/${projectId}/story-source/${sourceTaskId}`);
  if (!response.ok) {
    throw new Error(await buildApiErrorMessage(response));
  }
  return response.json();
}

export async function updateStorySource(projectId, sourceTaskId, payload) {
  const response = await fetch(`/v1/projects/${projectId}/story-source/${sourceTaskId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await buildApiErrorMessage(response));
  }
  return response.json();
}

export async function fetchTaskArtifacts(taskId) {
  const response = await fetch(`/v1/tasks/${taskId}/artifacts`);
  if (!response.ok) {
    return null;
  }
  return response.json();
}

export async function createNovelProject(payload) {
  const response = await fetch("/v1/projects/novel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await buildApiErrorMessage(response));
  }
  return response.json();
}

export async function createStageTask(endpoint, payload) {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await buildApiErrorMessage(response));
  }
  return response.json();
}
