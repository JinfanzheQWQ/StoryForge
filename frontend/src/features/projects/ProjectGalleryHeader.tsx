export function ProjectGalleryHeader({ projectCount }: { projectCount: number }) {
  return (
    <header className="project-gallery-header">
      <div>
        <p className="eyebrow">Project Library</p>
        <h2 id="library-title">项目库</h2>
      </div>
      <span>{projectCount} 个项目</span>
    </header>
  );
}
