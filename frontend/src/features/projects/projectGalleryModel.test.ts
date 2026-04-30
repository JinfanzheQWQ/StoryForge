import { describe, expect, it } from "vitest";
import type { ArtifactBundle } from "../../types";
import {
  countProjectsByProduct,
  filterProjectsByProduct,
  formatProjectUpdatedAt,
  getProjectOpenPath,
  getProjectProductLabel,
  getProjectTitle,
  selectProjectCover
} from "./projectGalleryModel";

describe("projectGalleryModel", () => {
  it("selects rendered video clips before any image cover", () => {
    const bundle: ArtifactBundle = {
      rendered_clips: [{ name: "clip.mp4", url: "/media/clip.mp4" }],
      scene_frames: [{ name: "scene.png", url: "/media/scene.png" }],
      character_images: [{ name: "role.png", url: "/media/role.png" }]
    };

    expect(selectProjectCover(bundle)).toEqual({
      kind: "video",
      name: "clip.mp4",
      posterUrl: "/media/scene.png",
      url: "/media/clip.mp4"
    });
  });

  it("uses planned segment clips when top-level clips are empty", () => {
    const bundle: ArtifactBundle = {
      planned_segments: [
        {
          chapter_number: 1,
          rendered_clip: { name: "seg.mp4", url: "/media/seg.mp4" },
          segment_id: "seg-01",
          title: "片段"
        }
      ]
    };

    expect(selectProjectCover(bundle)).toEqual({
      kind: "video",
      name: "seg.mp4",
      url: "/media/seg.mp4"
    });
  });

  it("selects scene images before character images", () => {
    const bundle: ArtifactBundle = {
      character_images: [{ name: "role.png", url: "/media/role.png" }],
      scene_frames: [{ name: "scene.png", url: "/media/scene.png" }]
    };

    expect(selectProjectCover(bundle)).toEqual({
      kind: "image",
      name: "scene.png",
      url: "/media/scene.png"
    });
  });

  it("falls back to character images and returns null when no usable url exists", () => {
    expect(selectProjectCover({ character_images: [{ name: "role.png", url: "/media/role.png" }] })).toEqual({
      kind: "image",
      name: "role.png",
      url: "/media/role.png"
    });

    expect(selectProjectCover({ scene_frames: [{ name: "missing-url.png" }] })).toBeNull();
    expect(selectProjectCover()).toBeNull();
  });

  it("formats project title and update timestamp fallbacks", () => {
    expect(getProjectTitle({ project_id: "p1", story_title: "故事标题", title_hint: "提示标题" })).toBe("故事标题");
    expect(getProjectTitle({ project_id: "p1", title_hint: "提示标题" })).toBe("提示标题");
    expect(getProjectTitle({ project_id: "p1" })).toBe("未命名项目");
    expect(formatProjectUpdatedAt()).toBe("等待更新");
  });

  it("filters projects by product type and resolves product metadata", () => {
    const projects = [
      { product_type: "novel_to_video", project_id: "video-1", title_hint: "视频项目" },
      { product_type: "image_generation", project_id: "image-1", title_hint: "生图工作台" }
    ];

    expect(filterProjectsByProduct(projects, "image_generation")).toEqual([projects[1]]);
    expect(countProjectsByProduct(projects)).toEqual({
      all: 2,
      image_generation: 1,
      novel_to_video: 1
    });
    expect(getProjectProductLabel(projects[0])).toBe("小说转视频");
    expect(getProjectProductLabel(projects[1])).toBe("生图");
    expect(getProjectOpenPath(projects[0])).toBe("/console/projects/video-1");
    expect(getProjectOpenPath(projects[1])).toBe("/console/image-projects/image-1");
  });
});
