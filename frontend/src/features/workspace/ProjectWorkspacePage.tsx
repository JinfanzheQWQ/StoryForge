import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { getTaskArtifacts } from "../../api/artifacts";
import { getProject } from "../../api/projects";
import { queryKeys } from "../../api/queryKeys";
import { createStageTask } from "../../api/stageTasks";
import { getTask } from "../../api/tasks";
import type { CreateStageTaskRequest, StageTaskKind } from "../../types";
import { StageActionRail, WorkspaceSection } from "./workspaceSections";
import {
  buildSceneRows,
  getErrorMessage,
  getStageCompletionState,
  hasEditableStorySource,
  labelTaskOperation,
  productionSteps,
  resolveEditableSourceTaskId,
  selectCharacter,
  selectSceneRow,
  selectSegment
} from "./workspaceModel";

export function ProjectWorkspacePage() {
  const { projectId, taskId } = useParams();
  const queryClient = useQueryClient();
  const [activeSection, setActiveSection] = useState(productionSteps[0].section);
  const [selectedCharacterName, setSelectedCharacterName] = useState<string>("");
  const [selectedSceneId, setSelectedSceneId] = useState<string>("");
  const [selectedSegmentId, setSelectedSegmentId] = useState<string>("");
  const [submittedTaskId, setSubmittedTaskId] = useState<string>("");

  const projectQuery = useQuery({
    queryKey: queryKeys.project(projectId),
    queryFn: () => getProject(projectId || ""),
    enabled: Boolean(projectId)
  });

  const activeTaskId = submittedTaskId || taskId || projectQuery.data?.latest_task_id || "";
  const taskQuery = useQuery({
    queryKey: queryKeys.task(activeTaskId),
    queryFn: () => getTask(activeTaskId),
    enabled: Boolean(activeTaskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 2000 : false;
    }
  });
  const activeTask = taskQuery.data?.task_id === activeTaskId ? taskQuery.data : undefined;
  const projectTasks = projectQuery.data?.tasks || [];
  const sourceTaskId = useMemo(
    () =>
      resolveEditableSourceTaskId({
        activeTask,
        fallbackTaskId: taskId || projectQuery.data?.latest_task_id || activeTaskId,
        tasks: projectTasks
      }),
    [activeTask, activeTaskId, projectQuery.data?.latest_task_id, projectTasks, taskId]
  );
  const sourceTask =
    projectTasks.find((task) => task.task_id === sourceTaskId) ||
    (activeTask?.task_id === sourceTaskId ? activeTask : undefined);
  const isSourceTaskReady = Boolean(sourceTaskId && sourceTask?.status === "completed" && hasEditableStorySource(sourceTask));

  const artifactsQuery = useQuery({
    queryKey: queryKeys.artifacts(sourceTaskId),
    queryFn: () => getTaskArtifacts(sourceTaskId),
    enabled: Boolean(sourceTaskId) && isSourceTaskReady
  });

  const artifacts = artifactsQuery.data;
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
  const sceneCount = scenes.length || artifacts?.scene_frames?.length || 0;
  const clipCount = artifacts?.rendered_clips?.length || 0;
  const readySegments = plannedSegments.filter((segment) => segment.rendered_clip?.url).length;
  const hasSceneStructure = scenes.length > 0 || sceneRows.length > 0;
  const activeTaskType = activeTask?.task_type || activeTask?.stage;
  const completion = getStageCompletionState({
    activeTaskStatus: activeTask?.status,
    activeTaskType,
    characterCount,
    hasSceneStructure,
    plannedSegmentCount: plannedSegments.length
  });
  const projectTitle = projectQuery.data?.story_title || projectQuery.data?.title_hint || artifacts?.story_title || "项目工作台";
  const stageMutation = useMutation({
    mutationFn: ({ payload, stage }: { payload: CreateStageTaskRequest; stage: StageTaskKind }) =>
      createStageTask(stage, payload),
    onSuccess: (response, variables) => {
      setSubmittedTaskId(response.task_id);
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.task(response.task_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.artifacts(variables.payload.source_task_id) });
    }
  });
  const isWaitingForTaskRecord = Boolean(activeTaskId) && taskQuery.isFetching && !activeTask;
  const isTaskBusy =
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
    if (activeTask?.status !== "completed" || !sourceTaskId) return;
    void queryClient.invalidateQueries({ queryKey: queryKeys.artifacts(sourceTaskId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.projects() });
  }, [activeTask?.status, activeTask?.task_id, projectId, queryClient, sourceTaskId]);

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
      characterCount,
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

  function submitStage(stage: StageTaskKind, extraPayload: Partial<CreateStageTaskRequest> = {}) {
    if (!projectId || !sourceTaskId || !isSourceTaskReady || isTaskBusy) return;
    stageMutation.mutate({
      stage,
      payload: {
        project_id: projectId,
        source_task_id: sourceTaskId,
        ...extraPayload
      }
    });
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

          <StageActionRail
            activeSection={activeSection}
            activeTaskId={sourceTaskId}
            activeStep={activeStep}
            activeStepIndex={activeStepIndex}
            completion={completion}
            isBusy={isTaskBusy}
            mutationStage={stageMutation.variables?.stage}
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
    characterCount: number;
    completion: { sceneStructureComplete: boolean; segmentContractsComplete: boolean };
    plannedCount: number;
    readySegments: number;
    sceneRowsReady: boolean;
  }
) {
  if (section === "小说") return "complete";
  if (section === "结构化信息") return progress.completion.segmentContractsComplete ? "complete" : "ready";
  if (section === "角色图") return progress.characterCount > 0 ? "complete" : "ready";
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
