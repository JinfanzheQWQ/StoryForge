import { getRunStageStatus } from "../utils.js";

export function getLatestSegmentStageTask(run, taskType, segmentId) {
  return run?.tasks?.find((task) => (
    task.task_type === taskType
    && String(task.payload?.segment_id || task.result?.segment_id || "") === String(segmentId || "")
  )) || null;
}

export function getLatestSceneMasterTask(run, sceneId) {
  return run?.tasks?.find((task) => (
    task.task_type === "project.scenes"
    && Boolean(task.payload?.master_only || task.result?.master_only)
    && String(task.payload?.scene_id || task.result?.scene_id || "") === String(sceneId || "")
  )) || null;
}

export function getLatestSceneRepairTask(run, sceneId) {
  return run?.tasks?.find((task) => (
    task.task_type === "project.continuity_repair"
    && String(task.payload?.scene_id || task.result?.scene_id || "") === String(sceneId || "")
    && !String(task.payload?.segment_id || task.result?.segment_id || "")
  )) || null;
}

export function getLatestBatchRepairTask(run) {
  return run?.tasks?.find((task) => task.task_type === "project.continuity_repair_batch") || null;
}

function taskCreatedTimestamp(task) {
  const value = Date.parse(String(task?.created_at || ""));
  return Number.isFinite(value) ? value : 0;
}

export function isBusyTaskStatus(status) {
  return status === "queued" || status === "running";
}

function isTaskStartedAfter(task, referenceTask, storySourceRevision) {
  if (!task || !referenceTask) {
    return false;
  }
  if (taskCreatedTimestamp(task) <= taskCreatedTimestamp(referenceTask)) {
    return false;
  }
  const status = getRunStageStatus(task, storySourceRevision);
  return status === "queued" || status === "running" || status === "completed";
}

export function getRepairAffectedSegmentIds(task) {
  return new Set(
    (Array.isArray(task?.result?.affected_segment_ids) ? task.result.affected_segment_ids : [])
      .map((segmentId) => String(segmentId || "").trim())
      .filter(Boolean),
  );
}

function hasLaterMatchingTask(run, repairTask, storySourceRevision, matcher) {
  return (run?.tasks || []).some(
    (task) => matcher(task) && isTaskStartedAfter(task, repairTask, storySourceRevision),
  );
}

function hasSegmentStageCoverage(run, repairTask, storySourceRevision, taskType, segmentIds) {
  const targets = Array.from(segmentIds).filter(Boolean);
  if (!targets.length) {
    return false;
  }
  return targets.every((segmentId) => hasLaterMatchingTask(
    run,
    repairTask,
    storySourceRevision,
    (task) => task.task_type === taskType
      && String(task.payload?.segment_id || task.result?.segment_id || "") === segmentId,
  ));
}

export function resolveRepairRemainingActions(run, repairTask, storySourceRevision) {
  if (!repairTask || repairTask.status !== "completed" || !repairTask.result?.media_regeneration_required) {
    return [];
  }
  const pendingActions = Array.isArray(repairTask.result?.pending_media_actions)
    ? repairTask.result.pending_media_actions
      .map((action) => String(action || "").trim())
      .filter(Boolean)
    : [];
  if (!pendingActions.length) {
    return [];
  }

  const sceneId = String(repairTask.payload?.scene_id || repairTask.result?.scene_id || "").trim();
  const segmentId = String(repairTask.payload?.segment_id || repairTask.result?.segment_id || "").trim();
  const affectedSegmentIds = getRepairAffectedSegmentIds(repairTask);
  if (!affectedSegmentIds.size && segmentId) {
    affectedSegmentIds.add(segmentId);
  }

  return pendingActions.filter((action) => {
    if (action === "regenerate_scene_master_frame") {
      return !hasLaterMatchingTask(
        run,
        repairTask,
        storySourceRevision,
        (task) => (
          task.task_type === "project.scenes"
          && Boolean(task.payload?.master_only || task.result?.master_only)
          && String(task.payload?.scene_id || task.result?.scene_id || "") === sceneId
        ),
      );
    }

    if (action === "regenerate_scene_images") {
      const coveredByBroadTask = hasLaterMatchingTask(
        run,
        repairTask,
        storySourceRevision,
        (task) => (
          (
            task.task_type === "project.scenes"
            && !task.payload?.master_only
            && !task.payload?.segment_id
            && !task.payload?.scene_id
          )
          || (
            task.task_type === "project.scenes"
            && !task.payload?.master_only
            && sceneId
            && String(task.payload?.scene_id || task.result?.scene_id || "") === sceneId
          )
        ),
      );
      if (coveredByBroadTask) {
        return false;
      }
      return !hasSegmentStageCoverage(run, repairTask, storySourceRevision, "project.scenes", affectedSegmentIds);
    }

    if (action === "regenerate_video") {
      const coveredByBroadTask = hasLaterMatchingTask(
        run,
        repairTask,
        storySourceRevision,
        (task) => (
          (
            task.task_type === "project.videos"
            && !task.payload?.merge_only
            && !task.payload?.segment_id
            && !task.payload?.scene_id
          )
          || (
            task.task_type === "project.videos"
            && !task.payload?.merge_only
            && sceneId
            && String(task.payload?.scene_id || task.result?.scene_id || "") === sceneId
          )
        ),
      );
      if (coveredByBroadTask) {
        return false;
      }
      return !hasSegmentStageCoverage(run, repairTask, storySourceRevision, "project.videos", affectedSegmentIds);
    }

    return true;
  });
}

