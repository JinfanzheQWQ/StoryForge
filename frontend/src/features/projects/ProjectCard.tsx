import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { MoreHorizontal, Trash2 } from "lucide-react";
import { resolveApiAssetUrl } from "../../api/client";
import type { ArtifactBundle, ProjectSummary } from "../../types";
import {
  formatProjectUpdatedAt,
  getProjectOpenPath,
  getProjectProductLabel,
  getProjectTitle,
  selectProjectCover,
  type ProjectCover
} from "./projectGalleryModel";

export function ProjectCard({
  artifacts,
  artifactsLoading,
  deleting,
  onDeleteRequest,
  project
}: {
  artifacts?: ArtifactBundle;
  artifactsLoading?: boolean;
  deleting?: boolean;
  onDeleteRequest: () => void;
  project: ProjectSummary;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const title = getProjectTitle(project);
  const cover = selectProjectCover(artifacts);
  const productLabel = getProjectProductLabel(project);

  return (
    <article className="project-card">
      <Link className="project-card-open" to={getProjectOpenPath(project)} aria-label={`打开 ${productLabel} ${title}`}>
        <div className="project-card-media">
          <ProjectCardMedia cover={cover} loading={artifactsLoading} title={title} />
          <span className="project-card-badge">{productLabel}</span>
          {cover ? <span className="project-card-kind">{cover.kind === "video" ? "视频" : "图片"}</span> : null}
        </div>
        <div className="project-card-body">
          <strong>{title}</strong>
          <span>{formatProjectUpdatedAt(project.updated_at)}</span>
        </div>
      </Link>
      <button
        aria-expanded={menuOpen}
        aria-label={`${title} 项目操作`}
        className="project-card-menu-trigger"
        disabled={deleting}
        type="button"
        onClick={() => setMenuOpen((value) => !value)}
      >
        <MoreHorizontal size={18} aria-hidden="true" />
      </button>
      {menuOpen ? (
        <div className="project-card-menu" role="menu">
          <button
            disabled={deleting}
            role="menuitem"
            type="button"
            onClick={() => {
              setMenuOpen(false);
              onDeleteRequest();
            }}
          >
            <Trash2 size={15} aria-hidden="true" />
            删除项目
          </button>
        </div>
      ) : null}
    </article>
  );
}

function ProjectCardMedia({ cover, loading, title }: { cover: ProjectCover | null; loading?: boolean; title: string }) {
  const [failedMedia, setFailedMedia] = useState(false);
  const mediaUrl = resolveApiAssetUrl(cover?.url);
  const posterUrl = resolveApiAssetUrl(cover?.posterUrl);

  useEffect(() => {
    setFailedMedia(false);
  }, [mediaUrl]);

  if (failedMedia) {
    return <ProjectCardPlaceholder failed label="封面不可用" title={title} />;
  }

  if (cover?.kind === "video") {
    return (
      <video
        aria-label={`${title} 视频预览`}
        autoPlay
        loop
        muted
        playsInline
        poster={posterUrl || undefined}
        preload="metadata"
        src={mediaUrl}
        onError={() => setFailedMedia(true)}
      />
    );
  }

  if (cover?.kind === "image") {
    return <img alt={`${title} 封面`} loading="lazy" src={mediaUrl} onError={() => setFailedMedia(true)} />;
  }

  return <ProjectCardPlaceholder label={loading ? "加载资源" : title.slice(0, 1).toUpperCase()} loading={loading} title={title} />;
}

function ProjectCardPlaceholder({
  failed,
  label,
  loading,
  title
}: {
  failed?: boolean;
  label: string;
  loading?: boolean;
  title: string;
}) {
  const className = ["project-card-placeholder", loading ? "loading" : "", failed ? "failed" : ""].filter(Boolean).join(" ");
  return (
    <div aria-label={`${title} 暂无封面`} className={className}>
      <span>{label}</span>
    </div>
  );
}
