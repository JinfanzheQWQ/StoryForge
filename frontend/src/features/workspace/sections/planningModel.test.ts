import { describe, expect, it } from "vitest";
import { buildSceneBlueprintRows } from "./planningModel";

describe("planningModel", () => {
  it("builds visible scene blueprint rows before segment contracts exist", () => {
    const rows = buildSceneBlueprintRows([
      {
        chapter_number: 1,
        involved_characters: ["林屿", "苏晚"],
        scene_bible: {
          location: "图书馆旁的郁金香花田"
        },
        scene_id: "ch01-sc01",
        scene_transition_contract: {
          next_scene_entry_match: "林屿站在花径入口，苏晚在花田尽头拍照"
        },
        segment_count: 0,
        summary: "林屿走进花田，准备开口。",
        title: "花田入口"
      }
    ]);

    expect(rows).toEqual([
      expect.objectContaining({
        chapterLabel: "第 1 章",
        characters: "林屿 / 苏晚",
        location: "图书馆旁的郁金香花田",
        sceneId: "ch01-sc01",
        statusLabel: "结构已生成",
        title: "花田入口",
        transition: "林屿站在花径入口，苏晚在花田尽头拍照"
      })
    ]);
  });
});
