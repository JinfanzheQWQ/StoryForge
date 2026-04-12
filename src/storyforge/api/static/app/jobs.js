import { createNovelProject, createStageTask } from "./api.js";
import { elements } from "./dom.js";
import { readProjectSubmission, setSubmitPending, setSubmitStatus } from "./form.js";
import { refreshTasks } from "./refresh.js";
import { state } from "./state.js";
import { compactId } from "./utils.js";

export async function submitProject(event) {
  event.preventDefault();
  if (!elements.form.reportValidity()) {
    setSubmitStatus("表单还有未填写或不合法的字段。");
    return;
  }

  setSubmitPending(true);
  setSubmitStatus("任务提交中...");

  const { projectId, payload } = readProjectSubmission();

  try {
    const result = await createNovelProject(payload);
    state.lastSubmittedTaskId = result.task_id;
    state.selectedProjectId = result.project_id;
    state.selectedProjectTaskId = result.task_id;
    state.selectedQueueTaskId = result.task_id;
    state.currentPage = "queue";
    state.queueDetailTab = "overview";
    setSubmitStatus(
      projectId
        ? `已为当前故事创建新的文本版本：${compactId(result.task_id)}`
        : `故事已创建，文本任务已开始：${compactId(result.task_id)}`,
    );
    await refreshTasks();
  } catch (error) {
    setSubmitStatus(error.message || "提交失败。");
  } finally {
    setSubmitPending(false);
  }
}

export async function submitStageJob(endpoint, payload, successMessage) {
  elements.pollIndicator.textContent = "任务提交中";
  const result = await createStageTask(endpoint, payload);
  state.lastSubmittedTaskId = result.task_id;
  state.selectedProjectId = result.project_id;
  state.selectedProjectTaskId = payload.source_task_id;
  state.selectedQueueTaskId = result.task_id;
  state.currentPage = "queue";
  elements.pollIndicator.textContent = `${successMessage}：${compactId(result.task_id)}`;
  await refreshTasks();
}
