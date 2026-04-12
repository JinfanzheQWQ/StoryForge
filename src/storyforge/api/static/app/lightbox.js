import { elements } from "./dom.js";
import { state } from "./state.js";

function renderLightbox() {
  const gallery = state.galleries.get(state.lightboxGroupId) || [];
  const item = gallery[state.lightboxIndex];
  if (!item) {
    return;
  }

  elements.lightboxTitle.textContent = item.title;
  elements.lightboxPosition.textContent = `${state.lightboxIndex + 1} / ${gallery.length}`;
  elements.lightboxOpenRaw.href = item.url;
  elements.lightboxContent.innerHTML = "";

  if (item.kind === "video") {
    const video = document.createElement("video");
    video.controls = true;
    video.autoplay = true;
    video.src = item.url;
    elements.lightboxContent.appendChild(video);
  } else {
    const image = document.createElement("img");
    image.src = item.url;
    image.alt = item.title;
    elements.lightboxContent.appendChild(image);
  }

  const multi = gallery.length > 1;
  elements.lightboxPrevButton.disabled = !multi;
  elements.lightboxNextButton.disabled = !multi;
}

export function openLightbox(groupId, index) {
  const gallery = state.galleries.get(groupId) || [];
  if (!gallery.length) {
    return;
  }

  state.lightboxGroupId = groupId;
  state.lightboxIndex = Math.max(0, Math.min(index, gallery.length - 1));
  renderLightbox();
  elements.lightbox.classList.remove("hidden");
  elements.lightbox.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
}

export function stepLightbox(direction) {
  const gallery = state.galleries.get(state.lightboxGroupId) || [];
  if (!gallery.length) {
    return;
  }
  state.lightboxIndex = (state.lightboxIndex + direction + gallery.length) % gallery.length;
  renderLightbox();
}

export function closeLightbox() {
  elements.lightbox.classList.add("hidden");
  elements.lightbox.setAttribute("aria-hidden", "true");
  elements.lightboxContent.innerHTML = "";
  document.body.classList.remove("modal-open");
}
