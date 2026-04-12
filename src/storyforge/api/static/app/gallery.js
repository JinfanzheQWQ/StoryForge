import { state } from "./state.js";

export function registerGallery(groupId, items) {
  state.galleries.set(
    groupId,
    items.map((item) => ({
      title: item.name,
      url: item.url,
      kind: item.kind || "image",
    })),
  );
}

export function findGalleryIndex(groupId, item) {
  const gallery = state.galleries.get(groupId) || [];
  return Math.max(0, gallery.findIndex((entry) => entry.url === item.url));
}
