import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { getTaskArtifacts } from "../../api/artifacts";
import { getProject } from "../../api/projects";
import { queryKeys } from "../../api/queryKeys";
import { createStageTask } from "../../api/stageTasks";
import { getTask } from "../../api/tasks";
import type { CreateStageTaskRequest, ProjectDetail, StageTaskKind, StageTaskResponse, TaskRecord } from "../../types";
import { resolveStoryboardSelection } from "../projects/creatorStoryboardOptions";
import { StageActionRail, WorkspaceSection } from "./workspaceSections";
import {
  areCharacterImagesReady,
  buildSceneRows,
  getErrorMessage,
  getStageCompletionState,
  hasEditableStorySource,
  labelTaskOperation,
  productionSteps,
  resolveEditableSourceTaskId,
  resolveRestorableActiveTaskId,
  resolveSourceTask,
  selectCharacter,
  selectSceneRow,
  selectSegment,
  sectionForTaskType
} from "./workspaceModel";

export function ProjectWorkspacePage() {
  const { projectId, taskId } = useParams();
  const queryClient = useQueryClient();
  const [activeSection, setActiveSectionState] = useState(() => readStoredWorkspaceSection(projectId));
  const [selectedCharacterName, setSelectedCharacterName] = useState<string>("");
  const [selectedSceneId, setSelectedSceneId] = useState<string>("");
  const [selectedSegmentId, setSelectedSegmentId] = useState<string>("");
  const [submittedTaskId, setSubmittedTaskId] = useState<string>("");
  const [stageSubmitMessage, setStageSubmitMessage] = useState<string>("");
  const [imageOptions, setImageOptions] = useState<ImageGenerationOptions>(DEFAULT_WORKSPACE_IMAGE_OPTIONS);

  const projectQuery = useQuery({
    queryKey: queryKeys.project(projectId),
    queryFn: () => getProject(projectId || ""),
    enabled: Boolean(projectId)
  });

  const projectTasks = projectQuery.data?.tasks || [];
  const activeTaskId = resolveRestorableActiveTaskId({
    latestTaskId: projectQuery.data?.latest_task_id,
    routeTaskId: taskId,
    submittedTaskId,
    tasks: projectTasks
  });
  const taskQuery = useQuery({
    queryKey: queryKeys.task(activeTaskId),
    queryFn: () => getTask(activeTaskId),
    enabled: Boolean(activeTaskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 2000 : false;
    }
  });
  const activeTask =
    (taskQuery.data?.task_id === activeTaskId ? taskQuery.data : undefined) ||
    projectTasks.find((task) => task.task_id === activeTaskId);
  const sourceTaskId = useMemo(
    () =>
      resolveEditableSourceTaskId({
        activeTask,
        fallbackTaskId: taskId || projectQuery.data?.latest_task_id || activeTaskId,
        tasks: projectTasks
      }),
    [activeTask, activeTaskId, projectQuery.data?.latest_task_id, projectTasks, taskId]
  );
  const sourceTask = resolveSourceTask({
    activeTask,
    sourceTaskId,
    tasks: projectTasks
  });
  const isSourceTaskReady = Boolean(sourceTaskId && sourceTask?.status === "completed" && hasEditableStorySource(sourceTask));

  const artifactsQuery = useQuery({
    queryKey: queryKeys.artifacts(sourceTaskId),
    queryFn: () => getTaskArtifacts(sourceTaskId),
    enabled: Boolean(sourceTaskId) && isSourceTaskReady
  });

  const artifacts = artifactsQuery.data;
  const segmentContractProgress = artifacts?.segment_contract_progress || null;
  const characters = artifacts?.character_images || [];
  const scenes = artifacts?.scenes || [];
  const plannedSegments = artifacts?.planned_segments || [];
  const sceneRows = useMemo(
    () => buildSceneRows(plannedSegments, artifacts?.scene_frames || []),
    [artifacts?.scene_frames, plannedSegments]
  );
  const selectedSegment = useMemo(
    () => selectSegment(plannedSegments, selectedSegmentId),
    [plannedSegments, selectedSegmentId]
  );
  const selectedCharacter = useMemo(
    () => selectCharacter(characters, selectedCharacterName),
    [characters, selectedCharacterName]
  );
  const selectedScene = useMemo(
    () => selectSceneRow(sceneRows, selectedSceneId, selectedSegment?.scene_id),
    [sceneRows, selectedSceneId, selectedSegment?.scene_id]
  );

  const characterCount = artifacts?.character_images?.length || 0;
  const charactersReady = areCharacterImagesReady(characters);
  const sceneCount = scenes.length || artifacts?.scene_frames?.length || 0;
  const clipCount = artifacts?.rendered_clips?.length || 0;
  const readySegments = plannedSegments.filter((segment) => segment.rendered_clip?.url).length;
  const hasSceneStructure = scenes.length > 0 || sceneRows.length > 0;
  const activeTaskType = activeTask?.task_type || activeTask?.stage;
  const completion = getStageCompletionState({
    activeTaskStatus: activeTask?.status,
    activeTaskType,
    charactersReady,
    hasSceneStructure,
    plannedSegmentCount: plannedSegments.length,
    segmentContractProgress
  });
  const projectTitle = projectQuery.data?.story_title || projectQuery.data?.title_hint || artifacts?.story_title || "项目工作台";
  const stageMutation = useMutation({
    mutationFn: ({ payload, stage }: { payload: CreateStageTaskRequest; stage: StageTaskKind }) =>
      createStageTask(stage, payload),
    onSuccess: (response, variables) => {
      setSubmittedTaskId(response.task_id);
      setStageSubmitMessage(buildStageSubmitMessage(variables.stage, response));
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.task(response.task_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.artifacts(variables.payload.source_task_id) });
    },
    onError: () => {
      setStageSubmitMessage("");
    }
  });
  const isWaitingForTaskRecord = Boolean(activeTaskId) && taskQuery.isFetching && !activeTask;
  const isWaitingForProjectRecord = Boolean(projectId) && projectQuery.isLoading;
  const isTaskBusy =
    isWaitingForProjectRecord ||
    stageMutation.isPending ||
    isWaitingForTaskRecord ||
    activeTask?.status === "queued" ||
    activeTask?.status === "running";
  const stageBlockReason = getStageBlockReason({
    isBusy: isTaskBusy,
    sourceTaskId,
    sourceStatus: sourceTask?.status,
    sourceTaskReady: isSourceTaskReady
  });

  useEffect(() => {
    setActiveSectionState(readStoredWorkspaceSection(projectId));
  }, [projectId]);

  useEffect(() => {
    setImageOptions(resolveTaskImageOptions(sourceTask));
  }, [sourceTask?.task_id]);

  useEffect(() => {
    if (!projectId || !taskQuery.data) return;
    queryClient.setQueryData<ProjectDetail>(queryKeys.project(projectId), (current) =>
      mergeTaskIntoProject(current, taskQuery.data)
    );
  }, [projectId, queryClient, taskQuery.data]);

  useEffect(() => {
    if (activeTask?.status !== "completed" || !sourceTaskId) return;
    void queryClient.invalidateQueries({ queryKey: queryKeys.artifacts(sourceTaskId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.storySource(projectId, sourceTaskId) });
    void queryClient.refetchQueries({ queryKey: queryKeys.artifacts(sourceTaskId), type: "active" });
    void queryClient.refetchQueries({ queryKey: queryKeys.storySource(projectId, sourceTaskId), type: "active" });
    void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.projects() });
    void queryClient.refetchQueries({ queryKey: queryKeys.project(projectId), type: "active" });
  }, [activeTask?.status, activeTask?.task_id, projectId, queryClient, sourceTaskId]);

  useEffect(() => {
    const taskSection = sectionForTaskType(activeTaskType);
    if (!taskSection) return;
    if (activeTask?.status !== "queued" && activeTask?.status !== "running") return;
    setActiveSection(taskSection);
  }, [activeTask?.status, activeTaskType]);

  const stageStatus = getStageStatusLabel({
    activeTaskId,
    isFetching: isWaitingForTaskRecord,
    isMutationPending: stageMutation.isPending,
    mutationStage: stageMutation.variables?.stage,
    status: activeTask?.status,
    taskType: activeTaskType
  });
  const runOperation = stageMutation.isPending
    ? labelTaskOperation(undefined, stageMutation.variables?.stage)
    : labelTaskOperation(activeTaskType);
  const stepProgress = productionSteps.map((step) => ({
    ...step,
    state: getStepState(step.section, {
      charactersReady,
      completion,
      plannedCount: plannedSegments.length,
      readySegments,
      sceneRowsReady: sceneRows.some((row) => row.ready)
    })
  }));
  const activeStepIndex = Math.max(
    productionSteps.findIndex((step) => step.section === activeSection),
    0
  );
  const activeStep = productionSteps[activeStepIndex] || productionSteps[0];
  const previousStep = productionSteps[activeStepIndex - 1];
  const nextStep = productionSteps[activeStepIndex + 1];
  const workspaceModeClass = `studio-mode-${activeStep.mode}`;

  function setActiveSection(section: string) {
    const nextSection = productionSteps.some((step) => step.section === section) ? section : productionSteps[0].section;
    setActiveSectionState(nextSection);
    setStageSubmitMessage("");
    writeStoredWorkspaceSection(projectId, nextSection);
  }

  function submitStage(stage: StageTaskKind, extraPayload: Partial<CreateStageTaskRequest> = {}) {
    if (!projectId) {
      setStageSubmitMessage("缺少项目 ID，无法提交生成任务。");
      return;
    }
    if (!sourceTaskId || !isSourceTaskReady || isTaskBusy) {
      setStageSubmitMessage(stageBlockReason || "当前状态不能提交生成任务。");
      return;
    }
    setStageSubmitMessage(`正在提交${labelTaskOperation(undefined, stage)}...`);
    stageMutation.mutate({
      stage,
      payload: {
        project_id: projectId,
        source_task_id: sourceTaskId,
        ...buildImageGenerationPayload(stage, imageOptions),
        ...extraPayload
      }
    });
  }

  function updateImageModel(model: string) {
    const resolved = resolveStoryboardSelection({
      aspectRatio: imageOptions.aspectRatio,
      model,
      size: imageOptions.size
    });
    setImageOptions({
      aspectRatio: resolved.aspectRatio,
      model: resolved.model,
      size: resolved.size
    });
  }

  function updateImageSize(size: string) {
    const resolved = resolveStoryboardSelection({
      aspectRatio: imageOptions.aspectRatio,
      model: imageOptions.model,
      size
    });
    setImageOptions((current) => ({
      ...current,
      aspectRatio: resolved.aspectRatio,
      size: resolved.size
    }));
  }

  function handleTaskAccepted(taskId: string) {
    setSubmittedTaskId(taskId);
    void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.projects() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.task(taskId) });
  }

  return (
    <section className={`studio-workspace workflow-page ${workspaceModeClass}`}>
      <section className="workflow-projectbar" aria-labelledby="workspace-title">
        <div className="workflow-project-title">
          <Link className="workflow-back" to="/console" aria-label="返回项目库">
            <ArrowLeft size={16} aria-hidden="true" />
          </Link>
          <div>
            <h2 id="workspace-title">{projectTitle}</h2>
            <span>{activeSection} · {runOperation}</span>
          </div>
        </div>

        <nav className="workflow-stepper" aria-label="生产步骤">
          {stepProgress.map((step, index) => (
            <button
              className={[
                "workflow-step",
                step.section === activeSection ? "active" : "",
                step.state === "complete" ? "complete" : ""
              ].filter(Boolean).join(" ")}
              key={step.section}
              type="button"
              onClick={() => setActiveSection(step.section)}
            >
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{step.title}</strong>
              <em>{labelStepState(step.state)}</em>
            </button>
          ))}
        </nav>

        <div className="workflow-commandbar">
          <div className="workflow-step-nav" aria-label="步骤切换">
            <button className="ghost-button" disabled={!previousStep || isTaskBusy} type="button" onClick={() => previousStep && setActiveSection(previousStep.section)}>
              上一步
            </button>
            <button className="primary-link" disabled={!nextStep || isTaskBusy} type="button" onClick={() => nextStep && setActiveSection(nextStep.section)}>
              下一步 <ArrowRight size={14} aria-hidden="true" />
            </button>
          </div>
        </div>
      </section>

      <div className="workflow-content-grid">
        <main className="workflow-main-board" aria-label="当前工作区">
          {stageMutation.isError ? <div className="error-callout">{getErrorMessage(stageMutation.error)}</div> : null}
          {!stageMutation.isError && stageSubmitMessage ? <div className="info-callout">{stageSubmitMessage}</div> : null}

          <StageActionRail
            activeSection={activeSection}
            activeTaskId={sourceTaskId}
            activeStep={activeStep}
            activeStepIndex={activeStepIndex}
            completion={completion}
            isBusy={isTaskBusy}
            imageOptions={imageOptions}
            mutationStage={stageMutation.variables?.stage}
            onImageAspectRatioChange={(aspectRatio) => setImageOptions((current) => ({ ...current, aspectRatio }))}
            onImageModelChange={updateImageModel}
            onImageSizeChange={updateImageSize}
            onSubmit={submitStage}
            stageStatus={stageStatus}
            stageBlockReason={stageBlockReason}
            selectedScene={selectedScene}
            selectedSegment={selectedSegment}
          />

          <WorkspaceSection
            activeSection={activeSection}
            activeTaskId={sourceTaskId}
            artifacts={artifacts}
            characterCount={characterCount}
            clipCount={clipCount}
            isSourceTaskReady={isSourceTaskReady}
            isTaskBusy={isTaskBusy}
            mutationStage={stageMutation.variables?.stage}
            onSubmit={submitStage}
            onTaskAccepted={handleTaskAccepted}
            plannedSegments={plannedSegments}
            projectId={projectId}
            readySegments={readySegments}
            sceneRows={sceneRows}
            sceneCount={sceneCount}
            segmentContractProgress={segmentContractProgress}
            stageBlockReason={stageBlockReason}
            selectedCharacterName={selectedCharacter?.character_name || selectedCharacter?.name || ""}
            selectedSceneId={selectedScene?.sceneId || ""}
            selectedSegment={selectedSegment}
            setSelectedCharacterName={setSelectedCharacterName}
            setSelectedSceneId={setSelectedSceneId}
            setSelectedSegmentId={setSelectedSegmentId}
          />
        </main>
      </div>
    </section>
  );
}

