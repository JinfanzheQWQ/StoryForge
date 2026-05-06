import { describe, expect, it } from "vitest";
import {
  areCharacterImagesReady,
  buildSceneRows,
  getSceneMasterActionState,
  getStageCompletionState,
  resolveEditableSourceTaskId,
  resolveRestorableActiveTaskId,
  resolveSourceTask,
  sectionForTaskType
} from "./workspaceModel";

describe("workspaceModel", () => {
  it("treats a completed scene-structure task as completed before artifacts finish refreshing", () => {
    expect(
      getStageCompletionState({
        activeTaskStatus: "completed",
        activeTaskType: "project.scene_structure",
        charactersReady: false,
        hasSceneStructure: false,
        plannedSegmentCount: 0
      })
    ).toEqual({
      charactersComplete: false,
      sceneStructureComplete: true,
      segmentContractsComplete: false,
      segmentContractsFailed: false,
      segmentContractsResumeReady: false
    });
  });

  it("treats completed segment contracts as both structure and contract completion", () => {
    expect(
      getStageCompletionState({
        activeTaskStatus: "completed",
        activeTaskType: "project.segment_contracts",
        charactersReady: false,
        hasSceneStructure: false,
        plannedSegmentCount: 0
      })
    ).toEqual({
      charactersComplete: false,
      sceneStructureComplete: true,
      segmentContractsComplete: true,
      segmentContractsFailed: false,
      segmentContractsResumeReady: false
    });
  });

  it("treats completed character task as completed before artifacts finish refreshing", () => {
    expect(
      getStageCompletionState({
        activeTaskStatus: "completed",
        activeTaskType: "project.characters",
        charactersReady: false,
        hasSceneStructure: false,
        plannedSegmentCount: 0
      })
    ).toEqual({
      charactersComplete: true,
      sceneStructureComplete: false,
      segmentContractsComplete: false,
      segmentContractsFailed: false,
      segmentContractsResumeReady: false
    });
  });

  it("does not mark partial segment contracts as complete when progress failed", () => {
    expect(
      getStageCompletionState({
        activeTaskStatus: "failed",
        activeTaskType: "project.segment_contracts",
        charactersReady: false,
        hasSceneStructure: true,
        plannedSegmentCount: 6,
        segmentContractProgress: {
          resume_ready: true,
          status: "failed"
        }
      })
    ).toEqual({
      charactersComplete: false,
      sceneStructureComplete: true,
      segmentContractsComplete: false,
      segmentContractsFailed: true,
      segmentContractsResumeReady: true
    });
  });

  it("does not treat planned character manifest entries as ready images", () => {
    expect(
      areCharacterImagesReady([
        {
          kind: "image",
          name: "林屿",
          status: "planned",
          url: "/outputs/characters/linyu.png"
        }
      ])
    ).toBe(false);
  });

  it("treats generated character images with urls as ready", () => {
    expect(
      areCharacterImagesReady([
        {
          kind: "image",
          name: "林屿",
          status: "completed",
          url: "/outputs/characters/linyu.png"
        }
      ])
    ).toBe(true);
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

  it("resolves a freshly completed story task before the stale project task record", () => {
    const staleSourceTask = {
      project_id: "p1",
      result: {},
      status: "running",
      task_id: "story-task"
    };
    const freshSourceTask = {
      project_id: "p1",
      result: { story_source_path: "/outputs/story_source.json" },
      status: "completed",
      task_id: "story-task",
      task_type: "project.novel"
    };

    expect(
      resolveEditableSourceTaskId({
        activeTask: freshSourceTask,
        fallbackTaskId: "story-task",
        tasks: [staleSourceTask]
      })
    ).toBe("story-task");
    expect(
      resolveSourceTask({
        activeTask: freshSourceTask,
        sourceTaskId: "story-task",
        tasks: [staleSourceTask]
      })
    ).toEqual(freshSourceTask);
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

  it("restores a running stage task ahead of the route story task after refresh", () => {
    expect(
      resolveRestorableActiveTaskId({
        routeTaskId: "story-task",
        latestTaskId: "scene-task",
        tasks: [
          {
            created_at: "2026-05-01T10:00:00Z",
            project_id: "p1",
            status: "completed",
            task_id: "story-task",
            task_type: "project.story"
          },
          {
            created_at: "2026-05-01T10:01:00Z",
            payload: { source_task_id: "story-task" },
            project_id: "p1",
            status: "running",
            task_id: "scene-task",
            task_type: "project.scene_structure"
          }
        ]
      })
    ).toBe("scene-task");
  });

  it("maps running task types back to workspace sections", () => {
    expect(sectionForTaskType("project.scene_structure")).toBe("结构化信息");
    expect(sectionForTaskType("project.segment_contracts")).toBe("结构化信息");
    expect(sectionForTaskType("project.characters")).toBe("角色图");
    expect(sectionForTaskType("project.scenes")).toBe("场景母图");
    expect(sectionForTaskType("project.storyboards")).toBe("分段视频");
    expect(sectionForTaskType("project.videos")).toBe("分段视频");
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
