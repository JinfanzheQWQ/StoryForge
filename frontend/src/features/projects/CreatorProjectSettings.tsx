import type { StoryBrief } from "../../types";

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
  return (
    <section className="composer-settings" aria-label="项目设定">
      <div className="composer-settings-head">
        <span>项目设定</span>
        <p>这些字段会直接影响小说、角色和视频风格，创建前必须确认。</p>
      </div>
      <div className="composer-settings-grid">
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
