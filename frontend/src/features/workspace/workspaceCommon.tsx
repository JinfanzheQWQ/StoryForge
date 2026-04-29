import { Film } from "lucide-react";
import type { ArtifactItem, PlannedSegmentArtifact } from "../../types";
import { isVideoAsset } from "./workspaceModel";

export function WorkspaceHeading({ eyebrow, summary, title }: { eyebrow: string; summary: string; title: string }) {
  return (
    <div className="workspace-heading">
      <p className="eyebrow">{eyebrow}</p>
      <h3>{title}</h3>
      <span>{summary}</span>
    </div>
  );
}

export function StageEmpty({ description, title }: { description: string; title: string }) {
  return (
    <div className="stage-empty">
      <Film size={30} aria-hidden="true" />
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}

export function AssetPreview({ item }: { item?: ArtifactItem | null }) {
  if (item?.url) {
    if (isVideoAsset(item)) {
      return <video muted src={item.url} aria-label={item.name} />;
    }
    return <img src={item.url} alt={item.name} />;
  }
  return (
    <div className="asset-thumb-empty">
      <Film size={20} aria-hidden="true" />
    </div>
  );
}

export function AssetLine({ item }: { item: ArtifactItem }) {
  return (
    <a className="asset-line" href={item.url || item.path || "#"} target={item.url ? "_blank" : undefined} rel="noreferrer">
      <span>{item.name}</span>
      <em>{item.url ? "打开" : item.path || "本地产物"}</em>
    </a>
  );
}

export function Metric({ label, value, detail }: { label: string; value: string | number; detail: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{detail}</em>
    </div>
  );
}

export function MediaStage({ segment }: { segment?: PlannedSegmentArtifact }) {
  const clip = segment?.rendered_clip;
  const sceneMaster = segment?.scene_master_frame;

  if (clip?.url) {
    return (
      <video controls src={clip.url} poster={sceneMaster?.url} aria-label={segment?.title || "当前视频片段"}>
        <track kind="captions" />
      </video>
    );
  }

  if (sceneMaster?.url) {
    return <img src={sceneMaster.url} alt={`${segment?.scene_title || segment?.scene_id || "场景"}母图`} />;
  }

  return (
    <div className="theater-placeholder">
      <Film size={34} aria-hidden="true" />
      <strong>等待可审阅媒体</strong>
      <span>完成场景母图或视频生成后，这里会显示当前片段素材。</span>
    </div>
  );
}
