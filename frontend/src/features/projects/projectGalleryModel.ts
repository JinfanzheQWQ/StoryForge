import type { ArtifactBundle, ArtifactItem, ProjectSummary } from "../../types";

export type ProjectProductFilter = "all" | "novel_to_video" | "image_generation";

export type ProjectCover = {
  kind: "video" | "image";
  name: string;
  posterUrl?: string;
  url: string;
};

export function getProjectTitle(project: ProjectSummary) {
  if (isImageGenerationProject(project)) {
    return project.story_title || project.title_hint || "生图作品";
  }
  return project.story_title || project.title_hint || "未命名项目";
}

export function getProjectProductLabel(project: ProjectSummary) {
  return isImageGenerationProject(project) ? "生图" : "小说转视频";
}

export function getProjectOpenPath(project: ProjectSummary) {
  return isImageGenerationProject(project) ? `/console/image-projects/${project.project_id}` : `/console/projects/${project.project_id}`;
}

export function filterProjectsByProduct(projects: ProjectSummary[], filter: ProjectProductFilter) {
  if (filter === "all") {
    return projects;
  }
  return projects.filter((project) => normalizeProjectProductType(project) === filter);
}

export function countProjectsByProduct(projects: ProjectSummary[]) {
  return {
    all: projects.length,
    image_generation: projects.filter(isImageGenerationProject).length,
    novel_to_video: projects.filter((project) => !isImageGenerationProject(project)).length
  };
}

export function formatProjectUpdatedAt(value?: string) {
  if (!value) return "等待更新";
  return new Date(value).toLocaleString();
}

export function selectProjectCover(bundle?: ArtifactBundle): ProjectCover | null {
  const image = selectPosterImage(bundle);
  const video = firstWithUrl([
    ...(bundle?.rendered_clips || []),
    ...compactArtifacts(bundle?.planned_segments?.map((segment) => segment.rendered_clip) || [])
  ]);
  if (video) {
    return image
      ? { kind: "video", name: video.name, posterUrl: image.url, url: video.url }
      : { kind: "video", name: video.name, url: video.url };
  }

  if (image) return { kind: "image", name: image.name, url: image.url };

  return null;
}

export function normalizeProjectProductType(project: ProjectSummary) {
  return project.product_type === "image_generation" ? "image_generation" : "novel_to_video";
}

export function isImageGenerationProject(project: ProjectSummary) {
  return normalizeProjectProductType(project) === "image_generation";
}

function compactArtifacts(items: Array<ArtifactItem | null | undefined>): ArtifactItem[] {
  return items.filter((item): item is ArtifactItem => Boolean(item));
}

function selectPosterImage(bundle?: ArtifactBundle): (ArtifactItem & { url: string }) | null {
  return firstWithUrl([
    ...(bundle?.scene_frames || []),
    ...compactArtifacts(bundle?.planned_segments?.map((segment) => segment.scene_master_frame) || []),
    ...(bundle?.character_images || [])
  ]);
}

function firstWithUrl(items: ArtifactItem[]): (ArtifactItem & { url: string }) | null {
  return items.find((item): item is ArtifactItem & { url: string } => Boolean(item.url)) || null;
}
