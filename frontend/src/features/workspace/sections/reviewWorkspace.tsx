import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Sparkles } from "lucide-react";
import { createContinuityRepairBatchTask, createContinuityRepairTask } from "../../../api/continuity";
import { resetSegmentPrompt, updateSegmentPrompts } from "../../../api/prompts";
import { queryKeys } from "../../../api/queryKeys";
import { TaskButton } from "../../../components/TaskButton";
import type {
  ArtifactItem,
  ArtifactBundle,
  ContinuityIssueGroup,
  CreateStageTaskRequest,
  PlannedSegmentArtifact,
  StageTaskKind
} from "../../../types";
import { AssetPreview, MediaStage, StageEmpty, WorkspaceHeading } from "../workspaceCommon";
import { getErrorMessage, getSegmentSceneFrame, type SceneRow } from "../workspaceModel";

type SegmentReferenceResource = {
  description: string;
  item: ArtifactItem;
  key: string;
  kind?: string;
  label: string;
};

export function ReviewWorkspace({
  activeTaskId,
  artifacts,
  isTaskBusy,
  mutationStage,
  onSubmit,
  onTaskAccepted,
  plannedSegments,
  projectId,
  sceneRows,
  selectedSegment,
  stageBlockReason,
  setSelectedSegmentId
}: {
  activeTaskId: string;
  artifacts?: ArtifactBundle;
  isTaskBusy: boolean;
  mutationStage?: StageTaskKind;
  onSubmit: (stage: StageTaskKind, extraPayload?: Partial<CreateStageTaskRequest>) => void;
  onTaskAccepted: (taskId: string) => void;
  plannedSegments: PlannedSegmentArtifact[];
  projectId?: string;
  sceneRows: SceneRow[];
  selectedSegment?: PlannedSegmentArtifact;
  stageBlockReason?: string;
  setSelectedSegmentId: (segmentId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [videoPromptDraft, setVideoPromptDraft] = useState("");

  useEffect(() => {
    setVideoPromptDraft(getEditableVideoPrompt(selectedSegment));
  }, [
    selectedSegment?.segment_id,
    selectedSegment?.video_prompt,
    selectedSegment?.submitted_video_prompt,
    selectedSegment?.seedance_motion_prompt
  ]);

  const continuityGroups = useMemo(
    () => [
      ...(artifacts?.continuity_segment_groups || []),
      ...(artifacts?.continuity_scene_groups || [])
    ],
    [artifacts?.continuity_scene_groups, artifacts?.continuity_segment_groups]
  );
  const selectedIssueGroups = useMemo(
    () => continuityGroups.filter((group) => groupMatchesSegment(group, selectedSegment)),
    [continuityGroups, selectedSegment]
  );
  const referenceResources = useMemo(
    () => getSegmentReferenceResources(selectedSegment, sceneRows),
    [sceneRows, selectedSegment]
  );
  const submittedVideoPrompt = getSubmittedVideoPrompt(selectedSegment);
  const persistedVideoPrompt = getEditableVideoPrompt(selectedSegment);
  const storyboardPrompt = getStoryboardPrompt(selectedSegment);
  const storyboardRequestPayload = selectedSegment?.storyboard_grid_request?.payload;
  const showStoryboardPromptPanel = Boolean(selectedSegment && isGridStoryboardMode(selectedSegment));
  const showVideoPromptPanel = Boolean(!selectedSegment || !isGridStoryboardMode(selectedSegment) || selectedSegment.storyboard_ready);
  const resolvedVideoPrompt = useMemo(
    () =>
      buildResolvedVideoPromptPreview({
        basePrompt: videoPromptDraft || persistedVideoPrompt,
        resources: referenceResources,
        submittedPrompt: submittedVideoPrompt
      }),
    [persistedVideoPrompt, referenceResources, submittedVideoPrompt, videoPromptDraft]
  );
  const resolvedPromptLabel = submittedVideoPrompt.trim().startsWith("参考图绑定")
    ? "实际提交 Prompt（含图片绑定）"
    : "提交预览 Prompt（含图片绑定）";
  const promptChanged = videoPromptDraft.trim() !== persistedVideoPrompt.trim();
  const resetMutation = useMutation({
    mutationFn: () => {
      if (!projectId || !activeTaskId || !selectedSegment) throw new Error("缺少当前片段，无法恢复 prompt。");
      return resetSegmentPrompt(projectId, activeTaskId, selectedSegment.segment_id, "video_prompt");
    },
    onSuccess: (response) => {
      setVideoPromptDraft(response.prompt || "");
      void queryClient.invalidateQueries({ queryKey: queryKeys.artifacts(activeTaskId) });
    }
  });
  const promptMutation = useMutation({
    mutationFn: ({ prompt }: { prompt: string; regenerate: boolean }) => {
      if (!projectId || !activeTaskId || !selectedSegment) throw new Error("缺少当前片段，无法保存视频 prompt。");
      return updateSegmentPrompts(projectId, activeTaskId, selectedSegment.segment_id, { video_prompt: prompt });
    },
    onSuccess: (_response, variables) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.artifacts(activeTaskId) });
      if (variables.regenerate && selectedSegment) {
        onSubmit("videos", { segment_id: selectedSegment.segment_id });
      }
    }
  });
  const repairMutation = useMutation({
    mutationFn: () => {
      if (!projectId || !activeTaskId || !selectedSegment) throw new Error("缺少当前片段，无法提交连续性修复。");
      return createContinuityRepairTask({
        continuity_review_mode: "auto",
        project_id: projectId,
        segment_id: selectedSegment.segment_id,
        source_task_id: activeTaskId,
        use_llm: true
      });
    },
    onSuccess: (response) => {
      onTaskAccepted(response.task_id);
    }
  });
  const batchRepairMutation = useMutation({
    mutationFn: () => {
      if (!projectId || !activeTaskId) throw new Error("缺少项目或任务信息，无法提交批量修复。");
      return createContinuityRepairBatchTask({
        continuity_review_mode: "auto",
        max_units_per_batch: 4,
        project_id: projectId,
        severity_threshold: "medium",
        source_task_id: activeTaskId,
        use_llm: true
      });
    },
    onSuccess: (response) => {
      onTaskAccepted(response.task_id);
    }
  });
  const actionDisabled = isTaskBusy || !projectId || !activeTaskId || !selectedSegment;
  const stageBlocked = Boolean(stageBlockReason);
  const promptActionDisabled =
    actionDisabled || promptMutation.isPending || resetMutation.isPending || !videoPromptDraft.trim();

  function saveVideoPrompt({ regenerate }: { regenerate: boolean }) {
    const prompt = videoPromptDraft.trim();
    if (!prompt) return;
    promptMutation.mutate({ prompt, regenerate });
  }

  return (
    <>
      <section className="segment-video-board" aria-label="分段视频生成列表">
        <WorkspaceHeading
          eyebrow="Review Desk"
          title="分段审片台"
          summary="逐段检查场景母图、视频状态和尾帧承接。"
        />
        {stageBlockReason ? <div className="error-callout">{stageBlockReason}</div> : null}
        <div className="segment-video-grid">
          {plannedSegments.length ? (
            plannedSegments.map((segment) => {
              const selected = segment.segment_id === selectedSegment?.segment_id;
              const sceneFrame = getSegmentSceneFrame(segment, sceneRows);
              const issueTotal = countIssuesForSegment(continuityGroups, segment);
              const videoAction = getSegmentVideoAction(segment);
              const gridMode = isGridStoryboardMode(segment);
              const videoReady = isSegmentReadyForVideo(segment);
              return (
                <article className={selected ? "segment-video-card selected" : "segment-video-card"} key={segment.segment_id}>
                  <button type="button" onClick={() => setSelectedSegmentId(segment.segment_id)}>
                    <AssetPreview item={segment.rendered_clip || segment.storyboard_grid || sceneFrame} />
                    <span>{segment.scene_title || segment.scene_id || "未绑定场景"}</span>
                    <strong>{segment.segment_id}</strong>
                    <em>
                      {labelSegmentVideoState(segment)}
                      {issueTotal > 0 ? ` · ${issueTotal} 个问题` : ""}
                    </em>
                  </button>
                  {gridMode ? (
                    <TaskButton
                      disabled={isTaskBusy || stageBlocked || !segment.scene_ready}
                      loading={isTaskBusy && mutationStage === "storyboards" && selected}
                      title={stageBlockReason || (!segment.scene_ready ? "当前片段缺少场景母图或角色图，先补齐素材。" : undefined)}
                      type="button"
                      onClick={() => {
                        setSelectedSegmentId(segment.segment_id);
                        onSubmit("storyboards", { segment_id: segment.segment_id, video_mode: "grid_storyboard" });
                      }}
                    >
                      {segment.storyboard_ready ? "重新生成九宫格" : "生成九宫格"}
                    </TaskButton>
                  ) : null}
                  <TaskButton
                    disabled={isTaskBusy || stageBlocked || !videoReady}
                    loading={isTaskBusy && mutationStage === "videos" && selected}
                    title={stageBlockReason || videoAction.reason || undefined}
                    type="button"
                    onClick={() => {
                      setSelectedSegmentId(segment.segment_id);
                      onSubmit("videos", { segment_id: segment.segment_id });
                    }}
                  >
                    {videoAction.label}
                  </TaskButton>
                </article>
              );
            })
          ) : (
            <StageEmpty title="还没有 segment" description="先完成结构化信息，生成分段合同后这里会展示所有视频片段。" />
          )}
        </div>
      </section>

      <div className="studio-theater">
        <div className="theater-screen">
          <MediaStage segment={selectedSegment} />
        </div>
        <aside className="theater-context" aria-label="当前片段摘要">
          <p className="eyebrow">{selectedSegment?.scene_id || "No segment"}</p>
          <h3>{selectedSegment?.title || "等待规划产物"}</h3>
          <p>{selectedSegment?.summary || selectedSegment?.scene_summary || "生成分段合同后，这里会显示当前片段的动作目标和审片状态。"}</p>
          <dl>
            <div>
              <dt>时长</dt>
              <dd>{selectedSegment?.duration_seconds ? `${selectedSegment.duration_seconds}s` : "未定"}</dd>
            </div>
            <div>
              <dt>场景</dt>
              <dd>{selectedSegment?.scene_title || selectedSegment?.scene_id || "未绑定"}</dd>
            </div>
            <div>
              <dt>尾帧承接</dt>
              <dd>{selectedSegment?.first_frame_url ? "已启用" : "独立开场"}</dd>
            </div>
            <div>
              <dt>片段问题</dt>
              <dd>{selectedSegment ? `${countIssuesForSegment(continuityGroups, selectedSegment)} 个` : "未选择"}</dd>
            </div>
          </dl>
          {selectedSegment ? (
            <div className="theater-actions">
              {isGridStoryboardMode(selectedSegment) ? (
                <TaskButton
                  disabled={isTaskBusy || stageBlocked || !selectedSegment.scene_ready}
                  loading={isTaskBusy && mutationStage === "storyboards"}
                  title={stageBlockReason || (!selectedSegment.scene_ready ? "当前片段缺少场景母图或角色图，先补齐素材。" : undefined)}
                  type="button"
                  onClick={() => onSubmit("storyboards", { segment_id: selectedSegment.segment_id, video_mode: "grid_storyboard" })}
                >
                  {selectedSegment.storyboard_ready ? "重新生成九宫格" : "生成九宫格"}
                </TaskButton>
              ) : null}
              <TaskButton
                disabled={isTaskBusy || stageBlocked || !isSegmentReadyForVideo(selectedSegment)}
                loading={isTaskBusy && mutationStage === "videos"}
                title={stageBlockReason || getSegmentVideoAction(selectedSegment).reason || undefined}
                type="button"
                onClick={() => onSubmit("videos", { segment_id: selectedSegment.segment_id })}
              >
                {getSegmentVideoAction(selectedSegment).label}
              </TaskButton>
            </div>
          ) : (
            <button className="primary-link" type="button" disabled>
              等待 artifacts
            </button>
          )}
        </aside>
      </div>

      {selectedSegment ? (
        <section className="segment-inspection-panel" aria-label="当前分段审片详情">
          <div className="segment-issue-panel">
            <div className="segment-panel-heading">
              <div>
                <p className="eyebrow">Issues</p>
                <h3>当前片段问题</h3>
              </div>
              <span className={selectedIssueGroups.length ? "status-pill status-failed" : "status-pill status-completed"}>
                {selectedIssueGroups.length ? `${countIssuesInGroups(selectedIssueGroups)} 个问题` : "暂无问题"}
              </span>
            </div>
            {selectedIssueGroups.length ? (
              <div className="segment-issue-list">
                {selectedIssueGroups.slice(0, 5).map((group, index) => (
                  <article key={String(group.id || group.key || group.segment_id || group.scene_id || index)}>
                    <span>{labelSeverity(group.severity)}</span>
                    <strong>{labelContinuityGroup(group)}</strong>
                    <em>{labelIssueScope(group)}</em>
                    {group.issues?.slice(0, 2).map((issue, issueIndex) => (
                      <p key={`${issue.code || issue.message || "issue"}-${issueIndex}`}>{issue.message || issue.code || "连续性问题"}</p>
                    ))}
                  </article>
                ))}
              </div>
            ) : (
              <p className="segment-muted-copy">当前片段没有命中的连续性报告。若画面仍不对，可以直接修改视频 Prompt 后重跑。</p>
            )}
            <div className="segment-repair-actions">
              <TaskButton
                disabled={actionDisabled}
                loading={repairMutation.isPending}
                type="button"
                onClick={() => repairMutation.mutate()}
              >
                <Sparkles size={14} aria-hidden="true" /> 修复当前片段
              </TaskButton>
              <TaskButton
                disabled={isTaskBusy || !projectId || !activeTaskId}
                loading={batchRepairMutation.isPending}
                type="button"
                onClick={() => batchRepairMutation.mutate()}
              >
                批量修复建议项
              </TaskButton>
            </div>
          </div>

          <div className="segment-reference-panel">
            <div className="segment-panel-heading">
              <div>
                <p className="eyebrow">References</p>
                <h3>提交资源图</h3>
              </div>
              <span className="status-pill">{referenceResources.length} 张</span>
            </div>
            {referenceResources.length ? (
              <div className="segment-resource-grid">
                {referenceResources.map((resource) => (
                  <article className="segment-resource-card" key={resource.key}>
                    <AssetPreview item={resource.item} />
                    <strong>{resource.label}</strong>
                    <span>{resource.description}</span>
                  </article>
                ))}
              </div>
            ) : (
              <p className="segment-muted-copy">当前片段还没有可展示的提交资源图。</p>
            )}
          </div>

          {showStoryboardPromptPanel ? (
            <div className="segment-prompt-editor">
              <div className="segment-panel-heading">
                <div>
                  <p className="eyebrow">Storyboard Prompt</p>
                  <h3>九宫格生图 Prompt</h3>
                </div>
                <span className="status-pill">
                  {selectedSegment.storyboard_grid_status || (isTaskBusy && mutationStage === "storyboards" ? "生成中" : "待生成")}
                </span>
              </div>
              {storyboardPrompt ? (
                <details className="segment-submitted-prompt" open>
                  <summary>九宫格生图 Prompt</summary>
                  <pre>{storyboardPrompt}</pre>
                </details>
              ) : (
                <p className="segment-muted-copy">
                  九宫格生图 Prompt 会在提交九宫格任务后由后端生成并回写；当前阶段不展示视频 Prompt，避免误判提交内容。
                </p>
              )}
              {storyboardRequestPayload ? (
                <details className="segment-submitted-prompt">
                  <summary>九宫格提交请求</summary>
                  <pre>{JSON.stringify(storyboardRequestPayload, null, 2)}</pre>
                </details>
              ) : null}
              <div className="segment-prompt-actions">
                <TaskButton
                  disabled={isTaskBusy || stageBlocked || !selectedSegment.scene_ready}
                  loading={isTaskBusy && mutationStage === "storyboards"}
                  title={stageBlockReason || (!selectedSegment.scene_ready ? "当前片段缺少场景母图或角色图，先补齐素材。" : undefined)}
                  type="button"
                  onClick={() => onSubmit("storyboards", { segment_id: selectedSegment.segment_id, video_mode: "grid_storyboard" })}
                >
                  {selectedSegment.storyboard_ready ? "重新生成九宫格" : "生成九宫格"}
                </TaskButton>
              </div>
              {repairMutation.isError ? <div className="error-callout">{getErrorMessage(repairMutation.error)}</div> : null}
              {batchRepairMutation.isError ? <div className="error-callout">{getErrorMessage(batchRepairMutation.error)}</div> : null}
            </div>
          ) : null}

          {showVideoPromptPanel ? (
            <div className="segment-prompt-editor">
              <div className="segment-panel-heading">
                <div>
                  <p className="eyebrow">Seedance Prompt</p>
                  <h3>生成视频 Prompt</h3>
                </div>
                <span className={promptChanged ? "status-pill status-edited" : "status-pill status-synced"}>
                  {promptChanged ? "有修改" : "已同步"}
                </span>
              </div>
              {resolvedVideoPrompt ? (
                <details className="segment-submitted-prompt" open>
                  <summary>{resolvedPromptLabel}</summary>
                  <pre>{resolvedVideoPrompt}</pre>
                </details>
              ) : (
                <p className="segment-muted-copy">提交预览 Prompt 会在视频 Prompt 和资源图准备后出现；下面编辑的是当前片段的基础视频 Prompt。</p>
              )}
              <textarea
                aria-label={`${selectedSegment.segment_id} 视频生成 prompt`}
                disabled={promptMutation.isPending || resetMutation.isPending || isTaskBusy}
                onChange={(event) => setVideoPromptDraft(event.target.value)}
                value={videoPromptDraft}
              />
              <div className="segment-prompt-actions">
                <TaskButton
                  disabled={actionDisabled || resetMutation.isPending}
                  loading={resetMutation.isPending}
                  type="button"
                  onClick={() => resetMutation.mutate()}
                >
                  <RotateCcw size={14} aria-hidden="true" /> 恢复默认 Prompt
                </TaskButton>
                <TaskButton
                  disabled={promptActionDisabled || !promptChanged}
                  loading={promptMutation.isPending && !promptMutation.variables?.regenerate}
                  type="button"
                  onClick={() => saveVideoPrompt({ regenerate: false })}
                >
                  保存 Prompt
                </TaskButton>
                <TaskButton
                  disabled={promptActionDisabled}
                  loading={promptMutation.isPending && Boolean(promptMutation.variables?.regenerate)}
                  type="button"
                  onClick={() => saveVideoPrompt({ regenerate: true })}
                >
                  保存并重跑视频
                </TaskButton>
              </div>
              {resetMutation.isError ? <div className="error-callout">{getErrorMessage(resetMutation.error)}</div> : null}
              {promptMutation.isError ? <div className="error-callout">{getErrorMessage(promptMutation.error)}</div> : null}
              {repairMutation.isError ? <div className="error-callout">{getErrorMessage(repairMutation.error)}</div> : null}
              {batchRepairMutation.isError ? <div className="error-callout">{getErrorMessage(batchRepairMutation.error)}</div> : null}
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="motion-ledger" aria-label="Motion plan">
        <div>
          <p className="eyebrow">Motion Plan</p>
          <h3>画面推进</h3>
        </div>
        <div className="motion-lines">
          {selectedSegment && Object.keys(selectedSegment.motion_plan || {}).length > 0 ? (
            Object.entries(selectedSegment.motion_plan || {}).map(([key, value]) => (
              <p key={key}>
                <strong>{key}</strong>
                <span>{value}</span>
              </p>
            ))
          ) : (
            <p>
              <strong>empty</strong>
              <span>当前片段还没有 motion_plan。</span>
            </p>
          )}
        </div>
      </section>
    </>
  );
}

function getEditableVideoPrompt(segment?: PlannedSegmentArtifact) {
  return segment?.video_prompt || segment?.seedance_motion_prompt || "";
}

function getSubmittedVideoPrompt(segment?: PlannedSegmentArtifact) {
  const requestPrompt = segment?.video_request?.payload?.content;
  if (Array.isArray(requestPrompt)) {
    const textItem = requestPrompt.find((item) => typeof item === "object" && item && "text" in item);
    if (textItem && typeof (textItem as { text?: unknown }).text === "string") {
      return (textItem as { text: string }).text;
    }
  }
  return segment?.submitted_video_prompt || "";
}

function getStoryboardPrompt(segment?: PlannedSegmentArtifact) {
  const requestPrompt = segment?.storyboard_grid_request?.payload?.prompt;
  if (typeof requestPrompt === "string" && requestPrompt.trim()) {
    return requestPrompt;
  }
  return segment?.storyboard_grid_prompt || "";
}

function buildResolvedVideoPromptPreview({
  basePrompt,
  resources,
  submittedPrompt
}: {
  basePrompt: string;
  resources: SegmentReferenceResource[];
  submittedPrompt: string;
}) {
  const submitted = submittedPrompt.trim();
  if (submitted.startsWith("参考图绑定")) return submitted;
  const body = (submitted || basePrompt).trim();
  if (!body) return "";
  if (!resources.length) return body;
  if (resources.length === 1 && resources[0].kind === "storyboard_grid") {
    return [
      "参考图绑定（按当前提交资源图顺序理解）：",
      "- 图片1：九宫格分镜图，是当前片段主要视频参考图；从左到右、从上到下依次表示本段动作推进、角色状态、空间关系和收束画面。",
      "推进引用规则：",
      "- 视频根据图片1的九宫格分镜图生成，画面、人物、道具、光线、镜头运动和对白节奏必须按文本中的场景时间描述与九宫格顺序自然推进。",
      "",
      body
    ].join("\n");
  }

  const bindingLines = ["参考图绑定（按当前提交资源图顺序理解）："];
  let sceneLabel = "";
  let firstFrameLabel = "";
  let storyboardLabel = "";
  const characterLabels: string[] = [];

  resources.forEach((resource, index) => {
    const label = `图片${index + 1}`;
    const kind = resource.kind || "";
    if (kind === "scene_master") {
      sceneLabel = label;
      bindingLines.push(`- ${label}：当前 scene 的场景母图，只用于锁定环境、空间、光线、背景锚点和固定道具；不是视频时间帧。`);
    } else if (kind === "storyboard_grid") {
      storyboardLabel = label;
      bindingLines.push(`- ${label}：九宫格分镜图，是当前片段主要视频参考图；从左到右、从上到下依次表示动作推进、空间关系、镜头运动和收束状态。`);
    } else if (kind === "first_frame") {
      firstFrameLabel = label;
      bindingLines.push(`- ${label}：上一段视频尾帧，是当前片段的开场时间锚点；必须先从这张图的构图、角色站位、朝向、动作停点和光线状态自然继续。`);
    } else if (kind.startsWith("character")) {
      characterLabels.push(label);
      bindingLines.push(`- ${label}：${resource.label.replace(/^图片\d+\s*·\s*/, "")}，只用于锁定角色身份、脸、发型、服装、体型和年龄感；不是视频时间帧。`);
    } else {
      bindingLines.push(`- ${label}：${resource.description || "提交给视频生成接口的参考图"}。`);
    }
  });

  bindingLines.push("推进引用规则：");
  if (storyboardLabel && firstFrameLabel) {
    bindingLines.push(`- 0 秒开场必须先对齐${firstFrameLabel}的构图、角色站位、朝向、动作停点和光线状态；随后按${storyboardLabel}的九宫格顺序自然推进。`);
    bindingLines.push(`- ${firstFrameLabel}只约束开场瞬间，不能替代${storyboardLabel}的分镜顺序；不要把尾帧扩写成新场景或打乱九宫格。`);
  } else if (storyboardLabel) {
    bindingLines.push(`- 视频必须按${storyboardLabel}的九宫格顺序生成，保持画面、人物、道具、光线、镜头运动和对白节奏连续。`);
  } else if (sceneLabel && firstFrameLabel) {
    bindingLines.push(`- 0 秒开场必须先对齐${firstFrameLabel}的构图、角色站位、朝向、动作停点和光线状态；随后角色运动、镜头推进和空间关系必须在${sceneLabel}锁定的同一场景母图空间中继续。`);
    bindingLines.push(`- ${firstFrameLabel}只决定当前片段开头的时间状态，不能替代${sceneLabel}的环境设定；不要把尾帧里的构图误当成新场景母图。`);
  } else if (sceneLabel) {
    bindingLines.push(`- 视频必须从${sceneLabel}锁定的场景母图空间中建立开场，并按文本中的运动轨迹推进；不要突然换景或生成无关地点。`);
  }
  if (characterLabels.length) {
    bindingLines.push(`- ${characterLabels.join(", ")}只用于锁定角色身份、脸、发型、服装、体型和年龄感，不是视频时间帧。`);
  }
  bindingLines.push("- 每个实际出镜角色只能出现一次，不要复制人物、不要新增相似替身、不要把三视图或白底定妆版式带入视频。");
  return [...bindingLines, "", body].join("\n");
}

function groupMatchesSegment(group: ContinuityIssueGroup, segment?: PlannedSegmentArtifact) {
  if (!segment) return false;
  if (group.segment_id === segment.segment_id) return true;
  if (group.scene_id && group.scene_id === segment.scene_id) return true;
  return Boolean(
    group.issues?.some((issue) => issue.segment_id === segment.segment_id || (issue.scene_id && issue.scene_id === segment.scene_id))
  );
}

function countIssuesForSegment(groups: ContinuityIssueGroup[], segment: PlannedSegmentArtifact) {
  return countIssuesInGroups(groups.filter((group) => groupMatchesSegment(group, segment)));
}

function countIssuesInGroups(groups: ContinuityIssueGroup[]) {
  return groups.reduce((count, group) => count + Math.max(group.issues?.length || 1, 1), 0);
}

function getSegmentReferenceResources(segment: PlannedSegmentArtifact | undefined, sceneRows: SceneRow[]): SegmentReferenceResource[] {
  if (!segment) return [];
  const submittedBindings = segment.video_request?.reference_bindings?.length
    ? segment.video_request.reference_bindings
    : segment.submitted_reference_bindings || [];
  const resources = submittedBindings
    .filter((binding) => binding.url)
    .map((binding, index) => ({
      description: binding.description || labelResourceKind(binding.kind),
      item: {
        kind: binding.kind || "image",
        name: binding.label || `图${index + 1}`,
        url: binding.url
      } as ArtifactItem,
      key: `binding-${index}-${binding.url}`,
      kind: binding.kind || "image",
      label: binding.label || `图${index + 1}`
    }));
  if (resources.length) return resources;

  const fallbackResources: SegmentReferenceResource[] = [];
  if (isGridStoryboardMode(segment) && segment.storyboard_grid?.url) {
    fallbackResources.push({
      description: "九宫格分镜图，作为该段视频主要提交参考图",
      item: segment.storyboard_grid,
      key: `storyboard-${segment.storyboard_grid.url}`,
      kind: "storyboard_grid",
      label: "九宫格分镜"
    });
    if (segment.first_frame_url) {
      fallbackResources.push({
        description: "上一段尾帧，用于承接构图、站位和动作停点",
        item: { kind: "image", name: "上一段尾帧", url: segment.first_frame_url },
        key: `grid-first-frame-${segment.first_frame_url}`,
        kind: "first_frame",
        label: "尾帧承接"
      });
    }
    return fallbackResources;
  }
  const sceneFrame = getSegmentSceneFrame(segment, sceneRows);
  if (sceneFrame?.url) {
    fallbackResources.push({
      description: "场景母图，锁定空间、光线和固定道具",
      item: sceneFrame,
      key: `scene-${sceneFrame.url}`,
      kind: "scene_master",
      label: "场景母图"
    });
  }
  if (segment.first_frame_url) {
    fallbackResources.push({
      description: "上一段尾帧，用于承接构图、站位和动作停点",
      item: { kind: "image", name: "上一段尾帧", url: segment.first_frame_url },
      key: `first-frame-${segment.first_frame_url}`,
      kind: "first_frame",
      label: "尾帧承接"
    });
  }
  segment.character_references?.forEach((item, index) => {
    if (!item.url) return;
    fallbackResources.push({
      description: "角色定妆图，只锁定脸、发型、服装、体型和比例",
      item,
      key: `character-${index}-${item.url}`,
      kind: "character",
      label: item.name || `角色图 ${index + 1}`
    });
  });
  return fallbackResources;
}

function labelResourceKind(kind?: string) {
  if (kind === "storyboard_grid") return "九宫格分镜图，该段视频主要参考图";
  if (kind === "scene_master") return "场景母图，锁定地点、光线、空间透视和固定道具";
  if (kind === "first_frame") return "上一段尾帧，锁定片段开头的时间状态";
  if (kind === "character") return "角色定妆图，锁定角色身份和造型";
  return "提交给视频生成接口的参考图";
}

function isGridStoryboardMode(segment?: PlannedSegmentArtifact) {
  return segment?.video_mode === "grid_storyboard";
}

function isSegmentReadyForVideo(segment: PlannedSegmentArtifact) {
  if (isGridStoryboardMode(segment)) return Boolean(segment.storyboard_ready || segment.storyboard_grid?.url);
  return Boolean(segment.scene_ready);
}

function getSegmentVideoAction(segment: PlannedSegmentArtifact) {
  if (segment.rendered_clip?.url) {
    return { label: "重新生成视频", reason: "" };
  }
  if (isGridStoryboardMode(segment) && !isSegmentReadyForVideo(segment)) {
    return {
      label: "先生成九宫格",
      reason: segment.scene_ready ? "九宫格未生成，先生成九宫格后才能生成视频。" : "当前片段缺少场景母图或角色图，先补齐素材。"
    };
  }
  return { label: "生成当前视频", reason: "" };
}

function labelSegmentVideoState(segment: PlannedSegmentArtifact) {
  if (segment.rendered_clip?.url) return "已出片";
  if (isGridStoryboardMode(segment)) {
    if (segment.storyboard_ready || segment.storyboard_grid?.url) return "可生成视频";
    if (segment.scene_ready) return "待九宫格";
    return "待场景图";
  }
  return segment.scene_ready ? "可生成" : "待场景图";
}

function labelSeverity(severity?: string) {
  if (severity === "high") return "高风险";
  if (severity === "medium") return "中风险";
  if (severity === "low") return "低风险";
  return "待检查";
}

function labelContinuityGroup(group: ContinuityIssueGroup) {
  return group.title || group.scope || group.key || group.id || group.issues?.[0]?.message || "连续性问题";
}

function labelIssueScope(group: ContinuityIssueGroup) {
  return group.segment_id || group.scene_id || group.scope || "当前片段";
}