function getStepState(
  section: string,
  progress: {
    charactersReady: boolean;
    completion: { sceneStructureComplete: boolean; segmentContractsComplete: boolean };
    plannedCount: number;
    readySegments: number;
    sceneRowsReady: boolean;
  }
) {
  if (section === "小说") return "complete";
  if (section === "结构化信息") return progress.completion.segmentContractsComplete ? "complete" : "ready";
  if (section === "角色图") return progress.charactersReady ? "complete" : "ready";
  if (section === "场景母图") return progress.sceneRowsReady ? "complete" : "ready";
  if (section === "分段视频") {
    return progress.plannedCount > 0 && progress.readySegments >= progress.plannedCount ? "complete" : "ready";
  }
  return progress.readySegments > 0 ? "ready" : "pending";
}

function labelStepState(state: string) {
  if (state === "complete") return "已完成";
  if (state === "ready") return "可操作";
  return "等待";
}

function getStageBlockReason({
  isBusy,
  sourceTaskId,
  sourceStatus,
  sourceTaskReady
}: {
  isBusy: boolean;
  sourceTaskId: string;
  sourceStatus?: string;
  sourceTaskReady: boolean;
}) {
  if (!sourceTaskId) return "需要先创建并完成小说正文任务。";
  if (isBusy) {
    return "当前任务还在生成中，完成后才能继续生成下一步。";
  }
  if (sourceStatus && sourceStatus !== "completed") return "小说正文任务未完成，不能继续生成下一步。";
  if (!sourceTaskReady) return "正在读取小说正文源任务，完成后才能继续生成下一步。";
  return "";
}

