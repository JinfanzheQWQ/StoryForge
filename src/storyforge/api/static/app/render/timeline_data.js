import { findGalleryIndex } from "../gallery.js";
import { escapeAttr, escapeHtml } from "../utils.js";
import { normalizeSubmittedRequest } from "./prompt_tools.js";

function segmentIdFromAssetName(name) {
  return String(name || "")
    .replace(/\.[^.]+$/, "")
    .replace(/_(start|mid|end)$/, "");
}

export function segmentLabel(segmentId, index) {
  const text = String(segmentId || "").trim();
  if (!text) {
    return `片段 ${index + 1}`;
  }
  return text
    .replace(/^ch(\d+)-sc(\d+)-seg(\d+)$/i, "第 $1 章 / 场景 $2 / 片段 $3")
    .replace(/^ch(\d+)-sc(\d+)-seg(\d+)_(\d+)$/i, "第 $1 章 / 场景 $2 / 片段 $3-$4")
    .replace(/^ch(\d+)_seg(\d+)$/i, "第 $1 章 / 片段 $2")
    .replaceAll("_", " ");
}

export function buildTimelineSegments(artifacts) {
  if (artifacts?.planned_segments?.length) {
    const segments = artifacts.planned_segments.map((segment, index) => ({
      segmentId: segment.segment_id,
      sceneId: segment.scene_id || "",
      sceneTitle: segment.scene_title || "",
      sceneSummary: segment.scene_summary || "",
      sceneAnchor: segment.scene_anchor || "",
      sceneBible: segment.scene_bible && typeof segment.scene_bible === "object" ? segment.scene_bible : {},
      sceneTransitionContract: segment.scene_transition_contract && typeof segment.scene_transition_contract === "object"
        ? segment.scene_transition_contract
        : {},
      sceneSpatialContinuityMode: segment.scene_spatial_continuity_mode || "uncertain",
      sceneMasterFrameStatus: segment.scene_master_frame_status || "",
      sceneMasterFrameError: segment.scene_master_frame_error || "",
      coveredEventIds: Array.isArray(segment.covered_event_ids) ? segment.covered_event_ids : [],
      coveredEventSummaries: Array.isArray(segment.covered_event_summaries) ? segment.covered_event_summaries : [],
      title: segment.title || segmentLabel(segment.segment_id, index),
      summary: segment.summary || "",
      chapterNumber: segment.chapter_number,
      durationSeconds: segment.duration_seconds || 0,
      sceneMasterFrame: segment.scene_master_frame ? { ...segment.scene_master_frame, kind: "image" } : null,
      clip: segment.rendered_clip ? { ...segment.rendered_clip, kind: "video" } : null,
      sceneMasterFramePrompt: segment.scene_master_frame_prompt || "",
      videoPrompt: segment.video_prompt || "",
      submittedVideoPrompt: segment.submitted_video_prompt || "",
      seedanceMotionPrompt: segment.seedance_motion_prompt || "",
      motionPlan: segment.motion_plan && typeof segment.motion_plan === "object" ? segment.motion_plan : {},
      motionContract: segment.motion_contract && typeof segment.motion_contract === "object" ? segment.motion_contract : {},
      firstFrameUrl: segment.first_frame_url || "",
      lastFrameUrl: segment.last_frame_url || "",
      previousClipSegmentId: segment.previous_clip_segment_id || "",
      previousClipVideoUrl: segment.previous_clip_video_url || "",
      characterReferences: Array.isArray(segment.character_references)
        ? segment.character_references.map((item) => ({ ...item, kind: "image" }))
        : [],
      sceneMasterReferenceImages: Array.isArray(segment.scene_master_reference_images)
        ? segment.scene_master_reference_images
        : [],
      diagnostics: segment.diagnostics && typeof segment.diagnostics === "object" ? segment.diagnostics : {},
      submittedPromptVariant: segment.submitted_prompt_variant || "",
      sceneMasterFrameRequest: normalizeSubmittedRequest(segment.scene_master_frame_request),
      videoRequest: normalizeSubmittedRequest(segment.video_request),
      submittedReferenceBindings: Array.isArray(segment.submitted_reference_bindings)
        ? segment.submitted_reference_bindings
        : [],
      sceneReady: Boolean(segment.scene_ready),
      videoReady: Boolean(segment.video_ready),
    }));
    return hydrateSharedSceneMasterFrames(segments);
  }

  const segmentMap = new Map();
  const ensureSegment = (segmentId) => {
    if (!segmentMap.has(segmentId)) {
      segmentMap.set(segmentId, {
        segmentId,
        sceneId: "",
        sceneTitle: "",
        sceneSummary: "",
        sceneAnchor: "",
        sceneBible: {},
        sceneTransitionContract: {},
        sceneSpatialContinuityMode: "uncertain",
        sceneMasterFrameStatus: "",
        sceneMasterFrameError: "",
        coveredEventIds: [],
        coveredEventSummaries: [],
        title: segmentId,
        summary: "",
        chapterNumber: 0,
        sceneMasterFrame: null,
        durationSeconds: 0,
        clip: null,
        seedanceMotionPrompt: "",
        motionPlan: {},
        diagnostics: {},
        sceneReady: false,
        videoReady: false,
      });
    }
    return segmentMap.get(segmentId);
  };

  for (const clip of artifacts?.rendered_clips || []) {
    const segment = ensureSegment(segmentIdFromAssetName(clip.name));
    segment.clip = clip;
  }

  return Array.from(segmentMap.values())
    .sort((left, right) => left.segmentId.localeCompare(right.segmentId))
    .map((segment, index) => ({
      ...segment,
      title: segment.title || segmentLabel(segment.segmentId, index),
      sceneReady: Boolean(segment.sceneMasterFrame),
      videoReady: Boolean(segment.clip),
    }));
}

