import type { PlannedSegmentArtifact, SceneArtifactItem } from "../../../types";
import { StageEmpty, WorkspaceHeading } from "../workspaceCommon";
import { buildSceneBlueprintRows } from "./planningModel";

export function PlanningWorkspace({
  plannedSegments,
  scenes,
  setSelectedSegmentId
}: {
  plannedSegments: PlannedSegmentArtifact[];
  scenes: SceneArtifactItem[];
  setSelectedSegmentId: (segmentId: string) => void;
}) {
  if (!plannedSegments.length) {
    const sceneRows = buildSceneBlueprintRows(scenes);
    if (!sceneRows.length) {
      return <StageEmpty title="还没有结构产物" description="先生成场景结构。完成后这里会展示 scene 蓝图，再继续生成分段合同。" />;
    }
    return (
      <section className="planning-workspace" aria-label="场景结构蓝图">
        <WorkspaceHeading eyebrow="Scene Structure" title="场景结构已生成" summary="这是 scene 级故事蓝图。下一步生成分段合同后，会拆成可执行 segment 清单。" />
        <div className="scene-blueprint-list">
          <div className="scene-blueprint-head">
            <span>Scene</span>
            <span>地点</span>
            <span>角色</span>
            <span>承接</span>
            <span>状态</span>
          </div>
          {sceneRows.map((scene) => (
            <article className="scene-blueprint-row" key={scene.sceneId}>
              <div>
                <em>{scene.chapterLabel}</em>
                <strong>{scene.title}</strong>
                <span>{scene.sceneId}</span>
              </div>
              <p>{scene.location}</p>
              <p>{scene.characters}</p>
              <p>{scene.transition}</p>
              <span>{scene.statusLabel}</span>
            </article>
          ))}
        </div>
      </section>
    );
  }
  return (
    <section className="planning-workspace" aria-label="规划结构">
      <WorkspaceHeading eyebrow="Story Blueprint" title="故事结构蓝图" summary="把 scene 和 segment 作为可执行生产清单，检查地点、时长、素材就绪和出片状态。" />
      <div className="planning-ledger">
        <div className="planning-head">
          <span>Segment</span>
          <span>Scene</span>
          <span>Duration</span>
          <span>Scene Ready</span>
          <span>Video</span>
        </div>
        {plannedSegments.map((segment) => (
          <button className="planning-row" key={segment.segment_id} type="button" onClick={() => setSelectedSegmentId(segment.segment_id)}>
            <span>{segment.segment_id}</span>
            <span>{segment.scene_title || segment.scene_id || "未绑定"}</span>
            <span>{segment.duration_seconds ? `${segment.duration_seconds}s` : "未定"}</span>
            <span>{segment.scene_ready ? "已就绪" : "待素材"}</span>
            <span>{segment.rendered_clip?.url ? "已出片" : "未生成"}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
