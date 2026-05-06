import type { PlannedSegmentArtifact, SceneArtifactItem, SegmentContractProgress } from "../../../types";
import { StageEmpty, WorkspaceHeading } from "../workspaceCommon";
import { buildSceneBlueprintRows } from "./planningModel";

export function PlanningWorkspace({
  plannedSegments,
  segmentContractProgress,
  scenes,
  setSelectedSegmentId
}: {
  plannedSegments: PlannedSegmentArtifact[];
  segmentContractProgress?: SegmentContractProgress | null;
  scenes: SceneArtifactItem[];
  setSelectedSegmentId: (segmentId: string) => void;
}) {
  const progressWarning = buildSegmentContractProgressWarning(segmentContractProgress);
  if (!plannedSegments.length) {
    const sceneRows = buildSceneBlueprintRows(scenes);
    if (!sceneRows.length) {
      return <StageEmpty title="还没有结构产物" description="先生成场景结构。完成后这里会展示 scene 蓝图，再继续生成分段合同。" />;
    }
    return (
      <section className="planning-workspace" aria-label="场景结构蓝图">
        {progressWarning ? <SegmentContractProgressWarning warning={progressWarning} /> : null}
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
      {progressWarning ? <SegmentContractProgressWarning warning={progressWarning} /> : null}
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

function buildSegmentContractProgressWarning(progress?: SegmentContractProgress | null) {
  if (!progress || String(progress.status || "").toLowerCase() !== "failed") return null;
  const completed = [
    progress.completed_scene_count ? `已完成 ${progress.completed_scene_count}/${progress.total_scenes || "?"} 个 scene` : "",
    progress.completed_chunk_count ? `已完成 ${progress.completed_chunk_count}/${progress.total_chunks || "?"} 个 chunk` : "",
    progress.completed_segment_count ? `已生成 ${progress.completed_segment_count} 个 segment` : ""
  ].filter(Boolean).join("，");
  const failedAt = [
    progress.failed_chapter_number ? `第 ${progress.failed_chapter_number} 章` : "",
    progress.failed_scene_id || "",
    progress.failed_chunk_id || ""
  ].filter(Boolean).join(" · ");
  return {
    completed,
    failedAt,
    lastError: String(progress.last_error || "").trim(),
    resumeReady: Boolean(progress.resume_ready)
  };
}

function SegmentContractProgressWarning({
  warning
}: {
  warning: {
    completed: string;
    failedAt: string;
    lastError: string;
    resumeReady: boolean;
  };
}) {
  return (
    <div className="error-callout" role="alert">
      <strong>分段合同生成失败，当前只展示了已完成的部分片段。</strong>
      {warning.failedAt ? <span>失败位置：{warning.failedAt}</span> : null}
      {warning.completed ? <span>进度：{warning.completed}</span> : null}
      <span>{warning.resumeReady ? "可以点击“继续生成分段合同”从失败位置恢复。" : "可以重新生成分段合同。"}</span>
      {warning.lastError ? <details><summary>查看错误详情</summary><pre>{warning.lastError}</pre></details> : null}
    </div>
  );
}
