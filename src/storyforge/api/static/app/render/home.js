import { elements } from "../dom.js";
import { registerGallery } from "../gallery.js";
import { state } from "../state.js";
import { escapeAttr, escapeHtml, formatShortTime } from "../utils.js";
import { renderInto } from "./patch.js";

function buildHomeVisualEntry(item, kind, badge, storyTitle, task) {
  return {
    name: item.name || `${storyTitle} ${badge}`,
    storyTitle,
    url: item.url,
    kind,
    badge,
    meta: `${badge} · ${formatShortTime(task.created_at)}`,
  };
}

function renderVisualMedia(item) {
  if (item.kind === "video") {
    return `<video autoplay muted loop playsinline preload="metadata" src="${item.url}"></video>`;
  }
  return `<img src="${item.url}" alt="${escapeAttr(item.name)}" loading="lazy" />`;
}

function renderHeroShowcaseSecondary(item, galleryId, index) {
  return `
    <button
      type="button"
      class="hero-showcase-secondary"
      data-preview-group="${escapeAttr(galleryId)}"
      data-preview-index="${index}"
    >
      <div class="hero-showcase-media compact">
        ${renderVisualMedia(item)}
        <span class="visual-kind">${escapeHtml(item.badge)}</span>
      </div>
      <div class="hero-showcase-caption compact">
        <strong>${escapeHtml(item.storyTitle)}</strong>
        <p>${escapeHtml(item.meta)}</p>
      </div>
    </button>
  `;
}

function collectHomeVisualItems() {
  const items = [];
  const seenUrls = new Set();
  const sortedTasks = [...state.tasks].sort(
    (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at),
  );

  for (const task of sortedTasks) {
    const artifacts = state.artifactsByTaskId.get(task.task_id);
    if (!artifacts?.available) {
      continue;
    }

    const storyTitle =
      artifacts.story_title ||
      task.result?.story_title ||
      task.payload?.brief?.title_hint ||
      "未命名故事";
    const candidates = [
      ...(artifacts.rendered_clips || []).slice(0, 1).map((item) =>
        buildHomeVisualEntry(item, "video", "Video", storyTitle, task),
      ),
      ...(artifacts.scene_frames || []).slice(0, 2).map((item) =>
        buildHomeVisualEntry(item, "image", "Scene", storyTitle, task),
      ),
      ...(artifacts.character_images || []).slice(0, 1).map((item) =>
        buildHomeVisualEntry(item, "image", "Cast", storyTitle, task),
      ),
      ...(artifacts.full_story ? [buildHomeVisualEntry(artifacts.full_story, "video", "Final", storyTitle, task)] : []),
    ];

    for (const candidate of candidates) {
      if (!candidate.url || seenUrls.has(candidate.url)) {
        continue;
      }

      seenUrls.add(candidate.url);
      items.push(candidate);

      if (items.length >= 6) {
        return items;
      }
    }
  }

  return items;
}

function renderHomeHeroShowcase(items = collectHomeVisualItems()) {
  if (!elements.homeHeroShowcase) {
    return;
  }

  const showcaseItems = items.slice(0, 3);
  if (!showcaseItems.length) {
    renderInto(elements.homeHeroShowcase, `
      <article class="hero-showcase-empty">
        <span class="hero-showcase-plate large"></span>
        <span class="hero-showcase-plate"></span>
        <span class="hero-showcase-plate"></span>
      </article>
    `);
    return;
  }

  const galleryId = "home:hero-showcase";
  registerGallery(galleryId, showcaseItems);
  const [primary, ...secondary] = showcaseItems;
  renderInto(elements.homeHeroShowcase, `
    <button
      type="button"
      class="hero-showcase-primary"
      data-preview-group="${escapeAttr(galleryId)}"
      data-preview-index="0"
    >
      <div class="hero-showcase-media">
        ${renderVisualMedia(primary)}
        <span class="visual-kind">${escapeHtml(primary.badge)}</span>
      </div>
      <div class="hero-showcase-caption">
        <strong>${escapeHtml(primary.storyTitle)}</strong>
        <p>${escapeHtml(primary.meta)}</p>
      </div>
    </button>
    <div class="hero-showcase-stack">
      ${secondary.map((item, index) => renderHeroShowcaseSecondary(item, galleryId, index + 1)).join("")}
    </div>
  `);
}

export function renderHomeOverview() {
  renderHomeHeroShowcase(collectHomeVisualItems());
}
