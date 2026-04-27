import {
  chip,
  escapeHtml,
  singleAssetMessage,
} from "../utils.js";
import { renderRequestInspectorPanel } from "./prompt_tools.js";

const DEBUG_DOCUMENT_NAMES = new Set([
  "character_image_manifest.json",
  "scene_image_manifest.json",
  "seedance_manifest.json",
  "seedream_character_execution.json",
  "seedream_scene_execution.json",
  "seedance_execution.json",
  "continuity_report.json",
]);

export function resolveDebugDocuments(documents = []) {
  return (documents || []).filter((item) => DEBUG_DOCUMENT_NAMES.has(item.name));
}

export function renderRequestDebugTab({ task, artifacts, run = null, helpers }) {
  if (!artifacts?.available) {
    return singleAssetMessage("请求与调试", helpers.buildArtifactPendingMessage(task, "docs", run));
  }
  const segments = helpers.buildTimelineSegments(artifacts);
  const debugDocuments = resolveDebugDocuments(artifacts.documents);
  return `
    <section class="request-debug-shell">
      ${helpers.renderAssetSectionIntro(
        "请求与调试",
        "这里集中查看真实提交参数、参考图绑定顺序、计划 prompt、实际提交 prompt 和执行报告。",
        [chip(`Segment ${segments.length}`), chip(`媒体链路文件 ${debugDocuments.length}`)].join(""),
      )}
      <div class="request-debug-grid">
        ${segments.map((segment) => `
          <details class="prompt-panel request-debug-item">
            <summary>${escapeHtml(segment.segmentId)} · ${escapeHtml(segment.title || "未命名片段")}</summary>
            <div class="prompt-panel-body">
              ${renderRequestInspectorPanel(segment)}
            </div>
          </details>
        `).join("")}
      </div>
      ${debugDocuments.length ? helpers.renderDocumentBlock("媒体链路文件", debugDocuments, "按媒体任务清单、修复与风险、执行报告分类查看。") : ""}
    </section>
  `;
}