function hydrateSharedSceneMasterFrames(segments) {
  const sceneMasterByScene = new Map();
  for (const segment of segments) {
    const sceneId = String(segment.sceneId || "").trim();
    if (!sceneId || !segment.sceneMasterFrame) {
      continue;
    }
    if (!sceneMasterByScene.has(sceneId)) {
      sceneMasterByScene.set(sceneId, segment.sceneMasterFrame);
    }
  }
  return segments.map((segment) => {
    const sceneMasterFrame = segment.sceneMasterFrame || sceneMasterByScene.get(String(segment.sceneId || "").trim()) || null;
    return {
      ...segment,
      sceneMasterFrame,
      sceneReady: Boolean(segment.sceneReady || sceneMasterFrame),
    };
  });
}

export function buildSceneGroups(segments) {
  const sceneMap = new Map();
  segments.forEach((segment, index) => {
    const sceneId = String(segment.sceneId || "").trim() || `scene-${String(index + 1).padStart(2, "0")}`;
    if (!sceneMap.has(sceneId)) {
      sceneMap.set(sceneId, {
        sceneId,
        sceneTitle: segment.sceneTitle || `场景 ${sceneMap.size + 1}`,
        sceneSummary: segment.sceneSummary || "",
        sceneAnchor: segment.sceneAnchor || "",
        sceneBible: segment.sceneBible || {},
        sceneTransitionContract: segment.sceneTransitionContract || {},
        sceneMasterFrameStatus: segment.sceneMasterFrameStatus || "",
        sceneMasterFrameError: segment.sceneMasterFrameError || "",
        coveredEventIds: segment.coveredEventIds || [],
        coveredEventSummaries: segment.coveredEventSummaries || [],
        chapterNumber: segment.chapterNumber || 0,
        sceneMasterFrame: segment.sceneMasterFrame || null,
        sceneSpatialContinuityMode: segment.sceneSpatialContinuityMode || "uncertain",
        sceneMasterReferenceImages: segment.sceneMasterReferenceImages || [],
        sceneMasterFramePrompt: segment.sceneMasterFramePrompt || "",
        sceneMasterFrameRequest: segment.sceneMasterFrameRequest || null,
        segments: [],
      });
    }
    if (!sceneMap.get(sceneId).sceneMasterFrame && segment.sceneMasterFrame) {
      sceneMap.get(sceneId).sceneMasterFrame = segment.sceneMasterFrame;
    }
    if (!sceneMap.get(sceneId).sceneMasterFramePrompt && segment.sceneMasterFramePrompt) {
      sceneMap.get(sceneId).sceneMasterFramePrompt = segment.sceneMasterFramePrompt;
    }
    if (!sceneMap.get(sceneId).sceneMasterFrameRequest && segment.sceneMasterFrameRequest) {
      sceneMap.get(sceneId).sceneMasterFrameRequest = segment.sceneMasterFrameRequest;
    }
    if (!sceneMap.get(sceneId).sceneAnchor && segment.sceneAnchor) {
      sceneMap.get(sceneId).sceneAnchor = segment.sceneAnchor;
    }
    if (!Object.keys(sceneMap.get(sceneId).sceneBible || {}).length && Object.keys(segment.sceneBible || {}).length) {
      sceneMap.get(sceneId).sceneBible = segment.sceneBible;
    }
    if (!Object.keys(sceneMap.get(sceneId).sceneTransitionContract || {}).length && Object.keys(segment.sceneTransitionContract || {}).length) {
      sceneMap.get(sceneId).sceneTransitionContract = segment.sceneTransitionContract;
    }
    if (!sceneMap.get(sceneId).sceneSpatialContinuityMode && segment.sceneSpatialContinuityMode) {
      sceneMap.get(sceneId).sceneSpatialContinuityMode = segment.sceneSpatialContinuityMode;
    }
    if (!sceneMap.get(sceneId).sceneMasterReferenceImages.length && segment.sceneMasterReferenceImages?.length) {
      sceneMap.get(sceneId).sceneMasterReferenceImages = segment.sceneMasterReferenceImages;
    }
    if (!sceneMap.get(sceneId).sceneMasterFrameStatus && segment.sceneMasterFrameStatus) {
      sceneMap.get(sceneId).sceneMasterFrameStatus = segment.sceneMasterFrameStatus;
    }
    if (!sceneMap.get(sceneId).sceneMasterFrameError && segment.sceneMasterFrameError) {
      sceneMap.get(sceneId).sceneMasterFrameError = segment.sceneMasterFrameError;
    }
    if (!sceneMap.get(sceneId).coveredEventIds.length && segment.coveredEventIds?.length) {
      sceneMap.get(sceneId).coveredEventIds = segment.coveredEventIds;
    }
    if (!sceneMap.get(sceneId).coveredEventSummaries.length && segment.coveredEventSummaries?.length) {
      sceneMap.get(sceneId).coveredEventSummaries = segment.coveredEventSummaries;
    }
    sceneMap.get(sceneId).segments.push(segment);
  });
  return Array.from(sceneMap.values());
}

export function buildTimelineGalleryItems(artifacts) {
  const plannedItems = (artifacts?.planned_segments || []).flatMap((segment) => ([
    segment.scene_master_frame ? { ...segment.scene_master_frame, kind: "image" } : null,
    segment.rendered_clip ? { ...segment.rendered_clip, kind: "video" } : null,
  ])).filter(Boolean);
  if (plannedItems.length) {
    return dedupeTimelineGalleryItems([
      ...(artifacts.full_story ? [{ ...artifacts.full_story, kind: "video" }] : []),
      ...plannedItems,
    ]);
  }
  return dedupeTimelineGalleryItems([
    ...artifacts.scene_frames.map((item) => ({ ...item, kind: "image" })),
    ...(artifacts.full_story ? [{ ...artifacts.full_story, kind: "video" }] : []),
    ...artifacts.rendered_clips.map((item) => ({ ...item, kind: "video" })),
  ]);
}

function dedupeTimelineGalleryItems(items) {
  const seen = new Set();
  return items.filter((item) => {
    const key = String(item?.path || item?.url || item?.name || "");
    if (!key || seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

export function renderTimelinePreview(item, label, galleryId) {
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
