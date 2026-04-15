import { state } from "../state.js";
import { findGalleryIndex, registerGallery } from "../gallery.js";
import {
  getStorySourceDraft,
  getStorySourceMeta,
  resolveStorySourceLocator,
} from "../story_source.js";
import {
  buildArtifactPendingMessage,
  buildOverviewNote,
  buildTaskErrorMessage,
  chip,
  escapeAttr,
  escapeHtml,
  formatShortTime,
  getRunStageStatus,
  getStorySourceRevision,
  kindLabel,
  metricCard,
  singleAssetMessage,
  stageStatusLabel,
  statusLabel,
} from "../utils.js";

const DOCUMENT_META = {
  "story_source.json": {
    title: "故事正文源文件",
    category: "小说源",
    summary: "当前版本的事实文本源。保存正文后，结构化分析和媒体阶段都从这里继续。",
  },
  "novel_package.json": {
    title: "小说分析总包",
    category: "小说分析",
    summary: "运行态最小小说包，包含角色卡、章节规划和正文摘录，是图片与视频阶段的正式输入。",
  },
  "novel_audit.json": {
    title: "小说分析审计包",
    category: "小说分析",
    summary: "保存 review、workflow_trace，以及从运行包中剥离的分析上下文，主要用于排错和人工审阅。",
  },
  "character_visual_bible.json": {
    title: "角色视觉设定",
    category: "视频规划",
    summary: "定义角色外观、服装、配色和定妆提示词，用来锁定视觉一致性。",
  },
  "character_image_manifest.json": {
    title: "角色图任务清单",
    category: "视频规划",
    summary: "记录每个角色图要怎么生成、输出到哪里，以及当前状态。",
  },
  "segment_plan.json": {
    title: "视频分段规划",
    category: "视频规划",
    summary: "定义每个片段的参与角色、对白、字幕、时长，以及首帧 / 中段锚点帧 / 尾帧提示词。",
  },
  "scene_image_manifest.json": {
    title: "场景帧任务清单",
    category: "视频规划",
    summary: "记录每个片段的首帧、中段锚点帧、尾帧、角色参考图和输出位置。",
  },
  "seedream_character_execution.json": {
    title: "角色图执行报告",
    category: "执行报告",
    summary: "用来确认角色图阶段是否真正跑通，以及失败原因。",
  },
  "seedream_scene_execution.json": {
    title: "场景图执行报告",
    category: "执行报告",
    summary: "用来确认场景关键帧阶段是否真正跑通，以及失败原因。",
  },
  "seedance_manifest.json": {
    title: "视频提交清单",
    category: "视频提交",
    summary: "最终送给 Seedance 的 clip 列表，决定视频片段会如何被生成。",
  },
  "seedance_execution.json": {
    title: "视频执行报告",
    category: "执行报告",
    summary: "记录视频提交状态、完成数量、失败数量和下载结果。",
  },
};

function renderStageFailureList(run, storySourceRevision) {
  const failedStages = [
    ["结构化信息", run.latestAnalysisTask],
    ["角色图", run.latestCharacterTask],
    ["场景图", run.latestSceneTask],
    ["视频", run.latestVideoTask],
    ["合并", run.latestMergeTask],
  ]
    .map(([label, task]) => {
      const status = getRunStageStatus(task, storySourceRevision);
      const error = buildTaskErrorMessage(task);
      if (status !== "failed" || !error) {
        return "";
      }
      return `
        <article class="stage-error-item">
          <strong>${escapeHtml(label)}</strong>
          <p>${escapeHtml(error)}</p>
        </article>
      `;
    })
    .filter(Boolean);

  if (failedStages.length === 0) {
    return "";
  }

  return `
    <div class="stage-error-list">
      ${failedStages.join("")}
    </div>
  `;
}

const DOCUMENT_GROUP_ORDER = ["小说源", "小说分析", "视频规划", "视频提交", "执行报告", "其他文件"];

function groupDocuments(items) {
  const groups = new Map();
  items.forEach((item) => {
    const group = DOCUMENT_META[item.name]?.category || "其他文件";
    if (!groups.has(group)) {
      groups.set(group, []);
    }
    groups.get(group).push(item);
  });
  return DOCUMENT_GROUP_ORDER
    .filter((group) => groups.has(group))
    .map((group) => ({ title: group, items: groups.get(group) }));
}

