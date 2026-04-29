import { useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { getTaskArtifacts } from "../../api/artifacts";
import { deleteProject, listProjects } from "../../api/projects";
import { queryKeys } from "../../api/queryKeys";
import type { ProjectSummary } from "../../types";
import { ProjectCard } from "./ProjectCard";
import { ProjectGalleryHeader } from "./ProjectGalleryHeader";
import { getProjectTitle } from "./projectGalleryModel";

export function ProjectListPage() {
  const queryClient = useQueryClient();
  const [deleteTarget, setDeleteTarget] = useState<ProjectSummary | null>(null);
  const projectsQuery = useQuery({
    queryKey: queryKeys.projects(),
    queryFn: listProjects
  });
  const projects = projectsQuery.data || [];
  const artifactQueries = useQueries({
    queries: projects.map((project) => ({
      enabled: Boolean(project.latest_task_id),
      queryFn: () => getTaskArtifacts(project.latest_task_id as string),
      queryKey: queryKeys.projectCardArtifacts(project.latest_task_id),
      staleTime: 60_000
    }))
  });
  const deleteMutation = useMutation({
    mutationFn: (projectId: string) => deleteProject(projectId),
    onSuccess: () => {
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects() });
    }
  });

  return (
    <section className="library-studio project-gallery" aria-labelledby="library-title">
      <ProjectGalleryHeader projectCount={projects.length} />

      {projectsQuery.isError ? <div className="error-callout project-gallery-error">项目列表加载失败，请确认后端 API 已启动。</div> : null}
      {projectsQuery.isLoading ? <div className="project-gallery-loading">正在加载项目...</div> : null}

      {!projectsQuery.isLoading && projects.length === 0 ? (
        <div className="project-gallery-empty">
          <strong>还没有项目</strong>
          <span>完成生产后，项目会以视频或图片封面展示在这里。</span>
        </div>
      ) : null}

      {projects.length > 0 ? (
        <div className="project-card-grid" aria-label="项目列表">
          {projects.map((project, index) => (
            <ProjectCard
              key={project.project_id}
              artifacts={artifactQueries[index]?.data}
              artifactsLoading={artifactQueries[index]?.isLoading || artifactQueries[index]?.isFetching}
              deleting={deleteMutation.isPending && deleteMutation.variables === project.project_id}
              onDeleteRequest={() => setDeleteTarget(project)}
              project={project}
            />
          ))}
        </div>
      ) : null}

      {deleteTarget ? (
        <div className="project-delete-layer" role="presentation">
          <button
            aria-label="关闭删除确认"
            className="project-delete-scrim"
            type="button"
            onClick={() => {
              if (!deleteMutation.isPending) setDeleteTarget(null);
            }}
          />
          <section aria-labelledby="project-delete-title" aria-modal="true" className="project-delete-dialog" role="dialog">
            <p className="eyebrow">Danger Zone</p>
            <h3 id="project-delete-title">删除项目</h3>
            <p>将删除「{getProjectTitle(deleteTarget)}」的项目记录、任务记录和可清理输出目录。运行中的任务不会被删除。</p>
            {deleteMutation.isError ? <div className="error-callout">删除失败，请确认项目没有排队中或运行中的任务。</div> : null}
            <div className="project-delete-actions">
              <button className="ghost-button" disabled={deleteMutation.isPending} type="button" onClick={() => setDeleteTarget(null)}>
                取消
              </button>
              <button
                className="danger-button"
                disabled={deleteMutation.isPending}
                type="button"
                onClick={() => deleteMutation.mutate(deleteTarget.project_id)}
              >
                {deleteMutation.isPending ? "正在删除..." : "确认删除"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
