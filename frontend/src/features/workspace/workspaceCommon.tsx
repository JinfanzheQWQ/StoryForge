import { useEffect, useState } from "react";
import { Film } from "lucide-react";
import { resolveApiAssetUrl } from "../../api/client";
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
  const [failedUrl, setFailedUrl] = useState("");
  const url = resolveApiAssetUrl(item?.url);
  const mediaName = item?.name || "媒体资源";

  useEffect(() => {
    setFailedUrl("");
  }, [url]);

  if (item && url && failedUrl !== url) {
    if (isVideoAsset(item)) {
      return <video muted src={url} aria-label={mediaName} onError={() => setFailedUrl(url)} />;
    }
    return <img src={url} alt={mediaName} onError={() => setFailedUrl(url)} />;
  }
  return (
    <div className="asset-thumb-empty">
      <Film size={20} aria-hidden="true" />
      {failedUrl ? <span>图片暂不可访问</span> : null}
    </div>
  );
}

export function AssetLine({ item }: { item: ArtifactItem }) {
  const url = resolveApiAssetUrl(item.url);
  return (
    <a className="asset-line" href={url || item.path || "#"} target={url ? "_blank" : undefined} rel="noreferrer">
      <span>{item.name}</span>
      <em>{url ? "打开" : item.path || "本地产物"}</em>
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
  const clipUrl = resolveApiAssetUrl(clip?.url);
  const posterUrl = resolveApiAssetUrl(sceneMaster?.url);

  if (clipUrl) {
    return (
      <video controls src={clipUrl} poster={posterUrl || undefined} aria-label={segment?.title || "当前视频片段"}>
        <track kind="captions" />
      </video>
    );
  }

  if (posterUrl) {
    return <img src={posterUrl} alt={`${segment?.scene_title || segment?.scene_id || "场景"}母图`} />;
  }

  return (
    <div className="theater-placeholder">
      <Film size={34} aria-hidden="true" />
      <strong>等待可审阅媒体</strong>
      <span>完成场景母图或视频生成后，这里会显示当前片段素材。</span>
    </div>
  );
}
