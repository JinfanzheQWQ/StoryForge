import type { PlannedSegmentArtifact } from "../../../types";
import { Metric, WorkspaceHeading } from "../workspaceCommon";

export function OverviewWorkspace({
  characterCount,
  clipCount,
  plannedSegments,
  readySegments,
  sceneCount
}: {
  characterCount: number;
  clipCount: number;
  plannedSegments: PlannedSegmentArtifact[];
  readySegments: number;
  sceneCount: number;
}) {
  return (
    <section className="overview-workspace" aria-label="项目总览">
      <WorkspaceHeading eyebrow="Project Overview" title="生产总览" summary="快速判断项目是否已经具备审片和交付条件。" />
      <div className="overview-lanes">
        <Metric label="角色" value={characterCount} detail="角色资产" />
        <Metric label="场景" value={sceneCount} detail="环境母图" />
        <Metric label="视频" value={clipCount} detail="视频文件" />
        <Metric label="进度" value={`${readySegments}/${plannedSegments.length || 0}`} detail="片段完成" />
      </div>
    </section>
  );
}
