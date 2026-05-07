import { ArrowUpRight, Film, FolderOpen, LoaderCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { resolveApiAssetUrl } from "../../api/client";
import type { ArtifactBundle, AgentSession } from "../../types";
import {
  getAgentWorkspacePath,
  getArtifactPreviewStats,
  getFinalVideoUrl,
  readString
} from "./agentSessionModel";

interface AgentArtifactPreviewProps {
  artifacts?: ArtifactBundle | null;
  isLoading?: boolean;
  session?: AgentSession | null;
}

export function AgentArtifactPreview({ artifacts, isLoading = false, session }: AgentArtifactPreviewProps) {
  const workspacePath = getAgentWorkspacePath(session);
  const finalVideoUrl = resolveApiAssetUrl(getFinalVideoUrl(artifacts));
  const stats = getArtifactPreviewStats(artifacts);
  const hasProject = Boolean(session?.project_id);

  return (
    <section className="agent-artifact-preview" aria-label="当前产物">
      <header className="agent-panel-heading">
        <span>Output</span>
        <strong>当前产物</strong>
        <p>{hasProject ? "自动流程产物会同步到普通项目工作台。" : "确认计划后会创建项目并开始生产。"}</p>
      </header>

      <div className="agent-preview-stage">
        {finalVideoUrl ? (
          <video controls src={finalVideoUrl} />
        ) : (
          <div className="agent-preview-placeholder">
            {isLoading ? <LoaderCircle className="spin" size={18} aria-hidden="true" /> : <Film size={18} aria-hidden="true" />}
            <span>{isLoading ? "正在读取产物..." : "成片完成后会在这里预览"}</span>
          </div>
        )}
      </div>

      <div className="agent-output-stats">
        <span>角色 {stats.characters}</span>
        <span>场景 {stats.scenes}</span>
        <span>分段 {stats.segments}</span>
        <span>视频 {stats.clips}</span>
      </div>

      <div className="agent-output-actions">
        {workspacePath ? (
          <Link className="agent-workspace-link" to={workspacePath}>
            <FolderOpen size={15} aria-hidden="true" />
            进入工作台
            <ArrowUpRight size={14} aria-hidden="true" />
          </Link>
        ) : null}
        {readString(session?.result?.output_dir) ? <span>输出目录已生成</span> : null}
      </div>
    </section>
  );
}
