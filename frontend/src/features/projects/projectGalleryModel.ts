import type { ArtifactBundle, ArtifactItem, ProjectSummary } from "../../types";

export type ProjectCover = {
  kind: "video" | "image";
  name: string;
  url: string;
};

export function getProjectTitle(project: ProjectSummary) {
  return project.story_title || project.title_hint || "未命名项目";
}

export function formatProjectUpdatedAt(value?: string) {
  if (!value) return "等待更新";
  return new Date(value).toLocaleString();
}

export function selectProjectCover(bundle?: ArtifactBundle): ProjectCover | null {
  const video = firstWithUrl([
    ...(bundle?.rendered_clips || []),
    ...compactArtifacts(bundle?.planned_segments?.map((segment) => segment.rendered_clip) || [])
  ]);
  if (video) return { kind: "video", name: video.name, url: video.url };

  const image = firstWithUrl([
    ...(bundle?.scene_frames || []),
    ...compactArtifacts(bundle?.planned_segments?.map((segment) => segment.scene_master_frame) || []),
    ...(bundle?.character_images || [])
  ]);
  if (image) return { kind: "image", name: image.name, url: image.url };

  return null;
}

function compactArtifacts(items: Array<ArtifactItem | null | undefined>): ArtifactItem[] {
  return items.filter((item): item is ArtifactItem => Boolean(item));
}

function firstWithUrl(items: ArtifactItem[]): (ArtifactItem & { url: string }) | null {
  return items.find((item): item is ArtifactItem & { url: string } => Boolean(item.url)) || null;
}
