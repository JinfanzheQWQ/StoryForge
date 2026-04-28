import { state } from "../state.js";
import { chip, escapeAttr, escapeHtml } from "../utils.js";

export function normalizeSubmittedRequest(request) {
  if (!request || typeof request !== "object") {
    return null;
  }
  return {
    provider: request.provider || "",
    endpoint: request.endpoint || "",
    variant: request.variant || "",
    payload: request.payload && typeof request.payload === "object" ? request.payload : {},
    referenceBindings: Array.isArray(request.reference_bindings) ? request.reference_bindings : [],
  };
}

function renderCopyButton(label = "复制") {
  return `
    <button
      type="button"
      class="copy-code-button"
      data-copy-nearest-code
    >${escapeHtml(label)}</button>
  `;
}

function getSegmentDiagnostics(segment) {
  return segment?.diagnostics && typeof segment.diagnostics === "object" ? segment.diagnostics : {};
}

function hasSegmentDiagnostics(segment) {
  return Object.keys(getSegmentDiagnostics(segment)).length > 0;
}

function formatDiagnosticsSeconds(value, fallback = "-") {
  return value != null && value !== "" ? `${value}s` : fallback;
}

function diagnosticsRiskTypes(diagnostics) {
  return Array.isArray(diagnostics.risk_types)
    ? diagnostics.risk_types
    : Array.isArray(diagnostics.risk_type)
      ? diagnostics.risk_type
      : diagnostics.risk_type
        ? [diagnostics.risk_type]
        : [];
}

function diagnosticsRows(segment) {
  const diagnostics = getSegmentDiagnostics(segment);
  const duration = diagnostics.duration_seconds ?? segment?.durationSeconds;
  const autoExpandedFrom = diagnostics.duration_auto_expanded_from;
  const durationLabel = autoExpandedFrom != null && duration != null
    ? `${autoExpandedFrom}s -> ${duration}s`
    : formatDiagnosticsSeconds(duration);
  return [
    ["动作点", `${diagnostics.action_node_count ?? "-"} / ${diagnostics.action_node_budget ?? "-"}`],
    ["时长", durationLabel],
    ["节拍", `${diagnostics.timed_beat_count ?? 0} 拍`],
    ["节拍覆盖", formatDiagnosticsSeconds(diagnostics.timed_beat_end_seconds, "未解析")],
    ["尾部留空", formatDiagnosticsSeconds(diagnostics.missing_tail_seconds)],
    ["子段", `${diagnostics.subsegment_index || 1}/${diagnostics.subsegment_count || 1}`],
    ["来源", diagnostics.repair_source || diagnostics.planner_warning_source || "planner"],
  ];
}

export function renderSegmentDiagnosticsSummary(segment) {
  if (!hasSegmentDiagnostics(segment)) {
    return "";
  }
  const diagnostics = getSegmentDiagnostics(segment);
  const riskTypes = diagnosticsRiskTypes(diagnostics);
  return `
    <section class="segment-diagnostics-summary">
      <div class="prompt-section-head">
        <strong>规划诊断摘要</strong>
        <span class="matrix-state ${diagnostics.status === "warning" ? "missing" : "ok"}">${diagnostics.status === "warning" ? "需留意" : "稳定"}</span>
      </div>
      ${riskTypes.length ? `<div class="detail-chip-row">${riskTypes.map((item) => chip(item)).join("")}</div>` : ""}
      <div class="segment-diagnostics-grid compact">
        ${diagnosticsRows(segment).map(([label, value]) => `
          <article>
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(String(value))}</strong>
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

function renderSegmentDiagnosticsJson(segment) {
  if (!hasSegmentDiagnostics(segment)) {
    return "";
  }
  return `
    <section class="prompt-section">
      <div class="prompt-section-head">
        <strong>完整诊断 JSON</strong>
        <span>${renderCopyButton()}</span>
      </div>
      <pre class="prompt-code">${escapeHtml(JSON.stringify(getSegmentDiagnostics(segment), null, 2))}</pre>
    </section>
  `;
}

export function renderPromptSection(title, promptText, note = "") {
  const normalized = String(promptText || "").trim();
  if (!normalized) {
    return "";
  }
  return `
    <section class="prompt-section">
      <div class="prompt-section-head">
        <strong>${escapeHtml(title)}</strong>
        <span class="prompt-section-tools">
          ${note ? `<span>${escapeHtml(note)}</span>` : ""}
          ${renderCopyButton()}
        </span>
      </div>
      <pre class="prompt-code">${escapeHtml(normalized)}</pre>
    </section>
  `;
}