function getStageStatusLabel({
  activeTaskId,
  isFetching,
  isMutationPending,
  mutationStage,
  status,
  taskType
}: {
  activeTaskId: string;
  isFetching: boolean;
  isMutationPending: boolean;
  mutationStage?: StageTaskKind;
  status?: string;
  taskType?: string;
}) {
  if (isMutationPending) return `正在提交${labelTaskOperation(undefined, mutationStage)}...`;
  if (!activeTaskId) return "尚未创建可继续生成的任务。";
  if (isFetching || !status) return `正在读取任务状态 · Task ${activeTaskId.slice(0, 8)}`;
  const operation = labelTaskOperation(taskType);
  if (status === "queued") return `${operation}排队中 · Task ${activeTaskId.slice(0, 8)}`;
  if (status === "running") return `${operation}生成中 · Task ${activeTaskId.slice(0, 8)}`;
  if (status === "completed") return `${operation}已完成 · Task ${activeTaskId.slice(0, 8)}`;
  if (status === "failed") return `${operation}失败 · Task ${activeTaskId.slice(0, 8)}`;
  return `${operation}${status} · Task ${activeTaskId.slice(0, 8)}`;
}

function buildStageSubmitMessage(stage: StageTaskKind, response: StageTaskResponse) {
  const operation = labelTaskOperation(undefined, stage);
  const taskLabel = `Task ${response.task_id.slice(0, 8)}`;
  if (response.status === "queued" || response.status === "running") {
    return `${operation}已提交 · ${taskLabel}`;
  }
  if (response.status === "completed") {
    return `${operation}已完成，已刷新当前产物 · ${taskLabel}`;
  }
  if (response.status === "failed") {
    return `${operation}失败 · ${taskLabel}`;
  }
  return `${operation}${response.status} · ${taskLabel}`;
}

