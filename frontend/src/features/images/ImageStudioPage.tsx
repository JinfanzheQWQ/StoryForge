import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowUpRight, CheckCircle2, ImageIcon, Layers, Loader2, WandSparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { resolveApiAssetUrl } from "../../api/client";
import { createImageGenerationTask, getImageGenerationCapabilities, saveImageGenerationTask } from "../../api/images";
import { getTask } from "../../api/tasks";
import type { ImageGenerationMode, ImageGenerationResult, ImageModelCapability, TaskRecord } from "../../types";

const MODE_COPY: Record<
  ImageGenerationMode,
  {
    action: string;
    eyebrow: string;
    helper: string;
    title: string;
  }
> = {
  text_to_image: {
    action: "生成图片",
    eyebrow: "Text to Image",
    helper: "直接描述画面、风格、构图和质感，选择模型后输出一张成图。",
    title: "文生图"
  },
  image_to_image: {
    action: "参考图生图",
    eyebrow: "Image to Image",
    helper: "提交一张可访问的参考图 URL，再用文字说明要保留或改变的部分。",
    title: "图生图"
  }
};

const DEFAULT_PROMPT: Record<ImageGenerationMode, string> = {
  text_to_image: "清晨的玻璃图书馆中庭，薄荷绿植物墙，柔和天光，清新科技感商业插画，干净构图，细节精致。",
  image_to_image: "基于参考图保持主体构图与空间关系，改成清新科技感商业插画风格，低饱和薄荷绿与浅青蓝配色，柔和光照。"
};

