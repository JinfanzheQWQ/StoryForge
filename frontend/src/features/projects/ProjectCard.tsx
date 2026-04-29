import { useState } from "react";
import { Link } from "react-router-dom";
import { MoreHorizontal, Trash2 } from "lucide-react";
import type { ArtifactBundle, ProjectSummary } from "../../types";
import { formatProjectUpdatedAt, getProjectTitle, selectProjectCover, type ProjectCover } from "./projectGalleryModel";

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

  return (
    <article className="project-card">
      <Link className="project-card-open" to={`/console/projects/${project.project_id}`} aria-label={`打开项目 ${title}`}>
        <div className="project-card-media">
          <ProjectCardMedia cover={cover} loading={artifactsLoading} title={title} />
          {cover ? <span className="project-card-badge">{cover.kind === "video" ? "视频" : "图片"}</span> : null}
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
  if (cover?.kind === "video") {
    return <video aria-label={`${title} 视频预览`} muted playsInline preload="metadata" src={cover.url} />;
  }

  if (cover?.kind === "image") {
    return <img alt={`${title} 封面`} loading="lazy" src={cover.url} />;
  }

  return (
    <div className={loading ? "project-card-placeholder loading" : "project-card-placeholder"}>
      <span>{loading ? "加载资源" : title.slice(0, 1).toUpperCase()}</span>
    </div>
  );
}
