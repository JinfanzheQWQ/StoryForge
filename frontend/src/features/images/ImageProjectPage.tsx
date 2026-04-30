import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, ImageIcon, Loader2 } from "lucide-react";
import { getTaskArtifacts } from "../../api/artifacts";
import { resolveApiAssetUrl } from "../../api/client";
import { getProject } from "../../api/projects";
import { queryKeys } from "../../api/queryKeys";
import type { ArtifactBundle, ImageGenerationResult, TaskRecord } from "../../types";

export function ImageProjectPage() {
  const { projectId } = useParams();
  const projectQuery = useQuery({
    enabled: Boolean(projectId),
    queryFn: () => getProject(projectId || ""),
    queryKey: queryKeys.project(projectId)
  });
  const imageTasks = useMemo(
    () => (projectQuery.data?.tasks || []).filter((task) => task.task_type === "image.generate"),
    [projectQuery.data?.tasks]
  );
  const selectedTask = imageTasks[0];
  const artifactsQuery = useQuery({
    enabled: Boolean(selectedTask?.task_id),
    queryFn: () => getTaskArtifacts(selectedTask?.task_id || ""),
    queryKey: queryKeys.artifacts(selectedTask?.task_id)
  });

  if (projectQuery.isLoading) {
    return (
      <section className="image-project-page">
        <div className="image-project-loading">
          <Loader2 className="spin" size={28} aria-hidden="true" />
          正在加载生图产品...
        </div>
      </section>
    );
  }

  if (projectQuery.isError || !projectQuery.data) {
    return (
      <section className="image-project-page">
        <div className="error-callout">生图产品加载失败，请确认后端 API 已启动。</div>
      </section>
    );
  }

  const selectedResult = getImageGenerationResult(selectedTask);
  const imageUrl = resolveImageResultUrl(selectedTask, artifactsQuery.data);
  const referenceImages = selectedResult?.reference_images || [];
  const requestInfo = selectedResult?.request_info || selectedResult?.gpt_image_request || selectedResult?.seedream_request;
  const requestPayload = requestInfo?.payload;
  const projectTitle = projectQuery.data.story_title || projectQuery.data.title_hint || "生图作品";

  return (
    <section className="image-project-page">
      <header className="image-project-header">
        <div>
          <p className="eyebrow">Image Product</p>
          <h1>{projectTitle}</h1>
          <p>查看这个生图产品的图片结果、Prompt、参考图和真实提交参数。</p>
        </div>
        <span>{formatTaskTime(selectedTask?.finished_at || selectedTask?.created_at)}</span>
      </header>

      {imageTasks.length === 0 ? (
        <div className="image-project-empty">
          <ImageIcon size={32} aria-hidden="true" />
          <strong>还没有生图结果</strong>
          <span>完成一次生图后，这里会展示图片、prompt 和生成参数。</span>
        </div>
      ) : (
        <div className="image-product-board">
          <main className="image-product-main">
            <div className="image-product-preview">
              {imageUrl ? (
                <div className="image-fit-canvas">
                  <img alt="生图作品预览" src={imageUrl} />
                </div>
              ) : (
                <div className="image-preview-empty">
                  <ImageIcon size={34} aria-hidden="true" />
                  <strong>暂无可展示图片</strong>
                  <span>当前任务可能尚未完成或图片地址不可用。</span>
                </div>
              )}
            </div>
          </main>

          <aside className="image-product-detail" aria-label="生图参数">
            <div className="image-product-status">
              <span>{formatImageMode(selectedResult?.mode)}</span>
              <strong>{formatTaskStatus(selectedTask)}</strong>
            </div>

            <section>
              <h2>Prompt</h2>
              <p>{selectedResult?.prompt || "暂无 prompt"}</p>
            </section>

            <dl className="image-product-params">
              <div>
                <dt>模型</dt>
                <dd>{formatImageModelLabel(selectedResult?.model)}</dd>
              </div>
              <div>
                <dt>分辨率</dt>
                <dd>{selectedResult?.size || "2K"}</dd>
              </div>
              <div>
                <dt>比例</dt>
                <dd>{selectedResult?.aspect_ratio || "16:9"}</dd>
              </div>
              <div>
                <dt>提交尺寸</dt>
                <dd>{formatSubmittedSize(requestPayload)}</dd>
              </div>
              {isSeedreamResult(selectedResult) ? (
                <div>
                  <dt>水印</dt>
                  <dd>{selectedResult?.seedream_watermark ? "开启" : "关闭"}</dd>
                </div>
              ) : null}
            </dl>

            {referenceImages.length > 0 ? (
              <section>
                <h2>参考图</h2>
                <div className="image-reference-list">
                  {referenceImages.map((url) => (
                    <a key={url} href={url} rel="noreferrer" target="_blank">
                      {url}
                    </a>
                  ))}
                </div>
              </section>
            ) : null}

            {imageUrl ? (
              <a className="image-open-link" href={imageUrl} rel="noreferrer" target="_blank">
                打开图片
                <ArrowUpRight size={14} aria-hidden="true" />
              </a>
            ) : null}

            {requestPayload ? (
              <details className="image-request-details">
                <summary>提交请求</summary>
                <div className="image-request-scroll">
                  <textarea
                    aria-label="提交请求 JSON"
                    className="image-request-code"
                    readOnly
                    value={JSON.stringify(requestPayload, null, 2)}
                    wrap="off"
                  />
                </div>
              </details>
            ) : null}
          </aside>
        </div>
      )}
    </section>
  );
}

function getImageGenerationResult(task?: TaskRecord): ImageGenerationResult | null {
  if (!task?.result) {
    return null;
  }
  return task.result as ImageGenerationResult;
}

function resolveImageResultUrl(task?: TaskRecord, artifacts?: ArtifactBundle): string {
  const artifactUrl = artifacts?.scene_frames?.[0]?.url;
  if (artifactUrl) {
    return resolveApiAssetUrl(artifactUrl);
  }
  const result = getImageGenerationResult(task);
  return resolveApiAssetUrl(result?.output_url || result?.image_url || result?.generated_url || "");
}

function formatImageMode(mode?: string) {
  return mode === "image_to_image" ? "图生图" : "文生图";
}

function formatImageModelLabel(model?: string) {
  if (model === "doubao-seedream-4-5-251128") {
    return "Seedream 4.5";
  }
  return "GPT Image 2";
}

function formatTaskStatus(task?: TaskRecord) {
  if (!task) return "未开始";
  if (task.status === "completed") return "已完成";
  if (task.status === "running") return "生成中";
  if (task.status === "queued") return "排队中";
  if (task.status === "failed") return "失败";
  return String(task.status);
}

function formatTaskTime(value?: string | null) {
  if (!value) return "等待完成";
  return new Date(value).toLocaleString();
}

function formatRequestValue(value: unknown) {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function formatSubmittedSize(payload?: Record<string, unknown>) {
  if (!payload) return "等待提交";
  const input = payload.input;
  if (input && typeof input === "object" && !Array.isArray(input)) {
    const typedInput = input as Record<string, unknown>;
    const resolution = formatRequestValue(typedInput.resolution);
    const ratio = formatRequestValue(typedInput.aspect_ratio);
    return [resolution, ratio].filter(Boolean).join(" / ") || "等待提交";
  }
  return formatRequestValue(payload.size) || "等待提交";
}

function isSeedreamResult(result: ImageGenerationResult | null) {
  return result?.model === "doubao-seedream-4-5-251128" || result?.seedream_watermark != null;
}
