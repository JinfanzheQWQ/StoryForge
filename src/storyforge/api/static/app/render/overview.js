import {
  escapeHtml,
  getRunStageStatus,
  getStorySourceRevision,
  metricCard,
} from "../utils.js";

export function renderWorkbenchOverviewTab({ task, artifacts, context, run = null, helpers }) {
  const segments = helpers.buildTimelineSegments(artifacts);
  const sceneGroups = helpers.buildSceneGroups(segments);
  const readySceneCount = segments.filter((segment) => segment.sceneReady).length;
  const readyVideoCount = segments.filter((segment) => segment.videoReady).length;
  const highRiskCount = Number(artifacts?.continuity_summary?.high_risk_count || 0);
  const mediumRiskCount = Number(artifacts?.continuity_summary?.medium_risk_count || 0);
  const nextAction = (() => {
    if (!run) {
      return helpers.buildOverviewNote(task, artifacts, run);
    }
    const rootTask = run.rootTask || task;
    const storySourceRevision = getStorySourceRevision(rootTask);
    const sceneStructureStatus = getRunStageStatus(run.latestSceneStructureTask, storySourceRevision);
    const segmentContractsStatus = getRunStageStatus(run.latestSegmentContractsTask, storySourceRevision);
    const characterStatus = getRunStageStatus(run.latestCharacterTask, storySourceRevision);
    if (sceneStructureStatus !== "completed") {
      return "下一步：进入正文与结构，生成或重生成场景结构。";
    }
    if (segmentContractsStatus !== "completed") {
      return "下一步：进入正文与结构，生成分段合同。";
    }
    if (characterStatus !== "completed") {
      return "下一步：生成角色定妆图。";
    }
    if (segments.length && readySceneCount < segments.length) {
      return "下一步：进入场景工作台或分段审片台，补齐缺失的场景关键帧。";
    }
    if (segments.length && readyVideoCount < segments.length) {
      return "下一步：进入分段审片台，逐段生成或重生成视频。";
    }
    if (readyVideoCount >= 2 && !artifacts?.full_story) {
      return "下一步：检查视频片段后手动合并总片。";
    }
    return "当前版本主链路已就绪，可以继续审片、修 prompt 或合并总片。";
  })();

  return `
    <section class="workbench-overview-shell">
      <article class="asset-block workbench-command-card">
        <div>
          <p class="section-kicker">Command Center</p>
          <h4>生产总览</h4>
          <p class="asset-note">${escapeHtml(nextAction)}</p>
        </div>
        <div class="detail-metrics">
          ${metricCard("Scene", String(sceneGroups.length))}
          ${metricCard("Segment", String(segments.length))}
          ${metricCard("场景图", segments.length ? `${readySceneCount}/${segments.length}` : "0/0")}
          ${metricCard("视频", segments.length ? `${readyVideoCount}/${segments.length}` : "0/0")}
          ${metricCard("高风险", String(highRiskCount))}
          ${metricCard("中风险", String(mediumRiskCount))}
        </div>
      </article>
      ${run ? helpers.renderRunStageActions(run) : ""}
      ${helpers.renderContinuityOverview(artifacts?.continuity_summary)}
      ${helpers.renderFullStoryBlock(artifacts?.full_story, context)}
    </section>
  `;
}
