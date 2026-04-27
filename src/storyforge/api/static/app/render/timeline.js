import { registerGallery } from "../gallery.js";
import {
  chip,
  escapeAttr,
  escapeHtml,
  getRunStageStatus,
  getStorySourceRevision,
  singleAssetMessage,
} from "../utils.js";
import {
  renderScenePromptPanel,
  renderSegmentPromptPanel,
} from "./prompt_tools.js";

export function renderTimelineTab({ task, artifacts, context, run = null, helpers }) {
  if (!artifacts?.available) {
    return singleAssetMessage("片段时间线暂不可用", helpers.buildArtifactPendingMessage(task, "images", run));
  }

  const timelineItems = helpers.buildTimelineGalleryItems(artifacts);
  const galleryId = `${context}:timeline:${task.task_id}`;
  registerGallery(galleryId, timelineItems);
  const segments = helpers.buildTimelineSegments(artifacts);
  const sceneGroups = helpers.buildSceneGroups(segments);
  const continuitySceneLookup = helpers.buildContinuityLookup(artifacts?.continuity_scene_groups, "scene_id");
  const continuitySegmentLookup = helpers.buildContinuityLookup(artifacts?.continuity_segment_groups, "segment_id");
  const rootTask = run?.rootTask || task;
  const storySourceRevision = run ? getStorySourceRevision(rootTask) : getStorySourceRevision(task);
  const segmentContractsStatus = run ? getRunStageStatus(run.latestSegmentContractsTask, storySourceRevision) : "idle";
  const characterStatus = run ? getRunStageStatus(run.latestCharacterTask, storySourceRevision) : "idle";
  const mergeTaskStatus = run ? getRunStageStatus(run.latestMergeTask, storySourceRevision) : "idle";
  const batchRepairTask = helpers.getLatestBatchRepairTask(run);
  const batchRepairTaskStatus = run ? getRunStageStatus(batchRepairTask, storySourceRevision) : "idle";
  const readySceneCount = segments.filter((segment) => segment.sceneReady).length;
  const readyVideoCount = segments.filter((segment) => segment.videoReady).length;
  const canMergeVideos = readyVideoCount >= 2 && !["queued", "running"].includes(mergeTaskStatus);
  const repairableRiskCount = Number(artifacts?.continuity_summary?.high_risk_count || 0)
    + Number(artifacts?.continuity_summary?.medium_risk_count || 0);
  const runHasBusyRepairTask = (run?.tasks || []).some(
    (item) => (
      (item.task_type === "project.continuity_repair" || item.task_type === "project.continuity_repair_batch")
      && helpers.isBusyTaskStatus(getRunStageStatus(item, storySourceRevision))
    ),
  );
  const canRunBatchRepair = segmentContractsStatus === "completed"
    && repairableRiskCount > 0
    && !runHasBusyRepairTask;

  return `
    <section class="timeline-shell">
      <article class="asset-block timeline-hero">
        <div>
          <p class="section-kicker">Timeline</p>
          <h4>按视频片段审片</h4>
          <p class="asset-note">分段合同完成后，这里会按 LLM 生成的 segment_plan 逐段展示。每一段都可以单独生成场景图和视频，不再一次性把全部片段跑完。</p>
          <p class="asset-note">场景母图、角色参考图和视频片段会放在同一张卡里，便于逐段检查角色一致性、动作推进和字幕是否完整。</p>
        </div>
        <div class="detail-chip-row">
          ${chip(`场景 ${sceneGroups.length}`)}
          ${chip(`片段 ${segments.length}`)}
          ${chip(`场景就绪 ${readySceneCount}/${segments.length || 0}`)}
          ${chip(`视频就绪 ${readyVideoCount}/${segments.length || 0}`)}
          ${chip(`总片 ${artifacts.full_story ? "已生成" : "未生成"}`)}
          ${
            artifacts?.continuity_summary
              ? chip(`连续性 ${helpers.CONTINUITY_STATUS_LABEL[artifacts.continuity_summary.status] || artifacts.continuity_summary.status}`)
              : chip("连续性 未校验")
          }
          ${
            artifacts?.continuity_summary?.high_risk_count
              ? `<span class="continuity-chip continuity-chip-high">高 ${artifacts.continuity_summary.high_risk_count}</span>`
              : ""
          }
        </div>
        <div class="timeline-hero-actions">
          <button
            type="button"
            class="secondary"
            data-auto-repair-batch="${escapeAttr(rootTask.task_id)}"
            data-project-id="${escapeAttr(rootTask.project_id)}"
            data-source-task="${escapeAttr(rootTask.task_id)}"
            ${canRunBatchRepair ? "" : "disabled"}
          >
            ${escapeHtml(helpers.buildBatchRepairButtonLabel(batchRepairTaskStatus, batchRepairTask))}
          </button>
          <button
            type="button"
            class="secondary"
            data-merge-videos="${escapeAttr(rootTask.task_id)}"
            data-project-id="${escapeAttr(rootTask.project_id)}"
            ${canMergeVideos ? "" : "disabled"}
          >
            ${escapeHtml(helpers.buildMergeButtonLabel(artifacts, mergeTaskStatus))}
          </button>
        </div>
        ${helpers.renderContinuityOverview(artifacts?.continuity_summary)}
        ${helpers.renderSegmentTaskError(batchRepairTask, "批量合同修复失败")}
        ${helpers.renderBatchRepairNotice(batchRepairTask)}
        ${helpers.renderRepairPlanNotice(
          batchRepairTask,
          helpers.resolveRepairRemainingActions(run, batchRepairTask, storySourceRevision),
        )}
      </article>

      ${artifacts.full_story ? helpers.renderFullStoryBlock(artifacts.full_story, context, galleryId) : ""}

      ${
        segments.length
          ? `
            <div class="timeline-scene-list">
              ${sceneGroups
                .map(
                  (sceneGroup) => {
                    const sceneContinuity = continuitySceneLookup.get(sceneGroup.sceneId) || null;
                    const sceneMasterTask = helpers.getLatestSceneMasterTask(run, sceneGroup.sceneId);
                    const sceneRepairTask = helpers.getLatestSceneRepairTask(run, sceneGroup.sceneId);
                    const sceneMasterTaskStatus = run ? getRunStageStatus(sceneMasterTask, storySourceRevision) : "idle";
                    const sceneRepairTaskStatus = run ? getRunStageStatus(sceneRepairTask, storySourceRevision) : "idle";
                    const sceneRepairRemainingActions = helpers.resolveRepairRemainingActions(
                      run,
                      sceneRepairTask,
                      storySourceRevision,
                    );
                    const sceneRepairAffectedSegmentIds = helpers.getRepairAffectedSegmentIds(sceneRepairTask);
                    const sceneHasBusySegmentTask = sceneGroup.segments.some((segment) => {
                      const segmentSceneTask = helpers.getLatestSegmentStageTask(run, "project.scenes", segment.segmentId);
                      const segmentVideoTask = helpers.getLatestSegmentStageTask(run, "project.videos", segment.segmentId);
                      const segmentRepairTask = helpers.getLatestSegmentStageTask(run, "project.continuity_repair", segment.segmentId);
                      return [
                        getRunStageStatus(segmentSceneTask, storySourceRevision),
                        getRunStageStatus(segmentVideoTask, storySourceRevision),
                        getRunStageStatus(segmentRepairTask, storySourceRevision),
                      ].some((status) => helpers.isBusyTaskStatus(status));
                    });
                    const canGenerateSceneMaster =
                      segmentContractsStatus === "completed"
                      && !helpers.isBusyTaskStatus(batchRepairTaskStatus)
                      && !helpers.isBusyTaskStatus(sceneRepairTaskStatus)
                      && !helpers.isBusyTaskStatus(sceneMasterTaskStatus)
                      && !sceneHasBusySegmentTask;
                    const canRunSceneRepair =
                      segmentContractsStatus === "completed"
                      && Boolean(sceneContinuity?.issue_count)
                      && !helpers.isBusyTaskStatus(batchRepairTaskStatus)
                      && !helpers.isBusyTaskStatus(sceneRepairTaskStatus)
                      && !helpers.isBusyTaskStatus(sceneMasterTaskStatus)
                      && !sceneHasBusySegmentTask;
                    const sceneMasterRecommended = helpers.hasRecommendedContinuityAction(
                      sceneContinuity,
                      "regenerate_scene_master_frame",
                    ) || sceneRepairRemainingActions.includes("regenerate_scene_master_frame");
                    return `
                    <section class="timeline-scene-group">
                      <div class="timeline-scene-head">
                        <div>
                          <p class="section-kicker">Scene</p>
                          <h4>${escapeHtml(sceneGroup.sceneTitle || sceneGroup.sceneId)}</h4>
                          <p class="asset-note">
                            ${escapeHtml(`${sceneGroup.chapterNumber ? `第 ${sceneGroup.chapterNumber} 章 · ` : ""}${sceneGroup.sceneId}`)}
                          </p>
                          ${sceneGroup.sceneSummary ? `<p class="timeline-scene-summary">${escapeHtml(sceneGroup.sceneSummary)}</p>` : ""}
                        </div>
                        <div class="timeline-scene-actions">
                          <div class="detail-chip-row">
                            ${chip(`片段 ${sceneGroup.segments.length}`)}
                            ${chip(`母图 ${sceneGroup.sceneMasterFrame ? "已生成" : "未生成"}`)}
                            ${sceneRepairRemainingActions.length ? chip("修复方案已更新") : ""}
                            ${helpers.renderContinuityRiskChips(sceneContinuity)}
                          </div>
                          <button
                            type="button"
                            class="secondary small"
                            data-auto-repair-scene="${escapeAttr(sceneGroup.sceneId)}"
                            data-project-id="${escapeAttr(rootTask.project_id)}"
                            data-source-task="${escapeAttr(rootTask.task_id)}"
                            ${canRunSceneRepair ? "" : "disabled"}
                          >
                            ${escapeHtml(helpers.buildSceneRepairButtonLabel(
                              sceneRepairTaskStatus,
                              sceneRepairRemainingActions.length > 0,
                            ))}
                          </button>
                          <button
                            type="button"
                            class="secondary small${sceneMasterRecommended ? " recommended-action" : ""}"
                            data-generate-scene-master="${escapeAttr(sceneGroup.sceneId)}"
                            data-project-id="${escapeAttr(rootTask.project_id)}"
                            data-source-task="${escapeAttr(rootTask.task_id)}"
                            ${canGenerateSceneMaster ? "" : "disabled"}
                          >
                            ${escapeHtml(helpers.buildSceneMasterButtonLabel(sceneGroup, sceneMasterTaskStatus))}
                          </button>
                        </div>
                      </div>
                      ${helpers.renderContinuityIssueList(sceneContinuity)}
                      ${helpers.renderSegmentTaskError(sceneRepairTask, "场景智能修复失败")}
                      ${helpers.renderRepairPlanNotice(sceneRepairTask, sceneRepairRemainingActions)}
                      <div class="timeline-scene-master">
                        ${helpers.renderTimelinePreview(sceneGroup.sceneMasterFrame, "场景母图", galleryId)}
                      </div>
                      ${renderScenePromptPanel(sceneGroup, rootTask)}
                      ${helpers.renderSegmentTaskError(sceneMasterTask, "场景母图失败")}
                      <div class="timeline-list">
                        ${sceneGroup.segments
                .map(
                  (segment, index) => {
                    const segmentContinuity = continuitySegmentLookup.get(segment.segmentId) || null;
                    const sceneTask = helpers.getLatestSegmentStageTask(run, "project.scenes", segment.segmentId);
                    const videoTask = helpers.getLatestSegmentStageTask(run, "project.videos", segment.segmentId);
                    const repairTask = helpers.getLatestSegmentStageTask(run, "project.continuity_repair", segment.segmentId);
                    const sceneTaskStatus = run ? getRunStageStatus(sceneTask, storySourceRevision) : "idle";
                    const videoTaskStatus = run ? getRunStageStatus(videoTask, storySourceRevision) : "idle";
                    const repairTaskStatus = run ? getRunStageStatus(repairTask, storySourceRevision) : "idle";
                    const segmentRepairRemainingActions = helpers.resolveRepairRemainingActions(
                      run,
                      repairTask,
                      storySourceRevision,
                    );
                    const sceneScopeLocked =
                      helpers.isBusyTaskStatus(batchRepairTaskStatus)
                      || runHasBusyRepairTask
                      || helpers.isBusyTaskStatus(sceneRepairTaskStatus)
                      || helpers.isBusyTaskStatus(sceneMasterTaskStatus);
                    const segmentRepairLocked = helpers.isBusyTaskStatus(repairTaskStatus);
                    const affectedBySceneRepair = sceneRepairAffectedSegmentIds.has(segment.segmentId);
                    const canGenerateScene =
                      characterStatus === "completed"
                      && !sceneScopeLocked
                      && !segmentRepairLocked
                      && !helpers.isBusyTaskStatus(sceneTaskStatus)
                      && !helpers.isBusyTaskStatus(videoTaskStatus);
                    const canGenerateVideo =
                      segment.sceneReady
                      && !sceneScopeLocked
                      && !segmentRepairLocked
                      && !helpers.isBusyTaskStatus(sceneTaskStatus)
                      && !helpers.isBusyTaskStatus(videoTaskStatus);
                    const canRunRepair =
                      characterStatus === "completed"
                      && Boolean(segmentContinuity?.issue_count)
                      && !sceneScopeLocked
                      && !helpers.isBusyTaskStatus(repairTaskStatus)
                      && !helpers.isBusyTaskStatus(sceneTaskStatus)
                      && !helpers.isBusyTaskStatus(videoTaskStatus);
                    const sceneRecommended = helpers.hasRecommendedContinuityAction(
                      segmentContinuity,
                      "regenerate_scene_images",
                    )
                      || segmentRepairRemainingActions.includes("regenerate_scene_images")
                      || (
                        affectedBySceneRepair
                        && sceneRepairRemainingActions.includes("regenerate_scene_images")
                      );
                    const videoRecommended = helpers.hasRecommendedContinuityAction(
                      segmentContinuity,
                      "regenerate_video",
                    )
                      || segmentRepairRemainingActions.includes("regenerate_video")
                      || (
                        affectedBySceneRepair
                        && sceneRepairRemainingActions.includes("regenerate_video")
                      );
                    return `
                    <article class="timeline-card">
                      <div class="timeline-card-head">
                        <span class="timeline-index">${String(index + 1).padStart(2, "0")}</span>
                        <div>
                          <h4>${escapeHtml(segment.title || helpers.segmentLabel(segment.segmentId, index))}</h4>
                          <p class="asset-note">
                            ${escapeHtml(`${segment.chapterNumber ? `第 ${segment.chapterNumber} 章 · ` : ""}${segment.sceneId ? `${segment.sceneId} · ` : ""}${segment.segmentId}${segment.durationSeconds ? ` · ${segment.durationSeconds}s` : ""}`)}
                          </p>
                        </div>
                      </div>
                      ${segment.summary ? `<p class="timeline-summary">${escapeHtml(segment.summary)}</p>` : ""}
                      <div class="timeline-preview-grid">
                        ${helpers.renderTimelinePreview(segment.sceneMasterFrame, "场景母图", galleryId)}
                        ${(segment.characterReferences || []).map((item, itemIndex) => helpers.renderTimelinePreview(item, `角色图 ${itemIndex + 1}`, galleryId)).join("")}
                        ${helpers.renderTimelinePreview(segment.clip, "视频", galleryId)}
                      </div>
                      ${renderSegmentPromptPanel(segment, rootTask)}
                      <div class="timeline-card-footer">
                        <div class="detail-chip-row">
                          ${chip(`场景 ${segment.sceneReady ? "已就绪" : "待生成"}`)}
                          ${chip(`视频 ${segment.videoReady ? "已就绪" : "待生成"}`)}
                          ${chip("母图+角色图")}
                          ${segmentRepairRemainingActions.length ? chip("合同已更新") : ""}
                          ${affectedBySceneRepair && sceneRepairRemainingActions.length ? chip("场景修复目标") : ""}
                          ${helpers.renderContinuityRiskChips(segmentContinuity)}
                        </div>
                        ${helpers.renderContinuityIssueList(segmentContinuity)}
                        <div class="timeline-actions">
                          <button
                            type="button"
                            class="secondary small"
                            data-auto-repair-segment="${escapeAttr(segment.segmentId)}"
                            data-project-id="${escapeAttr(rootTask.project_id)}"
                            data-source-task="${escapeAttr(rootTask.task_id)}"
                            ${canRunRepair ? "" : "disabled"}
                          >
                            ${escapeHtml(helpers.buildSegmentRepairButtonLabel(
                              segment,
                              repairTaskStatus,
                              segmentRepairRemainingActions.length > 0,
                            ))}
                          </button>
                          <button
                            type="button"
                            class="secondary small${sceneRecommended ? " recommended-action" : ""}"
                            data-generate-scene-segment="${escapeAttr(segment.segmentId)}"
                            data-scene-id="${escapeAttr(segment.sceneId)}"
                            data-project-id="${escapeAttr(rootTask.project_id)}"
                            data-source-task="${escapeAttr(rootTask.task_id)}"
                            ${canGenerateScene ? "" : "disabled"}
                          >
                            ${escapeHtml(
                              canGenerateScene
                                ? helpers.buildSegmentSceneButtonLabel(segment, sceneTaskStatus)
                                : helpers.buildBlockedSceneButtonLabel(segment, sceneTaskStatus, characterStatus),
                            )}
                          </button>
                          <button
                            type="button"
                            class="secondary small${videoRecommended ? " recommended-action" : ""}"
                            data-generate-video-segment="${escapeAttr(segment.segmentId)}"
                            data-project-id="${escapeAttr(rootTask.project_id)}"
                            data-source-task="${escapeAttr(rootTask.task_id)}"
                            ${canGenerateVideo ? "" : "disabled"}
                          >
                            ${escapeHtml(helpers.buildSegmentVideoButtonLabel(segment, videoTaskStatus))}
                          </button>
                        </div>
                        ${helpers.renderSegmentTaskError(repairTask, "智能修复失败")}
                        ${helpers.renderRepairPlanNotice(repairTask, segmentRepairRemainingActions)}
                        ${canGenerateScene
                          ? ""
                          : helpers.renderSegmentSceneBlockedNotice({
                            segment,
                            characterStatus,
                            sceneScopeLocked,
                            segmentRepairLocked,
                            sceneTaskStatus,
                            videoTaskStatus,
                          })}
                        ${helpers.renderSegmentTaskError(sceneTask, "场景图失败")}
                        ${helpers.renderSegmentTaskError(videoTask, "视频失败")}
                      </div>
                    </article>
                  `;
                  },
                )
                .join("")}
                      </div>
                    </section>
                  `;
                  },
                )
                .join("")}
            </div>
          `
          : singleAssetMessage("暂无片段资产", helpers.buildArtifactPendingMessage(task, "images", run))
      }
    </section>
  `;
}
