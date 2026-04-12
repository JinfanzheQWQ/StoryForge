import { findGalleryIndex, registerGallery } from "../gallery.js";
import {
  buildArtifactPendingMessage,
  buildOverviewNote,
  chip,
  escapeAttr,
  escapeHtml,
  formatShortTime,
  kindLabel,
  metricCard,
  singleAssetMessage,
  stageStatusLabel,
  statusLabel,
} from "../utils.js";

function renderDocumentBlock(title, items) {
  if (!items?.length) {
    return singleAssetMessage(title, "暂无文件。");
  }

  return `
    <article class="asset-block">
      <h4>${title}</h4>
      <div class="doc-link-list">
        ${items
          .map(
            (item) => `
              <a class="doc-link" href="${item.url}" target="_blank" rel="noreferrer">
                <span class="kind-tag">${kindLabel(item.kind)}</span>
                <strong>${escapeHtml(item.name)}</strong>
              </a>
            `,
          )
          .join("")}
      </div>
    </article>
  `;
}

function renderMediaCard(item, galleryId) {
  const index = findGalleryIndex(galleryId, item);
  const isVideo = item.kind === "video";
  const preview = isVideo
    ? `<video controls preload="metadata" src="${item.url}"></video>`
    : `<img src="${item.url}" alt="${escapeAttr(item.name)}" loading="lazy" />`;
  const note = isVideo ? "可在预览里继续切换其他视频内容。" : "可在预览里继续切换其他图片内容。";

  return `
    <article class="media-card">
      <button
        type="button"
        class="preview-trigger"
        data-preview-group="${escapeAttr(galleryId)}"
        data-preview-index="${index}"
      >
        ${preview}
      </button>
      <div class="asset-meta">
        <a href="${item.url}" target="_blank" rel="noreferrer">${escapeHtml(item.name)}</a>
      </div>
      <p class="asset-note">${note}</p>
    </article>
  `;
}

function renderMediaBlock(title, items, galleryId) {
  if (!items?.length) {
    return singleAssetMessage(title, "暂无可预览内容。");
  }

  return `
    <article class="asset-block">
      <h4>${title}</h4>
      <div class="media-grid">
        ${items.map((item) => renderMediaCard(item, galleryId)).join("")}
      </div>
    </article>
  `;
}

function renderFullStoryBlock(item, context, galleryId = null) {
  if (!item) {
    return singleAssetMessage("总片", "当前版本还没有生成完整成片。");
  }

  const effectiveGroupId = galleryId || `${context}:full:${item.path}`;
  if (!galleryId) {
    registerGallery(effectiveGroupId, [{ ...item, kind: "video" }]);
  }
  const index = findGalleryIndex(effectiveGroupId, item);

  return `
    <article class="asset-block">
      <h4>总片预览</h4>
      <button
        type="button"
        class="preview-trigger"
        data-preview-group="${escapeAttr(effectiveGroupId)}"
        data-preview-index="${index}"
      >
        <video class="hero-video" controls preload="metadata" src="${item.url}"></video>
      </button>
      <div class="asset-meta">
        <a href="${item.url}" target="_blank" rel="noreferrer">${escapeHtml(item.name)}</a>
      </div>
      <p class="asset-note">打开预览后可以继续切换其他视频内容。</p>
    </article>
  `;
}

function renderOverviewTab(task, artifacts, context, run = null) {
  return `
    <section class="asset-grid">
      <article class="asset-block">
        <h4>制作概览</h4>
        <div class="detail-metrics">
          ${metricCard("创建时间", formatShortTime(task.created_at))}
          ${metricCard("角色图", String(artifacts?.character_images?.length || 0))}
          ${metricCard("场景帧", String(artifacts?.scene_frames?.length || 0))}
          ${metricCard("片段视频", String(artifacts?.rendered_clips?.length || 0))}
        </div>
        <p class="asset-note">${escapeHtml(buildOverviewNote(task, artifacts, run))}</p>
      </article>
      ${renderFullStoryBlock(artifacts?.full_story, context)}
    </section>
  `;
}

function renderDocsTab(task, artifacts, run = null) {
  if (!artifacts?.available) {
    return singleAssetMessage("文档暂不可用", buildArtifactPendingMessage(task, "docs", run));
  }

  return `
    <section class="asset-grid">
      ${renderDocumentBlock("结构化文件", artifacts.documents)}
      ${renderDocumentBlock("章节草稿", artifacts.chapters)}
    </section>
  `;
}