function renderDocumentCard(item) {
  const meta = DOCUMENT_META[item.name] || {
    title: item.name,
    category: "其他文件",
    summary: "当前运行留下的附加文件，可按需打开查看原始内容。",
  };
  return `
    <article class="doc-card">
      <div class="doc-card-head">
        <span class="kind-tag">${escapeHtml(meta.category)}</span>
        <span class="doc-card-file">${escapeHtml(item.name)}</span>
      </div>
      <h5>${escapeHtml(meta.title)}</h5>
      <p>${escapeHtml(meta.summary)}</p>
      <div class="doc-card-actions">
        <a class="doc-link" href="${item.url}" target="_blank" rel="noreferrer">
          <span class="kind-tag">${kindLabel(item.kind)}</span>
          <strong>打开文件</strong>
        </a>
      </div>
    </article>
  `;
}

function renderDocumentBlock(title, items, summary = "") {
  if (!items?.length) {
    return singleAssetMessage(title, "暂无文件。");
  }

  return `
    <article class="asset-block">
      <div class="doc-section-head">
        <div>
          <h4>${title}</h4>
          ${summary ? `<p class="asset-note">${escapeHtml(summary)}</p>` : ""}
        </div>
        <span class="doc-section-count">${items.length} 份</span>
      </div>
      <div class="doc-card-grid">
        ${items.map((item) => renderDocumentCard(item)).join("")}
      </div>
    </article>
  `;
}

