import {
  buildTaskErrorMessage,
  escapeHtml,
} from "../utils.js";
import { isBusyTaskStatus } from "./task_state.js";

export function renderAssetSectionIntro(title, summary, chipsMarkup = "") {
  return `
    <article class="asset-block story-editor-hero">
      <div class="story-editor-head">
        <div>
          <h4>${title}</h4>
          <p class="asset-note">${escapeHtml(summary)}</p>
        </div>
        ${chipsMarkup ? `<div class="detail-chip-row">${chipsMarkup}</div>` : ""}
      </div>
    </article>
  `;
}

export function renderSegmentTaskError(task, label) {
  const error = buildTaskErrorMessage(task);
  if (!error) {
    return "";
  }
  return `<p class="timeline-task-error">${escapeHtml(`${label}：${error}`)}</p>`;
}

export function renderSegmentSceneBlockedNotice({
  segment,
  characterStatus,
  sceneScopeLocked,
  segmentRepairLocked,
  sceneTaskStatus,
  videoTaskStatus,
}) {
  if (characterStatus !== "completed") {
    if (characterStatus === "failed") {
      return '<p class="asset-note">角色图生成失败。请先重试角色图，再生成场景图。</p>';
    }
    if (characterStatus === "stale") {
      return '<p class="asset-note">角色图仍然对应旧文本版本。请先重新生成角色图，再生成场景图。</p>';
    }
    if (characterStatus === "queued" || characterStatus === "running") {
      return '<p class="asset-note">角色图正在生成。角色参考图完成后，这一段才能生成场景图。</p>';
    }
    if (!segment.sceneReady) {
      return '<p class="asset-note">请先生成角色图。场景图阶段依赖角色参考图，所以当前按钮会先锁定。</p>';
    }
  }
  if (sceneScopeLocked) {
    return '<p class="asset-note">当前 scene 正在修复或生成场景母图，暂时不能并发生成片段场景图。</p>';
  }
  if (segmentRepairLocked) {
    return '<p class="asset-note">当前片段正在智能修复。请等待修复完成后再生成场景图。</p>';
  }
  if (isBusyTaskStatus(sceneTaskStatus)) {
    return '<p class="asset-note">当前片段场景图正在生成，页面会自动刷新状态。</p>';
  }
  if (isBusyTaskStatus(videoTaskStatus)) {
    return '<p class="asset-note">当前片段视频正在生成，暂时不允许并发重跑场景图。</p>';
  }
  return "";
}
