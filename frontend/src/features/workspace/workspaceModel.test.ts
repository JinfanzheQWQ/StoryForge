import { describe, expect, it } from "vitest";
import {
  buildSceneRows,
  getSceneMasterActionState,
  getStageCompletionState,
  resolveEditableSourceTaskId
} from "./workspaceModel";

describe("workspaceModel", () => {
  it("treats a completed scene-structure task as completed before artifacts finish refreshing", () => {
    expect(
      getStageCompletionState({
        activeTaskStatus: "completed",
        activeTaskType: "project.scene_structure",
        characterCount: 0,
        hasSceneStructure: false,
        plannedSegmentCount: 0
      })
    ).toEqual({
      charactersComplete: false,
      sceneStructureComplete: true,
      segmentContractsComplete: false
    });
  });

  it("treats completed segment contracts as both structure and contract completion", () => {
    expect(
      getStageCompletionState({
        activeTaskStatus: "completed",
        activeTaskType: "project.segment_contracts",
        characterCount: 0,
        hasSceneStructure: false,
        plannedSegmentCount: 0
      })
    ).toEqual({
      charactersComplete: false,
      sceneStructureComplete: true,
      segmentContractsComplete: true
    });
  });

  it("treats generated character artifacts as completed for the character stage", () => {
    expect(
      getStageCompletionState({
        activeTaskStatus: "completed",
        activeTaskType: "project.characters",
        characterCount: 2,
        hasSceneStructure: false,
        plannedSegmentCount: 0
      })
    ).toEqual({
      charactersComplete: true,
      sceneStructureComplete: false,
      segmentContractsComplete: false
    });
  });

  it("resolves child stage tasks back to the editable story source task", () => {
    const sourceTask = {
      project_id: "p1",
      result: { story_source_path: "/outputs/story_source.json" },
      status: "completed",
      task_id: "story-task"
    };
    const childTask = {
      payload: { source_task_id: "story-task" },
      project_id: "p1",
      result: { pipeline_root_task_id: "story-task" },
      status: "completed",
      task_id: "character-task",
      task_type: "project.characters"
    };

    expect(
      resolveEditableSourceTaskId({
        activeTask: childTask,
        fallbackTaskId: "character-task",
        tasks: [sourceTask, childTask]
      })
    ).toBe("story-task");
  });

  it("keeps the previous editable source while a newly submitted child task is not in the project list yet", () => {
    expect(
      resolveEditableSourceTaskId({
        fallbackTaskId: "new-child-task",
        tasks: [
          {
            project_id: "p1",
            result: { story_source_path: "/outputs/story_source.json" },
            status: "completed",
            task_id: "story-task"
          }
        ]
      })
    ).toBe("story-task");
  });

  it("merges scene master image files back into their scene rows", () => {
    const rows = buildSceneRows(
      [
        {
          chapter_number: 1,
          scene_id: "ch01-sc01",
          scene_title: "傍晚的花园",
          segment_id: "ch01-sc01-seg01",
          title: "片段"
        }
      ],
      [
        {
          kind: "image",
          name: "ch01-sc01_master.png",
          path: "/Users/xy/StoryForge/outputs/project/assets/frames/ch01-sc01_master.png",
          url: "/outputs/project/assets/frames/ch01-sc01_master.png"
        }
      ]
    );

    expect(rows).toHaveLength(1);
    expect(rows[0]).toEqual(
      expect.objectContaining({
        frame: expect.objectContaining({ name: "ch01-sc01_master.png" }),
        sceneId: "ch01-sc01",
        sceneTitle: "傍晚的花园",
        segmentCount: 1
      })
    );
    expect(rows[0].summary).not.toContain("/Users/xy");
  });

  it("marks the selected scene master action as completed when the scene row is ready", () => {
    expect(
      getSceneMasterActionState({
        prompt: "",
        ready: true,
        sceneId: "ch01-sc01",
        sceneTitle: "花园",
        segmentCount: 2,
        segmentId: "ch01-sc01-seg01",
        summary: ""
      })
    ).toEqual({
      disabled: true,
      label: "场景母图已完成",
      sceneId: "ch01-sc01",
      state: "complete"
    });
  });

  it("keeps the selected scene master action available before the scene row is ready", () => {
    expect(
      getSceneMasterActionState({
        prompt: "",
        ready: false,
        sceneId: "ch01-sc02",
        sceneTitle: "长廊",
        segmentCount: 1,
        segmentId: "ch01-sc02-seg01",
        summary: ""
      })
    ).toEqual({
      disabled: false,
      label: "生成当前场景母图",
      sceneId: "ch01-sc02",
      state: undefined
    });
  });
});