export type ImageGenerationOptions = {
  aspectRatio: string;
  model: string;
  size: string;
};

const DEFAULT_WORKSPACE_IMAGE_OPTIONS: ImageGenerationOptions = {
  aspectRatio: "16:9",
  model: "doubao-seedream-4-5-251128",
  size: "2K"
};

function buildImageGenerationPayload(stage: StageTaskKind, options: ImageGenerationOptions): Partial<CreateStageTaskRequest> {
  if (!["characters", "scenes", "storyboards"].includes(stage)) {
    return {};
  }
  return {
    image_aspect_ratio: options.aspectRatio,
    image_model: options.model,
    image_size: options.size,
    storyboard_aspect_ratio: options.aspectRatio,
    storyboard_image_model: options.model,
    storyboard_size: options.size
  };
}

function resolveTaskImageOptions(sourceTask?: TaskRecord): ImageGenerationOptions {
  const payload = sourceTask?.payload || {};
  const result = sourceTask?.result || {};
  const brief = typeof payload.brief === "object" && payload.brief ? (payload.brief as Record<string, unknown>) : {};
  const model =
    stringValue(result.image_model) ||
    stringValue(result.storyboard_image_model) ||
    stringValue(payload.image_model) ||
    stringValue(payload.storyboard_image_model) ||
    stringValue(brief.image_model) ||
    stringValue(brief.storyboard_image_model) ||
    DEFAULT_WORKSPACE_IMAGE_OPTIONS.model;
  const size =
    stringValue(result.image_size) ||
    stringValue(result.storyboard_size) ||
    stringValue(payload.image_size) ||
    stringValue(payload.storyboard_size) ||
    stringValue(brief.image_size) ||
    stringValue(brief.storyboard_size) ||
    DEFAULT_WORKSPACE_IMAGE_OPTIONS.size;
  const aspectRatio =
    stringValue(result.image_aspect_ratio) ||
    stringValue(result.storyboard_aspect_ratio) ||
    stringValue(payload.image_aspect_ratio) ||
    stringValue(payload.storyboard_aspect_ratio) ||
    stringValue(brief.image_aspect_ratio) ||
    stringValue(brief.storyboard_aspect_ratio) ||
    DEFAULT_WORKSPACE_IMAGE_OPTIONS.aspectRatio;
  const resolved = resolveStoryboardSelection({ aspectRatio, model, size });
  return {
    aspectRatio: resolved.aspectRatio,
    model: resolved.model,
    size: resolved.size
  };
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function mergeTaskIntoProject(project: ProjectDetail | undefined, task: TaskRecord) {
  if (!project || project.project_id !== task.project_id) return project;
  const tasks = project.tasks || [];
  const nextTasks = tasks.some((item) => item.task_id === task.task_id)
    ? tasks.map((item) => (item.task_id === task.task_id ? { ...item, ...task } : item))
    : [task, ...tasks];
  return {
    ...project,
    latest_task_id: project.latest_task_id || task.task_id,
    tasks: nextTasks
  };
}

function readStoredWorkspaceSection(projectId?: string) {
  if (!projectId || typeof window === "undefined") return productionSteps[0].section;
  const stored = window.localStorage.getItem(workspaceSectionStorageKey(projectId)) || "";
  return productionSteps.some((step) => step.section === stored) ? stored : productionSteps[0].section;
}

function writeStoredWorkspaceSection(projectId: string | undefined, section: string) {
  if (!projectId || typeof window === "undefined") return;
  window.localStorage.setItem(workspaceSectionStorageKey(projectId), section);
}

function workspaceSectionStorageKey(projectId: string) {
  return `storyforge.workspace.${projectId}.activeSection`;
}
