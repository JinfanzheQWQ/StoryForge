import type { ProjectProductFilter } from "./projectGalleryModel";

export function ProjectGalleryHeader({
  counts,
  filter,
  onFilterChange,
  projectCount
}: {
  counts: Record<ProjectProductFilter, number>;
  filter: ProjectProductFilter;
  onFilterChange: (filter: ProjectProductFilter) => void;
  projectCount: number;
}) {
  return (
    <header className="project-gallery-header">
      <div>
        <p className="eyebrow">Project Library</p>
        <h2 id="library-title">作品库</h2>
      </div>
      <div className="project-gallery-toolbar">
        <div className="project-filter-tabs" aria-label="作品类型筛选">
          <button className={filter === "all" ? "active" : ""} type="button" onClick={() => onFilterChange("all")}>
            全部 <em>{counts.all}</em>
          </button>
          <button
            className={filter === "novel_to_video" ? "active" : ""}
            type="button"
            onClick={() => onFilterChange("novel_to_video")}
          >
            小说转视频 <em>{counts.novel_to_video}</em>
          </button>
          <button
            className={filter === "image_generation" ? "active" : ""}
            type="button"
            onClick={() => onFilterChange("image_generation")}
          >
            生图 <em>{counts.image_generation}</em>
          </button>
        </div>
        <span>{projectCount} 个作品</span>
      </div>
    </header>
  );
}