function renderAssetSectionIntro(title, summary, chipsMarkup = "") {
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

function renderMediaBlock(title, items, galleryId, summary = "") {
  if (!items?.length) {
    return singleAssetMessage(title, "暂无可预览内容。");
  }

  return `
    <article class="asset-block">
      <div class="doc-section-head">
        <div>
          <h4>${title}</h4>
          ${summary ? `<p class="asset-note">${escapeHtml(summary)}</p>` : ""}
        </div>
        <span class="doc-section-count">${items.length} 份</span>
      </div>
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

function segmentIdFromAssetName(name) {
  return String(name || "")
    .replace(/\.[^.]+$/, "")
    .replace(/_(start|mid|end)$/, "");
}

function segmentLabel(segmentId, index) {
  const text = String(segmentId || "").trim();
  if (!text) {
    return `片段 ${index + 1}`;
  }
  return text
    .replace(/^ch(\d+)_seg(\d+)$/i, "第 $1 章 / 片段 $2")
    .replaceAll("_", " ");
}

function buildTimelineSegments(artifacts) {
  if (artifacts?.planned_segments?.length) {
    return artifacts.planned_segments.map((segment, index) => ({
      segmentId: segment.segment_id,
      title: segment.title || segmentLabel(segment.segment_id, index),
      summary: segment.summary || "",
      chapterNumber: segment.chapter_number,
      durationSeconds: segment.duration_seconds || 0,
      requiresMidFrame: Boolean(segment.requires_mid_frame),
      startFrame: segment.start_frame ? { ...segment.start_frame, kind: "image" } : null,
      midFrame: segment.mid_frame ? { ...segment.mid_frame, kind: "image" } : null,
      endFrame: segment.end_frame ? { ...segment.end_frame, kind: "image" } : null,
      clip: segment.rendered_clip ? { ...segment.rendered_clip, kind: "video" } : null,
      sceneReady: Boolean(segment.scene_ready),
      videoReady: Boolean(segment.video_ready),
    }));
  }

  const segmentMap = new Map();
  const ensureSegment = (segmentId) => {
    if (!segmentMap.has(segmentId)) {
      segmentMap.set(segmentId, {
        segmentId,
        title: segmentId,
        summary: "",
        chapterNumber: 0,
        durationSeconds: 0,
        requiresMidFrame: false,
        startFrame: null,
        midFrame: null,
        endFrame: null,
        clip: null,
        sceneReady: false,
        videoReady: false,
      });
    }
    return segmentMap.get(segmentId);
  };

  for (const frame of artifacts?.scene_frames || []) {
    const segmentId = segmentIdFromAssetName(frame.name);
    const segment = ensureSegment(segmentId);
    if (String(frame.name).includes("_end")) {
      segment.endFrame = frame;
    } else if (String(frame.name).includes("_mid")) {
      segment.midFrame = frame;
    } else {
      segment.startFrame = frame;
    }
  }

  for (const clip of artifacts?.rendered_clips || []) {
    const segment = ensureSegment(segmentIdFromAssetName(clip.name));
    segment.clip = clip;
  }

  return Array.from(segmentMap.values())
    .sort((left, right) => left.segmentId.localeCompare(right.segmentId))
    .map((segment, index) => ({
      ...segment,
      title: segment.title || segmentLabel(segment.segmentId, index),
      sceneReady: Boolean(
        segment.startFrame
        && segment.endFrame
        && (!segment.requiresMidFrame || segment.midFrame),
      ),
      videoReady: Boolean(segment.clip),
    }));
}

function getLatestSegmentStageTask(run, taskType, segmentId) {
  return run?.tasks?.find((task) => (
    task.task_type === taskType
    && String(task.payload?.segment_id || task.result?.segment_id || "") === String(segmentId || "")
  )) || null;
}

function buildSegmentSceneButtonLabel(segment, sceneTaskStatus) {
  if (sceneTaskStatus === "queued" || sceneTaskStatus === "running") {
    return "场景图生成中";
  }
  if (segment.sceneReady) {
    return "重生成场景图";
  }
  if (sceneTaskStatus === "failed") {
    return "重试场景图";
  }
  return "生成场景图";
}

function buildSegmentVideoButtonLabel(segment, videoTaskStatus) {
  if (videoTaskStatus === "queued" || videoTaskStatus === "running") {
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

function buildMergeButtonLabel(artifacts, mergeTaskStatus) {
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

function renderSegmentTaskError(task, label) {
  const error = buildTaskErrorMessage(task);
  if (!error) {
    return "";
  }
  return `<p class="timeline-task-error">${escapeHtml(`${label}：${error}`)}</p>`;
}

function buildTimelineGalleryItems(artifacts) {
  const plannedItems = (artifacts?.planned_segments || []).flatMap((segment) => ([
    segment.start_frame ? { ...segment.start_frame, kind: "image" } : null,
    segment.mid_frame ? { ...segment.mid_frame, kind: "image" } : null,
    segment.end_frame ? { ...segment.end_frame, kind: "image" } : null,
    segment.rendered_clip ? { ...segment.rendered_clip, kind: "video" } : null,
  ])).filter(Boolean);
  if (plannedItems.length) {
    return [
      ...(artifacts.full_story ? [{ ...artifacts.full_story, kind: "video" }] : []),
      ...plannedItems,
    ];
  }
  return [
    ...artifacts.scene_frames.map((item) => ({ ...item, kind: "image" })),
    ...(artifacts.full_story ? [{ ...artifacts.full_story, kind: "video" }] : []),
    ...artifacts.rendered_clips.map((item) => ({ ...item, kind: "video" })),
  ];
}

function renderTimelinePreview(item, label, galleryId) {
  if (!item) {
    return `
      <div class="timeline-empty-preview">
        <span>${escapeHtml(label)}</span>
        <strong>未生成</strong>
      </div>
    `;
  }
  const index = findGalleryIndex(galleryId, item);
  const preview = item.kind === "video"
    ? `<video preload="metadata" src="${item.url}"></video>`
    : `<img src="${item.url}" alt="${escapeAttr(item.name)}" loading="lazy" />`;
  return `
    <button
      type="button"
      class="timeline-preview"
      data-preview-group="${escapeAttr(galleryId)}"
      data-preview-index="${index}"
    >
      <span>${escapeHtml(label)}</span>
      ${preview}
    </button>
  `;
}

function renderTimelineTab(task, artifacts, context, run = null) {
  if (!artifacts?.available) {
    return singleAssetMessage("片段时间线暂不可用", buildArtifactPendingMessage(task, "images", run));
  }

  const timelineItems = buildTimelineGalleryItems(artifacts);
  const galleryId = `${context}:timeline:${task.task_id}`;
  registerGallery(galleryId, timelineItems);
  const segments = buildTimelineSegments(artifacts);
  const rootTask = run?.rootTask || task;
  const storySourceRevision = run ? getStorySourceRevision(rootTask) : getStorySourceRevision(task);
  const characterStatus = run ? getRunStageStatus(run.latestCharacterTask, storySourceRevision) : "idle";
  const mergeTaskStatus = run ? getRunStageStatus(run.latestMergeTask, storySourceRevision) : "idle";
  const readySceneCount = segments.filter((segment) => segment.sceneReady).length;
  const readyVideoCount = segments.filter((segment) => segment.videoReady).length;
  const canMergeVideos = readyVideoCount >= 2 && !["queued", "running"].includes(mergeTaskStatus);

  return `
    <section class="timeline-shell">
      <article class="asset-block timeline-hero">
        <div>
          <p class="section-kicker">Timeline</p>
          <h4>按视频片段审片</h4>
          <p class="asset-note">结构化信息完成后，这里会按 LLM 生成的 segment_plan 逐段展示。每一段都可以单独生成场景图和视频，不再一次性把全部片段跑完。</p>
          <p class="asset-note">首帧、中段锚点帧、尾帧和视频片段会放在同一张卡里，便于逐段检查角色一致性、动作推进和字幕是否完整。</p>
        </div>
        <div class="detail-chip-row">
          ${chip(`片段 ${segments.length}`)}
          ${chip(`场景就绪 ${readySceneCount}/${segments.length || 0}`)}
          ${chip(`视频就绪 ${readyVideoCount}/${segments.length || 0}`)}
          ${chip(`总片 ${artifacts.full_story ? "已生成" : "未生成"}`)}
        </div>
        <div class="timeline-hero-actions">
          <button
            type="button"
            class="secondary"
            data-merge-videos="${escapeAttr(rootTask.task_id)}"
            data-project-id="${escapeAttr(rootTask.project_id)}"
            ${canMergeVideos ? "" : "disabled"}
          >
            ${escapeHtml(buildMergeButtonLabel(artifacts, mergeTaskStatus))}
          </button>
        </div>
      </article>

      ${artifacts.full_story ? renderFullStoryBlock(artifacts.full_story, context, galleryId) : ""}

      ${
        segments.length
          ? `
            <div class="timeline-list">
              ${segments
                .map(
                  (segment, index) => {
                    const sceneTask = getLatestSegmentStageTask(run, "project.scenes", segment.segmentId);
                    const videoTask = getLatestSegmentStageTask(run, "project.videos", segment.segmentId);
                    const sceneTaskStatus = run ? getRunStageStatus(sceneTask, storySourceRevision) : "idle";
                    const videoTaskStatus = run ? getRunStageStatus(videoTask, storySourceRevision) : "idle";
                    const canGenerateScene =
                      characterStatus === "completed"
                      && !["queued", "running"].includes(sceneTaskStatus);
                    const canGenerateVideo =
                      segment.sceneReady
                      && !["queued", "running"].includes(videoTaskStatus);
                    return `
                    <article class="timeline-card">
                      <div class="timeline-card-head">
                        <span class="timeline-index">${String(index + 1).padStart(2, "0")}</span>
                        <div>
                          <h4>${escapeHtml(segment.title || segmentLabel(segment.segmentId, index))}</h4>
                          <p class="asset-note">
                            ${escapeHtml(`${segment.chapterNumber ? `第 ${segment.chapterNumber} 章 · ` : ""}${segment.segmentId}${segment.durationSeconds ? ` · ${segment.durationSeconds}s` : ""}`)}
                          </p>
                        </div>
                      </div>
                      ${segment.summary ? `<p class="timeline-summary">${escapeHtml(segment.summary)}</p>` : ""}
                      <div class="timeline-preview-grid">
                        ${renderTimelinePreview(segment.startFrame, "首帧", galleryId)}
                        ${renderTimelinePreview(segment.midFrame, "中段", galleryId)}
                        ${renderTimelinePreview(segment.endFrame, "尾帧", galleryId)}
                        ${renderTimelinePreview(segment.clip, "视频", galleryId)}
                      </div>
                      <div class="timeline-card-footer">
                        <div class="detail-chip-row">
                          ${chip(`场景 ${segment.sceneReady ? "已就绪" : "待生成"}`)}
                          ${chip(`视频 ${segment.videoReady ? "已就绪" : "待生成"}`)}
                          ${segment.requiresMidFrame ? chip("含中段锚点") : chip("双帧片段")}
                        </div>
                        <div class="timeline-actions">
                          <button
                            type="button"
                            class="secondary small"
                            data-generate-scene-segment="${escapeAttr(segment.segmentId)}"
                            data-project-id="${escapeAttr(rootTask.project_id)}"
                            data-source-task="${escapeAttr(rootTask.task_id)}"
                            ${canGenerateScene ? "" : "disabled"}
                          >
                            ${escapeHtml(buildSegmentSceneButtonLabel(segment, sceneTaskStatus))}
                          </button>
                          <button
                            type="button"
                            class="secondary small"
                            data-generate-video-segment="${escapeAttr(segment.segmentId)}"
                            data-project-id="${escapeAttr(rootTask.project_id)}"
                            data-source-task="${escapeAttr(rootTask.task_id)}"
                            ${canGenerateVideo ? "" : "disabled"}
                          >
                            ${escapeHtml(buildSegmentVideoButtonLabel(segment, videoTaskStatus))}
                          </button>
                        </div>
                        ${renderSegmentTaskError(sceneTask, "场景图失败")}
                        ${renderSegmentTaskError(videoTask, "视频失败")}
                      </div>
                    </article>
                  `;
                  },
                )
                .join("")}
            </div>
          `
          : singleAssetMessage("暂无片段资产", buildArtifactPendingMessage(task, "images", run))
      }
    </section>
  `;
}

function renderOverviewTab(task, artifacts, context, run = null) {
  if (context === "project") {
    return renderTimelineTab(task, artifacts, context, run);
  }
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

function renderStoryTab(task, context, run = null) {
  const locator = resolveStorySourceLocator(task, run);
  if (!locator) {
    return singleAssetMessage("故事文本", "当前版本还没有可展示或编辑的故事正文。");
  }

  const storySource = getStorySourceDraft(locator.projectId, locator.sourceTaskId);
  const meta = getStorySourceMeta(locator.projectId, locator.sourceTaskId);
  if (meta.loading && !storySource) {
    return singleAssetMessage("故事文本", "故事正文加载中。");
  }
  if (!storySource) {
    return singleAssetMessage("故事文本", meta.message || "故事正文暂时不可用。");
  }

  const storySourceRevision = run ? getStorySourceRevision(run.rootTask) : storySource.story_source_revision;
  const analysisStatus = run ? getRunStageStatus(run.latestAnalysisTask, storySourceRevision) : "idle";
  const canAnalyze =
    !meta.loading
    && !meta.saving
    && !meta.dirty
    && !["queued", "running", "completed"].includes(analysisStatus);
  const analysisLabel =
    analysisStatus === "completed"
      ? "结构化已完成"
      : analysisStatus === "stale"
        ? "重新生成结构化信息"
        : analysisStatus === "running"
          ? "结构化生成中"
          : "生成结构化信息";
  const statusText =
    meta.message
    || (analysisStatus === "completed"
      ? "结构化信息已完成。继续生成角色图，或修改并保存正文后再重新生成结构化信息。"
      : analysisStatus === "stale"
        ? "故事文本已变更，旧的结构化结果已失效。请保存后重新生成结构化信息。"
        : "先检查并按需修改小说正文，保存后再进入结构化解析。");

  return `
    <section class="story-editor-shell">
      <article class="asset-block story-editor-hero">
        <div class="story-editor-head">
          <div>
            <h4>可编辑小说正文</h4>
            <p class="asset-note">这一层是当前版本的事实文本源。保存后，后续结构化 JSON、角色图、场景图和视频都应基于这份正文重新生成。</p>
          </div>
          <div class="story-editor-actions">
            <button
              type="button"
              class="secondary"
              data-story-source-project="${escapeAttr(locator.projectId)}"
              data-save-story-source="${escapeAttr(locator.sourceTaskId)}"
              ${meta.saving || meta.loading || !meta.dirty ? "disabled" : ""}
            >
              ${meta.saving ? "保存中" : meta.dirty ? "保存正文" : "已保存"}
            </button>
            <button
              type="button"
              class="secondary"
              data-story-source-project="${escapeAttr(locator.projectId)}"
              data-generate-story-analysis="${escapeAttr(locator.sourceTaskId)}"
              ${canAnalyze ? "" : "disabled"}
            >
              ${escapeHtml(analysisLabel)}
            </button>
          </div>
        </div>
        <div class="detail-chip-row">
          ${chip(`章节 ${storySource.chapters.length}`)}
          ${chip(`文本 ${meta.dirty ? "待保存" : "已保存"}`)}
          ${chip(`结构 ${stageStatusLabel(analysisStatus)}`)}
          ${storySource.story_source_revision ? chip(`修订 ${formatShortTime(storySource.story_source_revision)}`) : ""}
        </div>
        <p
          class="story-status-note"
          data-story-status-note="${escapeAttr(locator.sourceTaskId)}"
        >
          ${escapeHtml(statusText)}
        </p>
      </article>

      <article class="asset-block story-editor-card">
        <label class="story-field">
          <span>故事标题</span>
          <input
            type="text"
            value="${escapeAttr(storySource.story_title)}"
            data-story-title-input="true"
            data-story-source-project="${escapeAttr(locator.projectId)}"
            data-story-source-task="${escapeAttr(locator.sourceTaskId)}"
            ${meta.saving ? "disabled" : ""}
          />
        </label>
      </article>

      ${storySource.chapters
        .map(
          (chapter, index) => `
            <article class="asset-block story-editor-card">
              <div class="story-chapter-head">
                <h4>第 ${chapter.number} 章</h4>
                <span class="kind-tag">chapter</span>
              </div>
              <div class="story-field-grid">
                <label class="story-field">
                  <span>章节标题</span>
                  <input
                    type="text"
                    value="${escapeAttr(chapter.title)}"
                    data-story-chapter-field="title"
                    data-story-source-project="${escapeAttr(locator.projectId)}"
                    data-story-source-task="${escapeAttr(locator.sourceTaskId)}"
                    data-story-chapter-index="${index}"
                    ${meta.saving ? "disabled" : ""}
                  />
                </label>
                <label class="story-field">
                  <span>章节摘要</span>
                  <textarea
                    rows="4"
                    data-story-chapter-field="summary"
                    data-story-source-project="${escapeAttr(locator.projectId)}"
                    data-story-source-task="${escapeAttr(locator.sourceTaskId)}"
                    data-story-chapter-index="${index}"
                    ${meta.saving ? "disabled" : ""}
                  >${escapeHtml(chapter.summary)}</textarea>
                </label>
                <label class="story-field story-field-wide">
                  <span>章节正文</span>
                  <textarea
                    rows="14"
                    data-story-chapter-field="markdown"
                    data-story-source-project="${escapeAttr(locator.projectId)}"
                    data-story-source-task="${escapeAttr(locator.sourceTaskId)}"
                    data-story-chapter-index="${index}"
                    ${meta.saving ? "disabled" : ""}
                  >${escapeHtml(chapter.markdown)}</textarea>
                </label>
              </div>
            </article>
          `,
        )
        .join("")}
    </section>
  `;
}

function renderDocsTab(task, artifacts, run = null) {
  if (!artifacts?.available) {
    return singleAssetMessage("文档暂不可用", buildArtifactPendingMessage(task, "docs", run));
  }

  if (!artifacts.documents.length) {
    return singleAssetMessage("文档暂不可用", "当前运行没有额外落盘的文档文件。");
  }

  const documentGroups = groupDocuments(artifacts.documents);

  return `
    <section class="story-editor-shell">
      ${renderAssetSectionIntro(
        "运行文件面板",
        "这里只保留当前链路真正会继续消费的源文件，以及每一步的执行报告。",
        chip(`核心文件 ${artifacts.documents.length}`),
      )}
      ${documentGroups.map((group) => renderDocumentBlock(group.title, group.items)).join("")}
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
    <section class="story-editor-shell">
      ${renderAssetSectionIntro(
        "图像资产",
        "先看角色定妆，再看场景关键帧。当前页面只展示真实参与后续链路的图像资产。",
        [
          chip(`角色图 ${artifacts.character_images.length}`),
          chip(`场景帧 ${artifacts.scene_frames.length}`),
        ].join(""),
      )}
      ${
        artifacts.character_images.length
          ? renderMediaBlock(
            "角色定妆图",
            artifacts.character_images,
            galleryId,
            "角色基准参考图。后续场景关键帧和视频片段都会围绕这组角色外观继续生成。",
          )
          : singleAssetMessage("角色定妆图", buildArtifactPendingMessage(task, "characters", run))
      }
      ${
        artifacts.scene_frames.length
          ? renderMediaBlock(
            "场景关键帧",
            artifacts.scene_frames,
            galleryId,
            "每个片段的首帧、必要时的中段锚点帧，以及尾帧。它们共同决定镜头连续性、角色位置和空间氛围。",
          )
          : singleAssetMessage("场景关键帧", buildArtifactPendingMessage(task, "scenes", run))
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
  const rootTask = run?.rootTask || task;
  const storySourceRevision = run ? getStorySourceRevision(rootTask) : getStorySourceRevision(task);
  const mergeTaskStatus = run ? getRunStageStatus(run.latestMergeTask, storySourceRevision) : "idle";
  const canMergeVideos = artifacts.rendered_clips.length >= 2 && !["queued", "running"].includes(mergeTaskStatus);
  registerGallery(
    galleryId,
    [
      ...(artifacts.full_story ? [{ ...artifacts.full_story, kind: "video" }] : []),
      ...artifacts.rendered_clips.map((item) => ({ ...item, kind: "video" })),
    ],
  );

  return `
    <section class="story-editor-shell">
      ${renderAssetSectionIntro(
        "视频资产",
        "视频片段按 segment 单独生成。总片不再自动合并，需要你手动点击合并按钮决定是否输出完整成片。",
        [
          chip(`总片 ${artifacts.full_story ? "已生成" : "未生成"}`),
          chip(`片段 ${artifacts.rendered_clips.length}`),
        ].join(""),
      )}
      <article class="asset-block video-merge-card">
        <div class="story-editor-head">
          <div>
            <h4>总片合并</h4>
            <p class="asset-note">会按 seedance_manifest.json 顺序，把当前已经存在本地 mp4 的片段合并成 full_story.mp4。</p>
          </div>
          <div class="story-editor-actions">
            <button
              type="button"
              class="secondary"
              data-merge-videos="${escapeAttr(rootTask.task_id)}"
              data-project-id="${escapeAttr(rootTask.project_id)}"
              ${canMergeVideos ? "" : "disabled"}
            >
              ${escapeHtml(buildMergeButtonLabel(artifacts, mergeTaskStatus))}
            </button>
          </div>
        </div>
      </article>
      ${renderFullStoryBlock(artifacts.full_story, context, galleryId)}
      ${renderMediaBlock(
        "视频片段",
        artifacts.rendered_clips,
        galleryId,
        "按 segment 输出的独立片段，可用于逐段审片、比较效果和局部重跑。",
      )}
    </section>
  `;
}

export function renderRunStageActions(run) {
  const rootTask = run.rootTask;
  if (!rootTask || rootTask.task_type === "project.build") {
    return "";
  }

  const storySourceRevision = getStorySourceRevision(rootTask);
  const analysisStatus = getRunStageStatus(run.latestAnalysisTask, storySourceRevision);
  const characterStatus = getRunStageStatus(run.latestCharacterTask, storySourceRevision);
  const sceneStatus = getRunStageStatus(run.latestSceneTask, storySourceRevision);
  const videoStatus = getRunStageStatus(run.latestVideoTask, storySourceRevision);
  const mergeStatus = getRunStageStatus(run.latestMergeTask, storySourceRevision);
  const storyLocator = resolveStorySourceLocator(rootTask, run);
  const storyMeta = storyLocator
    ? getStorySourceMeta(storyLocator.projectId, storyLocator.sourceTaskId)
    : { dirty: false, loading: false, saving: false };
  const analysisReady = analysisStatus === "completed";
  const canGenerateAnalysis =
    rootTask.status === "completed"
    && !storyMeta.dirty
    && !storyMeta.loading
    && !storyMeta.saving
    && !["queued", "running", "completed"].includes(analysisStatus);
  const canGenerateCharacters =
    analysisReady && !["queued", "running", "completed"].includes(characterStatus);
  const plannedSegments = run.latestArtifacts?.planned_segments || [];
  const readySceneCount = plannedSegments.filter((segment) => segment.scene_ready).length;
  const readyVideoCount = plannedSegments.filter((segment) => segment.video_ready).length;
  const canMergeVideos = readyVideoCount >= 2 && !["queued", "running"].includes(mergeStatus);

  const analysisButtonLabel =
    analysisStatus === "failed" || analysisStatus === "stale"
      ? "重新生成结构化信息"
      : analysisStatus === "completed"
        ? "结构化已完成"
        : analysisStatus === "running"
          ? "结构化生成中"
          : "生成结构化信息";
  const characterButtonLabel =
    characterStatus === "failed" || characterStatus === "stale" ? "重新生成角色图" : characterStatus === "completed" ? "角色图已完成" : characterStatus === "running" ? "角色图生成中" : "生成角色图";
  const steps = [
    ["01", "小说正文", rootTask.status, "先确认故事文本"],
    ["02", "结构信息", analysisStatus, "解析角色和分段"],
    ["03", "角色图", characterStatus, "生成角色定妆"],
    ["04", "场景图", sceneStatus, plannedSegments.length ? `${readySceneCount}/${plannedSegments.length} 段已就绪` : "在时间线中逐段生成"],
    ["05", "视频", videoStatus, plannedSegments.length ? `${readyVideoCount}/${plannedSegments.length} 段已出片` : "在时间线中逐段生成"],
  ];

  return `
    <div class="pipeline-rail">
      ${steps
        .map(
          ([number, title, status, note]) => `
            <article class="pipeline-step ${escapeAttr(status)}">
              <span>${escapeHtml(number)}</span>
              <strong>${escapeHtml(title)}</strong>
              <small>${escapeHtml(stageStatusLabel(status))} · ${escapeHtml(note)}</small>
            </article>
          `,
        )
        .join("")}
    </div>
    <div class="stage-action-card">
      <div>
        <p class="section-kicker">Next Step</p>
        <strong>当前版本制作入口</strong>
        <p>这里只保留全局阶段入口。场景图和视频请在下方时间线里按片段逐段生成，总片合并也改成手动触发。</p>
      </div>
      <div class="action-row">
      <button
        type="button"
        class="secondary"
        data-story-source-project="${escapeAttr(rootTask.project_id)}"
        data-generate-story-analysis="${escapeAttr(rootTask.task_id)}"
        ${canGenerateAnalysis ? "" : "disabled"}
      >
        ${escapeHtml(analysisButtonLabel)}
      </button>
      <button
        type="button"
        class="secondary"
        data-merge-videos="${escapeAttr(rootTask.task_id)}"
        data-project-id="${escapeAttr(rootTask.project_id)}"
        ${canMergeVideos ? "" : "disabled"}
      >
        ${escapeHtml(buildMergeButtonLabel(run.latestArtifacts, mergeStatus))}
      </button>
      <button
        type="button"
        class="secondary"
        data-generate-characters="${escapeAttr(rootTask.task_id)}"
        ${canGenerateCharacters ? "" : "disabled"}
      >
        ${escapeHtml(characterButtonLabel)}
      </button>
      </div>
    </div>
    ${renderStageFailureList(run, storySourceRevision)}
  `;
}

export function renderRunTabContent(task, artifacts, context, activeTab, run = null) {
  if (activeTab === "story") {
    return renderStoryTab(task, context, run);
  }
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