function renderEditablePromptSection(title, promptText, field, segmentId, note = "") {
  const normalized = String(promptText || "").trim();
  if (!normalized) {
    return "";
  }
  return `
    <section class="prompt-section prompt-section-editable">
      <label class="prompt-section-head">
        <strong>${escapeHtml(title)}</strong>
        ${note ? `<span>${escapeHtml(note)}</span>` : ""}
      </label>
      <textarea
        class="prompt-editor"
        data-edit-segment-prompt-field="${escapeAttr(field)}"
        data-segment-id="${escapeAttr(segmentId)}"
        rows="8"
      >${escapeHtml(normalized)}</textarea>
    </section>
  `;
}

function renderSubmittedReferenceBindings(bindings, title = "参考图绑定", note = "当前实际提交顺序") {
  if (!bindings?.length) {
    return "";
  }
  return `
    <section class="prompt-section">
      <div class="prompt-section-head">
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(note)}</span>
      </div>
      <div class="prompt-binding-list">
        ${bindings.map((item) => `
          <article class="prompt-binding-item">
            <div>
              <strong>${escapeHtml(item.label || "图")}</strong>
              <span>${escapeHtml(item.kind || "reference")}</span>
            </div>
            <p>${escapeHtml(item.description || "")}</p>
            ${item.url ? `<a class="doc-link" href="${escapeAttr(item.url)}" target="_blank" rel="noreferrer">打开参考图</a>` : ""}
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

function renderMotionPlanSection(motionPlan) {
  if (!motionPlan || typeof motionPlan !== "object") {
    return "";
  }
  const rows = [
    ["场景内运动", motionPlan.scene_motion || motionPlan.sceneMotion || ""],
    ["节拍推进", motionPlan.beat_progression || motionPlan.beatProgression || ""],
    ["镜头路径", motionPlan.camera_path || motionPlan.cameraPath || ""],
    ["角色运动", motionPlan.character_motion || motionPlan.characterMotion || ""],
    ["连续性防跳", motionPlan.continuity_guard || motionPlan.continuityGuard || ""],
  ].filter(([, value]) => String(value || "").trim());
  if (!rows.length) {
    return "";
  }
  return `
    <section class="prompt-section">
      <div class="prompt-section-head">
        <strong>画面推进合同 motion_plan</strong>
        <span>分段合同 / 后处理补齐</span>
      </div>
      <div class="prompt-binding-list prompt-motion-list">
        ${rows.map(([label, value]) => `
          <article class="prompt-binding-item">
            <div>
              <strong>${escapeHtml(label)}</strong>
            </div>
            <p>${escapeHtml(value)}</p>
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

function renderVideoFrameContinuitySection(segment) {
  const requestPayload = segment?.videoRequest?.payload && typeof segment.videoRequest.payload === "object"
    ? segment.videoRequest.payload
    : {};
  const requestFirstFrame = String(requestPayload.first_frame || "").trim();
  const returnLastFrame = requestPayload.return_last_frame === true;
  const rows = [
    ["上一段", segment.previousClipSegmentId || "无"],
    ["首帧来源", segment.firstFrameUrl || requestFirstFrame || "未使用上一段尾帧"],
    ["上一段视频", segment.previousClipVideoUrl || "未记录"],
    ["本段尾帧", segment.lastFrameUrl || "等待 Seedance 返回"],
    ["请求返回尾帧", returnLastFrame ? "已开启" : "未开启或未提交"],
  ];
  const hasSignal = rows.some(([, value]) => value && !["无", "未记录", "等待 Seedance 返回", "未开启或未提交", "未使用上一段尾帧"].includes(value));
  if (!hasSignal && !returnLastFrame) {
    return "";
  }
  return `
    <section class="segment-diagnostics-panel">
      <div class="prompt-editor-panel-head">
        <div>
          <p class="section-kicker">Frame Continuity</p>
          <h5>视频帧连续性</h5>
          <p class="asset-note">用于判断当前 segment 是否从上一段真实尾帧继续，以及本段是否请求 Seedance 返回尾帧。</p>
        </div>
        <span class="matrix-state ${segment.firstFrameUrl || requestFirstFrame ? "ok" : "missing"}">${escapeHtml(segment.firstFrameUrl || requestFirstFrame ? "尾帧承接" : "独立开场")}</span>
      </div>
      <div class="segment-diagnostics-grid">
        ${rows.map(([label, value]) => `
          <article>
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(String(value || "-"))}</strong>
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

function renderMotionContractSection(motionContract) {
  if (!motionContract || typeof motionContract !== "object") {
    return "";
  }
  const rows = [
    ["开场状态", motionContract.entry_state || motionContract.entryState || ""],
    ["运动轨迹", motionContract.motion_trajectory || motionContract.motionTrajectory || ""],
    ["收束状态", motionContract.exit_state || motionContract.exitState || ""],
    ["镜头调度", motionContract.camera_plan || motionContract.cameraPlan || ""],
    ["景别", motionContract.framing || ""],
    ["角色调度", motionContract.staging || ""],
    ["空间规则", motionContract.spatial_rules || motionContract.spatialRules || ""],
  ].filter(([, value]) => String(value || "").trim());
  if (!rows.length) {
    return "";
  }
  return `
    <section class="prompt-section">
      <div class="prompt-section-head">
        <strong>运动轨迹合同 motion_contract</strong>
        <span>场景母图 + 角色图驱动</span>
      </div>
      <div class="prompt-binding-list prompt-motion-list">
        ${rows.map(([label, value]) => `
          <article class="prompt-binding-item">
            <div><strong>${escapeHtml(label)}</strong></div>
            <p>${escapeHtml(value)}</p>
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

export function renderSubmittedRequest(title, request, emptyNote = "提交后可见") {
  const payload = request?.payload && typeof request.payload === "object"
    ? request.payload
    : null;
  const bindings = Array.isArray(request?.referenceBindings) ? request.referenceBindings : [];
  const hasPayload = Boolean(payload && Object.keys(payload).length);
  const hasRequest = Boolean(
    hasPayload
    || bindings.length
    || String(request?.provider || "").trim()
    || String(request?.variant || "").trim()
    || String(request?.endpoint || "").trim()
  );
  if (!hasRequest) {
    return "";
  }
  const meta = [
    String(request?.provider || "").trim(),
    request?.variant ? `策略：${String(request.variant).trim()}` : "",
    String(request?.endpoint || "").trim(),
  ].filter(Boolean).join(" · ") || emptyNote;
  return `
    <section class="prompt-section">
      <div class="prompt-section-head">
        <strong>${escapeHtml(title)}</strong>
        <span class="prompt-section-tools">
          <span>${escapeHtml(meta)}</span>
          ${hasPayload ? renderCopyButton("复制 JSON") : ""}
        </span>
      </div>
      ${renderSubmittedReferenceBindings(bindings, "本次实际使用图片", "按真实请求顺序展示")}
      ${hasPayload ? `<pre class="prompt-code">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>` : ""}
    </section>
  `;
}

export function renderScenePromptPanel(sceneGroup, rootTask) {
  const firstSegment = sceneGroup.segments?.[0] || null;
  const editablePrompt = firstSegment
    ? renderEditablePromptSection(
      "场景母图 Prompt",
      sceneGroup.sceneMasterFramePrompt,
      "scene_master_frame_prompt",
      firstSegment.segmentId,
      "保存后手动重跑场景母图生效",
    )
    : renderPromptSection("场景母图 Prompt", sceneGroup.sceneMasterFramePrompt);
  const sections = [
    editablePrompt,
    renderSubmittedRequest("场景母图实际提交参数", sceneGroup.sceneMasterFrameRequest, "场景母图提交后可见"),
  ].filter(Boolean);
  if (!sections.length) {
    return "";
  }
  const projectId = rootTask?.project_id || state.selectedProjectId || "";
  const sourceTaskId = rootTask?.task_id || "";
  return `
    <details class="prompt-panel" data-segment-prompt-panel="${escapeAttr(firstSegment?.segmentId || sceneGroup.sceneId)}">
      <summary>查看 / 修改场景母图 Prompt / 请求参数</summary>
      <div class="prompt-panel-body">
        ${sections.join("")}
        ${firstSegment ? `
          <div class="prompt-edit-actions">
            <button
              type="button"
              class="primary-button"
              data-save-segment-prompts="${escapeAttr(firstSegment.segmentId)}"
              data-project-id="${escapeAttr(projectId)}"
              data-source-task="${escapeAttr(sourceTaskId)}"
            >保存场景母图 Prompt</button>
            <button
              type="button"
              class="primary-button"
              data-save-and-rerun-segment-prompt="${escapeAttr(firstSegment.segmentId)}"
              data-project-id="${escapeAttr(projectId)}"
              data-source-task="${escapeAttr(sourceTaskId)}"
              data-scene-id="${escapeAttr(sceneGroup.sceneId)}"
              data-asset-kind="scene_master"
            >保存并重做场景母图</button>
            <span class="asset-note">同步到同一 scene 的场景图任务，不会自动开始生成。</span>
          </div>
        ` : ""}
      </div>
    </details>
  `;
}

export function getSegmentAssetOptions(segment) {
  return [
    {
      kind: "video",
      label: "视频",
      promptTitle: "视频 Prompt",
      promptField: "video_prompt",
      promptText: segment.videoPrompt,
      requestTitle: "视频实际提交参数",
      request: segment.videoRequest,
      ready: Boolean(segment.videoReady),
    },
  ];
}

export function resolveSelectedSegmentAssetOption(segment) {
  const options = getSegmentAssetOptions(segment);
  return options.find((option) => option.kind === state.selectedSegmentAssetKind) || options[0];
}

export function renderSegmentAssetSelector(segment, selectedOption) {
  return `
    <div class="segment-asset-selector" role="tablist" aria-label="选择当前生成点">
      ${getSegmentAssetOptions(segment).map((option) => `
        <button
          type="button"
          class="segment-asset-tab${option.kind === selectedOption.kind ? " is-active" : ""}"
          data-select-segment-asset-kind="${escapeAttr(option.kind)}"
          aria-selected="${option.kind === selectedOption.kind ? "true" : "false"}"
        >
          <span>${escapeHtml(option.label)}</span>
          <small>${escapeHtml(option.ready ? "已生成" : "待生成")}</small>
        </button>
      `).join("")}
    </div>
  `;
}

function buildSegmentEditablePromptSections(segment, option = resolveSelectedSegmentAssetOption(segment)) {
  return [
    renderEditablePromptSection(
      option.promptTitle,
      option.promptText,
      option.promptField,
      segment.segmentId,
      option.kind === "video" ? "保存后该段旧视频会失效，需要手动重跑视频" : "保存后手动重做当前图片生效",
    ),
  ].filter(Boolean);
}

function buildSegmentRequestInspectorSections(segment, option = resolveSelectedSegmentAssetOption(segment)) {
  if (option.kind === "video") {
    return [
      renderMotionContractSection(segment.motionContract),
      renderMotionPlanSection(segment.motionPlan),
      renderVideoFrameContinuitySection(segment),
      renderPromptSection("Seedance 画面推进摘录", segment.seedanceMotionPrompt, "最终提交 prompt 中的参考图绑定与画面推进"),
      renderPromptSection(
        "视频实际提交 Prompt",
        segment.submittedVideoPrompt,
        segment.submittedPromptVariant
          ? `提交策略：${segment.submittedPromptVariant}`
          : "视频提交后可见",
      ),
      renderSubmittedRequest(option.requestTitle, option.request, "视频提交后可见"),
      option.request ? "" : renderSubmittedReferenceBindings(segment.submittedReferenceBindings),
    ].filter(Boolean);
  }
  return [renderSubmittedRequest(option.requestTitle, option.request, `${option.label}提交后可见`)].filter(Boolean);
}

export function renderPromptEditorPanel(segment, rootTask, option = resolveSelectedSegmentAssetOption(segment), { locked = false } = {}) {
  const sections = buildSegmentEditablePromptSections(segment, option);
  if (!sections.length) {
    return "";
  }
  const projectId = rootTask?.project_id || state.selectedProjectId || "";
  const sourceTaskId = rootTask?.task_id || "";
  const isVideo = option.kind === "video";
  const rerunLabel = isVideo
    ? (segment.videoReady ? "保存并重做视频" : "保存并生成视频")
    : `保存并重做${option.label}`;
  return `
    <section class="prompt-editor-panel" data-segment-prompt-panel="${escapeAttr(segment.segmentId)}">
      <div class="prompt-editor-panel-head">
        <div>
          <p class="section-kicker">Prompt Editor</p>
          <h5>${escapeHtml(option.label)}计划 Prompt</h5>
          <p class="asset-note">这里只修改当前选择的生成点。保存后不会自动开始生图或生视频。</p>
        </div>
        <div class="prompt-editor-actions">
          <button
            type="button"
            class="secondary small"
            data-reset-segment-prompt="${escapeAttr(segment.segmentId)}"
            data-prompt-field="${escapeAttr(option.promptField)}"
            data-project-id="${escapeAttr(projectId)}"
            data-source-task="${escapeAttr(sourceTaskId)}"
            ${locked ? "disabled" : ""}
          >重置当前点 Prompt</button>
          <button
            type="button"
            class="secondary small"
            data-save-segment-prompts="${escapeAttr(segment.segmentId)}"
            data-project-id="${escapeAttr(projectId)}"
            data-source-task="${escapeAttr(sourceTaskId)}"
            ${locked ? "disabled" : ""}
          >保存${escapeHtml(option.label)} Prompt</button>
          <button
            type="button"
            class="primary-button small"
            data-save-and-rerun-segment-prompt="${escapeAttr(segment.segmentId)}"
            data-project-id="${escapeAttr(projectId)}"
            data-source-task="${escapeAttr(sourceTaskId)}"
            data-asset-kind="${escapeAttr(option.kind)}"
            ${isVideo ? "" : `data-scene-id="${escapeAttr(segment.sceneId)}"`}
            ${locked ? "disabled" : ""}
          >${escapeHtml(rerunLabel)}</button>
        </div>
      </div>
      <div class="prompt-panel-body">
        ${sections.join("")}
      </div>
    </section>
  `;
}


function renderSegmentDiagnosticsPanel(segment) {
  const diagnostics = getSegmentDiagnostics(segment);
  if (!Object.keys(diagnostics).length) {
    return "";
  }
  const riskTypes = diagnosticsRiskTypes(diagnostics);
  const rows = diagnosticsRows(segment);
  return `
    <section class="segment-diagnostics-panel">
      <div class="prompt-editor-panel-head">
        <div>
          <p class="section-kicker">Planning Diagnostics</p>
          <h5>规划诊断</h5>
          <p class="asset-note">根据当前 segment_plan 和 continuity_report 生成，用来解释动作预算、时长、节拍覆盖和修复来源。</p>
        </div>
        <span class="matrix-state ${diagnostics.status === "warning" ? "missing" : "ok"}">${diagnostics.status === "warning" ? "需留意" : "稳定"}</span>
      </div>
      ${riskTypes.length ? `<div class="detail-chip-row">${riskTypes.map((item) => chip(item)).join("")}</div>` : ""}
      <div class="segment-diagnostics-grid">
        ${rows.map(([label, value]) => `
          <article>
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(String(value))}</strong>
          </article>
        `).join("")}
      </div>
      ${renderSegmentDiagnosticsJson(segment)}
    </section>
  `;
}

export function renderRequestInspectorPanel(segment, option = resolveSelectedSegmentAssetOption(segment)) {
  const sections = buildSegmentRequestInspectorSections(segment, option);
  return `
    <section class="request-inspector-panel">
      <div class="prompt-editor-panel-head">
        <div>
          <p class="section-kicker">Request Inspector</p>
          <h5>${escapeHtml(option.label)}实际请求</h5>
          <p class="asset-note">这里只显示当前选择生成点的 payload、参考图顺序和实际提交记录。</p>
        </div>
      </div>
      <div class="prompt-panel-body">
        ${renderSegmentDiagnosticsPanel(segment)}
        ${sections.length ? sections.join("") : `<p class="asset-note">该片段还没有实际提交请求。</p>`}
      </div>
    </section>
  `;
}

export function renderSegmentPromptPanel(segment, rootTask) {
  const option = resolveSelectedSegmentAssetOption(segment);
  const sections = [
    renderPromptEditorPanel(segment, rootTask, option),
    renderRequestInspectorPanel(segment, option),
  ].filter(Boolean);
  if (!sections.length) {
    return "";
  }
  return `
    <details class="prompt-panel">
      <summary>查看 / 修改本段 Prompt 与请求参数</summary>
      <div class="prompt-panel-body">
        ${sections.join("")}
      </div>
    </details>
  `;
}
