import {
  escapeAttr,
  escapeHtml,
  singleAssetMessage,
} from "../utils.js";
import { registerGallery } from "../gallery.js";
import { normalizeSubmittedRequest, renderSubmittedRequest } from "./prompt_tools.js";

export function renderCharacterWorkbenchTab({ task, artifacts, context, run = null }) {
  const items = (artifacts?.character_images || []).map((item) => ({ ...item, kind: "image" }));
  if (!items.length) {
    return `
      <section class="character-workbench-shell">
        ${singleAssetMessage("角色定妆图", "还没有角色图。生成角色图后，这里会展示每个角色的定妆参考、Prompt 和单角色重做入口。", "生成角色图")}
      </section>
    `;
  }
  const galleryId = `${context}:characters`;
  registerGallery(galleryId, items);
  return `
    <section class="character-workbench-shell">
      <article class="asset-block workbench-command-card">
        <div>
          <p class="section-kicker">Character Bench</p>
          <h4>角色工作台</h4>
          <p class="asset-note">集中检查角色定妆图、编辑单个角色 Prompt，并按角色粒度重做 Seedream 生图。</p>
        </div>
        <div class="detail-metrics">
          <article><strong>${items.length}</strong><span>角色图</span></article>
          <article><strong>${items.filter((item) => item.status === "completed" || item.url).length}</strong><span>已完成</span></article>
        </div>
      </article>
      <div class="character-card-grid">
        ${items.map((item, index) => renderCharacterPromptCard({ task, item, index, galleryId, run })).join("")}
      </div>
    </section>
  `;
}

function renderCharacterPromptCard({ task, item, index, galleryId, run }) {
  const characterName = item.character_name || item.name || `角色 ${index + 1}`;
  const pendingTask = findPendingCharacterTask(run, item.character_name || characterName);
  const isBusy = Boolean(pendingTask);
  const requestHtml = renderSubmittedRequest(
    "角色图实际提交请求",
    normalizeSubmittedRequest(item.character_request),
    "角色图提交后可见",
  );
  return `
    <article class="character-workbench-card ${isBusy ? "is-busy" : ""}" data-character-prompt-panel>
      <header class="character-card-head">
        <div>
          <p class="section-kicker">Character</p>
          <h4>${escapeHtml(characterName)}</h4>
        </div>
        <span class="kind-tag">${escapeHtml(item.status || "planned")}</span>
      </header>
      <div class="character-operation-status" data-character-operation-status ${isBusy ? "" : "hidden"}>${isBusy ? "该角色图正在重做，完成后会出现新候选图。" : ""}</div>
      ${renderCharacterVersionPanel({ task, item, index, galleryId, characterName, isBusy })}
      <section class="character-prompt-editor">
        <div class="prompt-editor-head">
          <strong>角色 Prompt</strong>
          <span class="asset-note">修改后可只重做该角色</span>
        </div>
        <textarea data-edit-character-prompt rows="10">${escapeHtml(item.prompt || "")}</textarea>
        <div class="character-primary-actions">
          <button
            type="button"
            class="secondary"
            ${isBusy ? "disabled" : ""}
            data-save-character-prompt="${escapeAttr(item.character_name || "")}"
            data-project-id="${escapeAttr(task.project_id)}"
            data-source-task="${escapeAttr(task.task_id)}"
          >只保存 Prompt</button>
          <button
            type="button"
            ${isBusy ? "disabled" : ""}
            data-save-and-rerun-character-prompt="${escapeAttr(item.character_name || "")}"
            data-project-id="${escapeAttr(task.project_id)}"
            data-source-task="${escapeAttr(task.task_id)}"
          >保存并重做该角色</button>
        </div>
      </section>
      ${requestHtml ? `
        <details class="character-request-details">
          <summary>查看 Seedream 提交请求</summary>
          ${requestHtml}
        </details>
      ` : `
        <section class="character-request-empty">
          <strong>Seedream 提交请求</strong>
          <p class="asset-note">角色图提交后这里会显示真实 payload。</p>
        </section>
      `}
    </article>
  `;
}

function renderCharacterVersionPanel({ task, item, index, galleryId, characterName, isBusy = false }) {
  const hasCandidate = Boolean(item.candidate_url) && !isBusy;
  return `
    <section class="character-version-panel">
      <div class="character-version-head">
        <strong>角色图版本</strong>
        ${hasCandidate ? `<span class="asset-note">新图已生成但尚未替换当前图，请确认是否使用。</span>` : `<span class="asset-note">当前没有待确认的新图。</span>`}
      </div>
      <div class="character-version-grid ${hasCandidate ? "has-candidate" : ""}">
        <article class="character-version-card is-current">
          <button
            type="button"
            class="character-image-preview"
            data-preview-group="${escapeAttr(galleryId)}"
            data-preview-index="${index}"
          >
            <span>当前图</span>
            ${item.url ? `<img src="${escapeAttr(item.url)}" alt="${escapeAttr(characterName)} 当前角色图" loading="lazy" />` : `<em>暂无图片</em>`}
          </button>
        </article>
        ${hasCandidate ? `
          <article class="character-version-card">
            <div class="character-image-preview static">
              <span>新候选图</span>
              <img src="${escapeAttr(item.candidate_url)}" alt="${escapeAttr(characterName)} 新候选角色图" loading="lazy" />
            </div>
          </article>
        ` : ""}
      </div>
      ${hasCandidate ? `
        <div class="character-version-actions">
          <button
            type="button"
            class="secondary"
            ${isBusy ? "disabled" : ""}
            data-select-character-version="current"
            data-character-name="${escapeAttr(item.character_name || "")}"
            data-project-id="${escapeAttr(task.project_id)}"
            data-source-task="${escapeAttr(task.task_id)}"
          >放弃新图</button>
          <button
            type="button"
            ${isBusy ? "disabled" : ""}
            data-select-character-version="candidate"
            data-character-name="${escapeAttr(item.character_name || "")}"
            data-project-id="${escapeAttr(task.project_id)}"
            data-source-task="${escapeAttr(task.task_id)}"
          >使用新图</button>
        </div>
      ` : ""}
    </section>
  `;
}


function findPendingCharacterTask(run, characterName) {
  const targetName = String(characterName || "").trim();
  if (!targetName || !Array.isArray(run?.tasks)) {
    return null;
  }
  return run.tasks.find((task) => (
    task?.task_type === "project.characters"
    && ["queued", "running"].includes(task.status)
    && String(task.payload?.character_name || "").trim() === targetName
  )) || null;
}