const GPT_IMAGE_MODEL = "gpt-image-2";
const SEEDREAM_MODEL = "doubao-seedream-4-5-251128";
const IMAGE_MODELS = [
  { label: "GPT Image 2", value: GPT_IMAGE_MODEL },
  { label: "Seedream 4.5", value: SEEDREAM_MODEL }
] as const;
const FALLBACK_MODEL_CAPABILITIES: ImageModelCapability[] = [
  {
    label: "GPT Image 2",
    value: GPT_IMAGE_MODEL,
    size_options: [
      { label: "1K", value: "1K", aspect_ratios: ["auto", "1:1", "9:16", "16:9", "4:3", "3:4"] },
      { label: "2K", value: "2K", aspect_ratios: ["1:1", "9:16", "16:9", "4:3", "3:4"] },
      { label: "4K", value: "4K", aspect_ratios: ["9:16", "16:9", "4:3", "3:4"] },
      { label: "自动", value: "auto", aspect_ratios: ["auto"] }
    ]
  },
  {
    label: "Seedream 4.5",
    value: SEEDREAM_MODEL,
    size_options: [
      { label: "2K", value: "2K", aspect_ratios: ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"] },
      { label: "4K", value: "4K", aspect_ratios: ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"] }
    ]
  }
];

export function ImageStudioPage() {
  const [mode, setMode] = useState<ImageGenerationMode>("text_to_image");
  const copy = MODE_COPY[mode];
  const [prompt, setPrompt] = useStateWithMode(DEFAULT_PROMPT[mode], mode);
  const [referenceUrl, setReferenceUrl] = useStateWithMode("", mode);
  const [model, setModel] = useState(GPT_IMAGE_MODEL);
  const [size, setSize] = useState("1K");
  const [aspectRatio, setAspectRatio] = useState("1:1");
  const [seedreamWatermark, setSeedreamWatermark] = useState(false);
  const [taskId, setTaskId] = useState("");
  const [formError, setFormError] = useState("");
  const [saveMessage, setSaveMessage] = useState("");
  const [savedProjectPath, setSavedProjectPath] = useState("");
  const seedreamSelected = model === SEEDREAM_MODEL;
  const selectedModelLabel = formatImageModelLabel(model);
  const capabilitiesQuery = useQuery({
    queryFn: getImageGenerationCapabilities,
    queryKey: ["image-generation-capabilities"],
    staleTime: 5 * 60 * 1000
  });
  const modelCapabilities = capabilitiesQuery.data?.models?.length
    ? capabilitiesQuery.data.models
    : FALLBACK_MODEL_CAPABILITIES;
  const selectedCapability =
    modelCapabilities.find((item) => item.value === model) || FALLBACK_MODEL_CAPABILITIES[0];
  const sizeOptions = selectedCapability?.size_options || [];
  const selectedSizeOption = sizeOptions.find((item) => item.value === size) || sizeOptions[0];
  const aspectRatioOptions = selectedSizeOption?.aspect_ratios || ["1:1"];

  const taskQuery = useQuery({
    enabled: Boolean(taskId),
    queryFn: () => getTask(taskId),
    queryKey: ["image-generation-task", taskId],
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 1200 : false;
    }
  });

  const mutation = useMutation({
    mutationFn: createImageGenerationTask,
    onError: (error) => {
      setFormError(error instanceof Error ? error.message : "提交失败，请稍后重试。");
    },
    onMutate: () => {
      setFormError("");
      setSaveMessage("");
      setSavedProjectPath("");
    },
    onSuccess: (response) => {
      setTaskId(response.task_id);
    }
  });
  const saveMutation = useMutation({
    mutationFn: saveImageGenerationTask,
    onError: (error) => {
      setFormError(error instanceof Error ? error.message : "保存失败，请稍后重试。");
    },
    onMutate: () => {
      setFormError("");
    },
    onSuccess: (response) => {
      setTaskId("");
      setImageUrlIndex(0);
      setSaveMessage("图片已保存到作品库。");
      setSavedProjectPath(`/console/image-projects/${response.project_id}`);
    }
  });

  useEffect(() => {
    if (!sizeOptions.some((item) => item.value === size)) {
      setSize(sizeOptions[0]?.value || "2K");
    }
  }, [size, sizeOptions]);
  useEffect(() => {
    if (!aspectRatioOptions.includes(aspectRatio)) {
      setAspectRatio(aspectRatioOptions[0] || "1:1");
    }
  }, [aspectRatio, aspectRatioOptions]);

  const currentTask = taskQuery.data;
  const taskActive = currentTask?.status === "queued" || currentTask?.status === "running";
  const busy = mutation.isPending || taskActive;
  const saving = saveMutation.isPending;
  const result = getImageGenerationResult(currentTask);
  const resultImageUrls = getImageGenerationImageUrls(result);
  const [imageUrlIndex, setImageUrlIndex] = useState(0);
  useEffect(() => {
    setImageUrlIndex(0);
  }, [taskId, resultImageUrls.join("|")]);
  const resultImageUrl = resolveApiAssetUrl(resultImageUrls[imageUrlIndex]);
  const references = parseReferenceImages(referenceUrl);

  function submitGeneration() {
    const normalizedPrompt = prompt.trim();
    const normalizedReferences = parseReferenceImages(referenceUrl);
    if (!normalizedPrompt) {
      setFormError("先写画面 prompt。");
      return;
    }
    if (mode === "image_to_image" && normalizedReferences.length === 0) {
      setFormError("图生图需要一张参考图 URL。");
      return;
    }
    mutation.mutate({
      mode,
      model,
      prompt: normalizedPrompt,
      reference_images: mode === "image_to_image" ? normalizedReferences : [],
      size,
      aspect_ratio: aspectRatio,
      seedream_watermark: seedreamSelected ? seedreamWatermark : undefined
    });
  }

  function saveGeneratedImage() {
    if (!currentTask?.task_id || currentTask.status !== "completed") {
      return;
    }
    saveMutation.mutate(currentTask.task_id);
  }

  return (
    <section className="image-studio-page">
      <div className="image-command-panel">
        <div className="image-mode-switch" aria-label="生图模式">
          <button
            className={mode === "text_to_image" ? "active" : ""}
            type="button"
            onClick={() => setMode("text_to_image")}
          >
            <WandSparkles size={15} aria-hidden="true" />
            文生图
          </button>
          <button
            className={mode === "image_to_image" ? "active" : ""}
            type="button"
            onClick={() => setMode("image_to_image")}
          >
            <Layers size={15} aria-hidden="true" />
            图生图
          </button>
        </div>

        <div className="image-command-heading">
          <span>{copy.eyebrow}</span>
          <h1>{copy.title}</h1>
          <p>{copy.helper}</p>
        </div>

        {mode === "image_to_image" ? (
          <label className="image-field">
            <span>参考图 URL</span>
            <input
              placeholder="https://example.com/reference.png"
              type="url"
              value={referenceUrl}
              onChange={(event) => setReferenceUrl(event.target.value)}
            />
          </label>
        ) : null}

        <div className="image-setting-grid">
          <label className="image-field image-model-field">
            <span>模型</span>
            <select value={model} onChange={(event) => setModel(event.target.value)}>
              {IMAGE_MODELS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="image-field">
            <span>分辨率</span>
            <select value={size} onChange={(event) => setSize(event.target.value)}>
              {sizeOptions.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="image-field">
            <span>比例</span>
            <select value={aspectRatio} onChange={(event) => setAspectRatio(event.target.value)}>
              {aspectRatioOptions.map((item) => (
                <option key={item} value={item}>
                  {formatAspectRatioLabel(item)}
                </option>
              ))}
            </select>
          </label>
        </div>

        {seedreamSelected ? (
          <label className="image-checkbox-field">
            <input
              checked={seedreamWatermark}
              type="checkbox"
              onChange={(event) => setSeedreamWatermark(event.target.checked)}
            />
            Seedream 水印
          </label>
        ) : null}

        <label className="image-field prompt-field">
          <span>Prompt</span>
          <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} />
        </label>

        <div className="image-command-meta">
          <span>{selectedModelLabel}</span>
          <span>{size}</span>
          <span>{formatAspectRatioLabel(aspectRatio)}</span>
          {seedreamSelected ? <span>{seedreamWatermark ? "带水印" : "无水印"}</span> : null}
          {mode === "image_to_image" ? <span>参考图 {references.length} 张</span> : null}
        </div>

        {formError || currentTask?.error ? (
          <div className="image-error" role="alert">
            <AlertCircle size={16} aria-hidden="true" />
            {formError || currentTask?.error}
          </div>
        ) : null}
        {saveMessage ? (
          <div className="image-save-message">
            <CheckCircle2 size={16} aria-hidden="true" />
            <span>{saveMessage}</span>
            {savedProjectPath ? <Link to={savedProjectPath}>查看作品</Link> : null}
          </div>
        ) : null}

        <button className="image-generate-button" disabled={busy} type="button" onClick={submitGeneration}>
          {busy ? <Loader2 className="spin" size={16} aria-hidden="true" /> : <WandSparkles size={16} aria-hidden="true" />}
          {busy ? "生成中..." : copy.action}
        </button>
      </div>

      <div className="image-result-stage">
        <div className="image-stage-bar">
          <div>
            <span>当前输出</span>
            <strong>{formatImageTaskStatus(currentTask)}</strong>
          </div>
          {resultImageUrl ? (
            <div className="image-stage-actions">
              <button disabled={saving || currentTask?.status !== "completed"} type="button" onClick={saveGeneratedImage}>
                {saving ? <Loader2 className="spin" size={14} aria-hidden="true" /> : <CheckCircle2 size={14} aria-hidden="true" />}
                保存到作品库
              </button>
              <a href={resultImageUrl} rel="noreferrer" target="_blank">
                打开图片
                <ArrowUpRight size={14} aria-hidden="true" />
              </a>
            </div>
          ) : null}
        </div>

        <div className={resultImageUrl ? "image-preview ready" : "image-preview"}>
          {resultImageUrl ? (
            <div className="image-fit-canvas">
              <img
                key={resultImageUrl}
                alt={`${formatImageModelLabel(result?.model || model)} 生成结果`}
                src={resultImageUrl}
                onError={() => {
                  setImageUrlIndex((currentIndex) =>
                    currentIndex < resultImageUrls.length - 1 ? currentIndex + 1 : currentIndex
                  );
                }}
              />
            </div>
          ) : (
            <div className="image-preview-empty">
              {busy ? <Loader2 className="spin" size={34} aria-hidden="true" /> : <ImageIcon size={34} aria-hidden="true" />}
              <strong>{busy ? "正在生成图片" : "等待生成"}</strong>
              <span>{busy ? `${selectedModelLabel} 返回结果后会自动展示。` : "左侧输入 prompt 后开始生成。"}</span>
            </div>
          )}
        </div>

        {result ? (
          <div className="image-result-strip">
            <span>{formatImageModelLabel(result.model || GPT_IMAGE_MODEL)}</span>
            <span>{result.size || "2K"}</span>
            <span>{formatAspectRatioLabel(result.aspect_ratio || "16:9")}</span>
            {isSeedreamResult(result) ? <span>{result.seedream_watermark ? "带水印" : "无水印"}</span> : null}
            <span>{result.reference_images?.length ? `参考图 ${result.reference_images.length} 张` : "文生图"}</span>
            <span>
              <CheckCircle2 size={14} aria-hidden="true" />
              已完成
            </span>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function useStateWithMode(initialValue: string, mode: ImageGenerationMode) {
  const [value, setValue] = useState(initialValue);
  useEffect(() => {
    setValue(initialValue);
  }, [initialValue, mode]);
  return [value, setValue] as const;
}

function parseReferenceImages(value: string): string[] {
  const normalized: string[] = [];
  for (const item of value.split(/\n|,/)) {
    const url = item.trim();
    if (url && !normalized.includes(url)) {
      normalized.push(url);
    }
  }
  return normalized;
}

function getImageGenerationResult(task?: TaskRecord): ImageGenerationResult | null {
  if (!task?.result) {
    return null;
  }
  return task.result as ImageGenerationResult;
}

function getImageGenerationImageUrls(result: ImageGenerationResult | null): string[] {
  if (!result) {
    return [];
  }
  const urls = [result.output_url, result.image_url, result.generated_url];
  const normalized: string[] = [];
  for (const rawUrl of urls) {
    const url = String(rawUrl || "").trim();
    if (url && !normalized.includes(url)) {
      normalized.push(url);
    }
  }
  return normalized;
}

function formatImageModelLabel(model?: string) {
  if (model === SEEDREAM_MODEL) {
    return "Seedream 4.5";
  }
  return "GPT Image 2";
}

function formatAspectRatioLabel(value?: string) {
  return value === "auto" ? "自动" : value || "自动";
}

function formatImageTaskStatus(task?: TaskRecord): string {
  if (!task) {
    return "未开始";
  }
  if (task.status === "queued") {
    return "排队中";
  }
  if (task.status === "running") {
    return "生成中";
  }
  if (task.status === "completed") {
    return "已完成";
  }
  if (task.status === "failed") {
    return "生成失败";
  }
  return String(task.status);
}

function isSeedreamResult(result: ImageGenerationResult | null) {
  return result?.model === SEEDREAM_MODEL || result?.seedream_watermark != null;
}
