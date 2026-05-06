import type { StoryBrief } from "../../types";
import {
  STORYBOARD_MODEL_OPTIONS,
  getStoryboardModelOption,
  getStoryboardSizeOption,
  resolveStoryboardSelection
} from "./creatorStoryboardOptions";

type CreatorProjectSettingsProps = {
  brief: StoryBrief;
  mustIncludeText: string;
  onBriefChange: <K extends keyof StoryBrief>(key: K, value: StoryBrief[K]) => void;
  onMustIncludeTextChange: (value: string) => void;
  onStyleKeywordsTextChange: (value: string) => void;
  styleKeywordsText: string;
};

export function CreatorProjectSettings({
  brief,
  mustIncludeText,
  onBriefChange,
  onMustIncludeTextChange,
  onStyleKeywordsTextChange,
  styleKeywordsText
}: CreatorProjectSettingsProps) {
  const selectedImageModel = getStoryboardModelOption(brief.image_model);
  const selectedImageSize = getStoryboardSizeOption(brief.image_model, brief.image_size);

  function updateImageModel(model: string) {
    const resolved = resolveStoryboardSelection({
      aspectRatio: brief.image_aspect_ratio,
      model,
      size: brief.image_size
    });
    onBriefChange("image_model", resolved.model);
    onBriefChange("image_size", resolved.size);
    onBriefChange("image_aspect_ratio", resolved.aspectRatio);
    onBriefChange("storyboard_image_model", resolved.model);
    onBriefChange("storyboard_size", resolved.size);
    onBriefChange("storyboard_aspect_ratio", resolved.aspectRatio);
  }

  function updateImageSize(size: string) {
    const resolved = resolveStoryboardSelection({
      aspectRatio: brief.image_aspect_ratio,
      model: brief.image_model,
      size
    });
    onBriefChange("image_size", resolved.size);
    onBriefChange("image_aspect_ratio", resolved.aspectRatio);
    onBriefChange("storyboard_size", resolved.size);
    onBriefChange("storyboard_aspect_ratio", resolved.aspectRatio);
  }

  function updateImageAspectRatio(aspectRatio: string) {
    onBriefChange("image_aspect_ratio", aspectRatio);
    onBriefChange("storyboard_aspect_ratio", aspectRatio);
  }

  return (
    <section className="composer-settings" aria-label="项目设定">
      <div className="composer-settings-head">
        <span>项目设定</span>
        <p>这些字段会直接影响小说、角色和视频风格，创建前必须确认。</p>
      </div>
      <div className="composer-settings-grid">
        <label>
          <span>视频模式</span>
          <select
            value={brief.video_mode}
            onChange={(event) => onBriefChange("video_mode", event.target.value as StoryBrief["video_mode"])}
          >
            <option value="grid_storyboard">九宫格分镜</option>
            <option value="direct_motion">直接运动描述</option>
          </select>
        </label>
        <label>
          <span>生图模型</span>
          <select value={brief.image_model} onChange={(event) => updateImageModel(event.target.value)}>
            {STORYBOARD_MODEL_OPTIONS.map((option) => (
              <option value={option.value} key={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label>
          <span>生图分辨率</span>
          <select value={brief.image_size} onChange={(event) => updateImageSize(event.target.value)}>
            {selectedImageModel.sizes.map((option) => (
              <option value={option.value} key={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label>
          <span>生图比例</span>
          <select value={brief.image_aspect_ratio} onChange={(event) => updateImageAspectRatio(event.target.value)}>
            {selectedImageSize.aspectRatios.map((ratio) => (
              <option value={ratio} key={ratio}>{ratio === "auto" ? "自动" : ratio}</option>
            ))}
          </select>
        </label>
        <label>
          <span>观众</span>
          <input value={brief.target_audience} onChange={(event) => onBriefChange("target_audience", event.target.value)} required />
        </label>
        <label>
          <span>目标字数</span>
          <input
            min={500}
            step={100}
            type="number"
            value={brief.total_word_target}
            onChange={(event) => onBriefChange("total_word_target", Number(event.target.value))}
            required
          />
        </label>
        <label>
          <span>必须出现</span>
          <input
            value={mustIncludeText}
            onChange={(event) => onMustIncludeTextChange(event.target.value)}
            placeholder="傍晚花园，误以为被叫，最终表白"
            required
          />
        </label>
        <label>
          <span>风格关键词</span>
          <input
            value={styleKeywordsText}
            onChange={(event) => onStyleKeywordsTextChange(event.target.value)}
            placeholder="大学，青春，小清新，电影感"
            required
          />
        </label>
      </div>
    </section>
  );
}
