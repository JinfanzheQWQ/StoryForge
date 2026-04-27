import { findGalleryIndex, registerGallery } from "../gallery.js";
import {
  escapeAttr,
  escapeHtml,
  kindLabel,
  singleAssetMessage,
} from "../utils.js";

const DOCUMENT_META = {
  "story_source.json": {
    title: "故事正文源文件",
    category: "核心运行文件",
    summary: "当前版本的事实文本源。保存正文后，场景结构、分段合同和媒体阶段都从这里继续。",
  },
  "novel_package.json": {
    title: "结构规划总包",
    category: "核心运行文件",
    summary: "结构化小说包，包含角色、章节和正文摘录，是视频规划和媒体阶段的正式输入。",
  },
  "novel_audit.json": {
    title: "结构规划审计包",
    category: "调试与审阅",
    summary: "保存 review、workflow_trace，以及从运行包中剥离的分析上下文，主要用于排错和人工审阅。",
  },
  "character_visual_bible.json": {
    title: "角色视觉设定",
    category: "核心运行文件",
    summary: "定义角色外观、服装、配色和定妆提示词，用来锁定视觉一致性。",
  },
  "character_image_manifest.json": {
    title: "角色图任务清单",
    category: "媒体任务清单",
    summary: "记录每个角色图要怎么生成、输出到哪里，以及当前状态。",
  },
  "scene_plan.json": {
    title: "场景规划主文件",
    category: "核心运行文件",
    summary: "定义章节下的 scene 层，以及每个 scene 内部的多个视频片段，并记录 scene_master_frame 的 prompt、路径和状态。",
  },
  "scene_structure_source.json": {
    title: "场景结构恢复快照",
    category: "恢复与进度",
    summary: "保存分段合同开始前的原始 scene skeleton，仅供失败恢复时从当前位置继续，不参与图片和视频执行。",
  },
  "segment_plan.json": {
    title: "片段执行索引",
    category: "核心运行文件",
    summary: "保留给图片与视频执行阶段使用的 flat segment 索引，便于逐段生成和重试。",
  },
  "segment_contract_progress.json": {
    title: "分段合同进度",
    category: "恢复与进度",
    summary: "按 scene 记录分段合同执行进度、失败位置和断点恢复状态，用于失败后继续生成。",
  },
  "scene_image_manifest.json": {
    title: "场景帧任务清单",
    category: "媒体任务清单",
    summary: "记录每个场景母图，以及每个片段的首帧、中段锚点帧、尾帧、角色参考图和输出位置。",
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
    category: "媒体任务清单",
    summary: "最终送给 Seedance 的 clip 列表，决定视频片段会如何被生成。",
  },
  "seedance_execution.json": {
    title: "视频执行报告",
    category: "执行报告",
    summary: "记录视频提交状态、完成数量、失败数量和下载结果。",
  },
  "continuity_report.json": {
    title: "连续性校验报告",
    category: "修复与风险",
    summary: "连续性审校结果，汇总场景母图、关键帧承接、对白预算和视频执行风险，并驱动修复入口。",
  },
};

const DOCUMENT_GROUP_ORDER = [
  "核心运行文件",
  "媒体任务清单",
  "恢复与进度",
  "修复与风险",
  "执行报告",
  "调试与审阅",
  "其他文件",
];

function resolveDocumentMeta(item) {
  const baseMeta = DOCUMENT_META[item.name];
  if (baseMeta) {
    return baseMeta;
  }
  if (/^continuity_repair_.+\.json$/.test(item.name || "")) {
    return {
      title: "连续性修复报告",
      category: "修复与风险",
      summary: "记录某次 scene 或 segment 智能修复的目标、修复摘要、改写字段和后续建议动作。",
    };
  }
  return {
    title: item.name,
    category: "其他文件",
    summary: "本次运行留下的附加文件，可按需打开查看原始内容。",
  };
}

function groupDocuments(items) {
  const groups = new Map();
  items.forEach((item) => {
    const group = resolveDocumentMeta(item).category;
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
  const meta = resolveDocumentMeta(item);
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

export function renderDocumentBlock(title, items, summary = "") {
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

export function renderDocumentGroups(items) {
  return groupDocuments(items).map((group) => renderDocumentBlock(group.title, group.items)).join("");
}

export function renderFullStoryBlock(item, context, galleryId = null) {
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