export function buildSceneMasterButtonLabel(sceneGroup, sceneMasterTaskStatus) {
  if (isBusyTaskStatus(sceneMasterTaskStatus)) {
    return "场景母图生成中";
  }
  if (sceneGroup.sceneMasterFrame) {
    return "重生成场景母图";
  }
  if (sceneMasterTaskStatus === "failed") {
    return "重试场景母图";
  }
  return "生成场景母图";
}

export function buildSceneRepairButtonLabel(sceneRepairTaskStatus, hasPendingActions) {
  if (isBusyTaskStatus(sceneRepairTaskStatus)) {
    return "智能修复中";
  }
  if (sceneRepairTaskStatus === "failed") {
    return "重试智能修复";
  }
  if (hasPendingActions) {
    return "修复方案已更新";
  }
  if (sceneRepairTaskStatus === "completed") {
    return "重新智能修复";
  }
  return "智能修复场景";
}

export function buildBatchRepairButtonLabel(batchRepairTaskStatus, batchRepairTask) {
  if (isBusyTaskStatus(batchRepairTaskStatus)) {
    return "批量修复中";
  }
  if (batchRepairTaskStatus === "failed") {
    return "重试批量修复";
  }
  if (batchRepairTask?.result?.has_more_batches) {
    return "继续修下一批";
  }
  if (batchRepairTaskStatus === "completed") {
    return "重新批量修复";
  }
  return "一键修复风险合同";
}

export function buildSegmentSceneButtonLabel(segment, sceneTaskStatus) {
  if (isBusyTaskStatus(sceneTaskStatus)) {
    return "场景母图生成中";
  }
  if (segment.sceneReady) {
    return "重生成场景母图";
  }
  if (sceneTaskStatus === "failed") {
    return "重试场景母图";
  }
  return "生成场景母图";
}

export function buildBlockedSceneButtonLabel(segment, sceneTaskStatus, characterStatus) {
  if (characterStatus === "failed") {
    return "角色图失败";
  }
  if (characterStatus === "stale") {
    return "先重生成角色图";
  }
  if (characterStatus === "queued" || characterStatus === "running") {
    return "角色图生成中";
  }
  if (characterStatus !== "completed" && !segment.sceneReady) {
    return "先生成角色图";
  }
  return buildSegmentSceneButtonLabel(segment, sceneTaskStatus);
}

export function buildSegmentVideoButtonLabel(segment, videoTaskStatus) {
  if (isBusyTaskStatus(videoTaskStatus)) {
    return "视频生成中";
  }
  if (segment.videoReady) {
    return "重生成视频";
  }
  if (videoTaskStatus === "failed") {
    return "重试视频";
  }
  return "生成视频";
}

export function buildSegmentRepairButtonLabel(segment, repairTaskStatus, hasPendingActions) {
  if (isBusyTaskStatus(repairTaskStatus)) {
    return "智能修复中";
  }
  if (hasPendingActions) {
    return "修复合同已更新";
  }
  if (segment.videoReady || segment.sceneReady) {
    return "重新智能修复";
  }
  if (repairTaskStatus === "failed") {
    return "重试智能修复";
  }
  return "智能修复该段";
}

export function buildMergeButtonLabel(artifacts, mergeTaskStatus) {
  if (mergeTaskStatus === "queued" || mergeTaskStatus === "running") {
    return "合并中";
  }
  if (artifacts?.full_story) {
    return "重新合并总片";
  }
  if (mergeTaskStatus === "failed") {
    return "重试合并";
  }
  return "合并已生成片段";
}