function renderImagesTab(task, artifacts, context, run = null) {
  if (!artifacts?.available) {
    return singleAssetMessage("图片暂不可用", buildArtifactPendingMessage(task, "images", run));
  }
  if (
    run
    && run.latestTask.task_type === "project.story"
    && !artifacts.character_images.length
    && !artifacts.scene_frames.length
  ) {
    return singleAssetMessage("图片暂不可用", buildArtifactPendingMessage(task, "images", run));
  }

  const galleryId = `${context}:images:${task.task_id}`;
  registerGallery(
    galleryId,
    [
      ...artifacts.character_images.map((item) => ({ ...item, kind: "image" })),
      ...artifacts.scene_frames.map((item) => ({ ...item, kind: "image" })),
    ],
  );

  return `
    <section class="asset-grid">
      ${
        artifacts.character_images.length
          ? renderMediaBlock("角色定妆图", artifacts.character_images, galleryId)
          : singleAssetMessage("角色定妆图", buildArtifactPendingMessage(task, "characters", run))
      }
      ${
        artifacts.scene_frames.length
          ? renderMediaBlock("场景首尾帧", artifacts.scene_frames, galleryId)
          : singleAssetMessage("场景首尾帧", buildArtifactPendingMessage(task, "scenes", run))
      }
    </section>
  `;
}

function renderVideosTab(task, artifacts, context, run = null) {
  if (!artifacts?.available) {
    return singleAssetMessage("视频暂不可用", buildArtifactPendingMessage(task, "videos", run));
  }
  if (
    run
    && run.latestTask.task_type !== "project.videos"
    && !artifacts.rendered_clips.length
    && !artifacts.full_story
  ) {
    return singleAssetMessage("视频暂不可用", buildArtifactPendingMessage(task, "videos", run));
  }

  const galleryId = `${context}:videos:${task.task_id}`;
  registerGallery(
    galleryId,
    [
      ...(artifacts.full_story ? [{ ...artifacts.full_story, kind: "video" }] : []),
      ...artifacts.rendered_clips.map((item) => ({ ...item, kind: "video" })),
    ],
  );

  return `
    <section class="asset-grid">
      ${renderFullStoryBlock(artifacts.full_story, context, galleryId)}
      ${renderMediaBlock("视频片段", artifacts.rendered_clips, galleryId)}
    </section>
  `;
}

export function renderRunStageActions(run) {
  const rootTask = run.rootTask;
  if (!rootTask || rootTask.task_type === "project.build") {
    return "";
  }

  const characterStatus = run.latestCharacterTask?.status || "idle";
  const sceneStatus = run.latestSceneTask?.status || "idle";
  const videoStatus = run.latestVideoTask?.status || "idle";
  const canGenerateCharacters =
    rootTask.status === "completed" && !["queued", "running", "completed"].includes(characterStatus);
  const canGenerateScenes =
    characterStatus === "completed" && !["queued", "running", "completed"].includes(sceneStatus);
  const canGenerateVideos =
    sceneStatus === "completed" && !["queued", "running", "completed"].includes(videoStatus);

  const characterButtonLabel =
    characterStatus === "failed" ? "重试角色图" : characterStatus === "completed" ? "角色图已完成" : characterStatus === "running" ? "角色图生成中" : "生成角色图";
  const sceneButtonLabel =
    sceneStatus === "failed" ? "重试场景图" : sceneStatus === "completed" ? "场景图已完成" : sceneStatus === "running" ? "场景图生成中" : "生成场景图";
  const videoButtonLabel =
    videoStatus === "failed" ? "重试视频" : videoStatus === "completed" ? "视频已完成" : videoStatus === "running" ? "视频生成中" : "生成视频";

  return `
    <div class="detail-chip-row">
      ${chip(`故事 ${statusLabel(rootTask.status)}`)}
      ${chip(`角色 ${stageStatusLabel(characterStatus)}`)}
      ${chip(`场景 ${stageStatusLabel(sceneStatus)}`)}
      ${chip(`视频 ${stageStatusLabel(videoStatus)}`)}
    </div>
    <div class="action-row">
      <button
        type="button"
        class="secondary"
        data-generate-characters="${escapeAttr(rootTask.task_id)}"
        ${canGenerateCharacters ? "" : "disabled"}
      >
        ${escapeHtml(characterButtonLabel)}
      </button>
      <button
        type="button"
        class="secondary"
        data-generate-scenes="${escapeAttr(rootTask.task_id)}"
        ${canGenerateScenes ? "" : "disabled"}
      >
        ${escapeHtml(sceneButtonLabel)}
      </button>
      <button
        type="button"
        class="secondary"
        data-generate-videos="${escapeAttr(rootTask.task_id)}"
        ${canGenerateVideos ? "" : "disabled"}
      >
        ${escapeHtml(videoButtonLabel)}
      </button>
    </div>
  `;
}

export function renderRunTabContent(task, artifacts, context, activeTab, run = null) {
  if (activeTab === "docs") {
    return renderDocsTab(task, artifacts, run);
  }
  if (activeTab === "images") {
    return renderImagesTab(task, artifacts, context, run);
  }
  if (activeTab === "videos") {
    return renderVideosTab(task, artifacts, context, run);
  }
  return renderOverviewTab(task, artifacts, context, run);
}
