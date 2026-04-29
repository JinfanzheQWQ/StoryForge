import type { SceneArtifactItem } from "../../../types";

export type SceneBlueprintRow = {
  chapterLabel: string;
  characters: string;
  location: string;
  sceneId: string;
  segmentCount: number;
  statusLabel: string;
  summary: string;
  title: string;
  transition: string;
};

export function buildSceneBlueprintRows(scenes: SceneArtifactItem[] = []): SceneBlueprintRow[] {
  return scenes.map((scene, index) => {
    const bible = scene.scene_bible || {};
    const transitionContract = scene.scene_transition_contract || {};
    return {
      chapterLabel: scene.chapter_number ? `第 ${scene.chapter_number} 章` : `场景 ${index + 1}`,
      characters: formatList(scene.involved_characters, "未指定角色"),
      location: readString(bible, "location") || scene.scene_anchor || "未指定地点",
      sceneId: scene.scene_id || `scene-${index + 1}`,
      segmentCount: Number(scene.segment_count || 0),
      statusLabel: getSceneStatusLabel(scene),
      summary: scene.summary || scene.scene_anchor || "暂无摘要",
      title: scene.title || scene.scene_id || `场景 ${index + 1}`,
      transition:
        readString(transitionContract, "next_scene_entry_match") ||
        readString(transitionContract, "bridge_action") ||
        readString(transitionContract, "visual_bridge") ||
        "等待分段合同细化"
    };
  });
}

function getSceneStatusLabel(scene: SceneArtifactItem) {
  if (scene.segment_count && scene.segment_count > 0) return `${scene.segment_count} 个片段`;
  if (scene.scene_master_frame?.url) return "母图已就绪";
  if (scene.scene_master_frame_status === "failed") return "母图失败";
  return "结构已生成";
}

function readString(source: Record<string, unknown>, key: string) {
  const value = source[key];
  return typeof value === "string" ? value.trim() : "";
}

function formatList(items: string[] | undefined, fallback: string) {
  const values = (items || []).map((item) => item.trim()).filter(Boolean);
  return values.length ? values.join(" / ") : fallback;
}
