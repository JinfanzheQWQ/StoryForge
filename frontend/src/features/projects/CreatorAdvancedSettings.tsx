import type { StoryBrief } from "../../types";

type CreatorAdvancedSettingsProps = {
  brief: StoryBrief;
  onBriefChange: <K extends keyof StoryBrief>(key: K, value: StoryBrief[K]) => void;
  onListFieldChange: (key: "must_include" | "style_keywords", value: string) => void;
};

export function CreatorAdvancedSettings({ brief, onBriefChange, onListFieldChange }: CreatorAdvancedSettingsProps) {
  return (
    <details className="composer-advanced">
      <summary>高级设置</summary>
      <div className="composer-advanced-grid">
        <label>
          <span>观众</span>
          <input value={brief.target_audience} onChange={(event) => onBriefChange("target_audience", event.target.value)} />
        </label>
        <label>
          <span>目标字数</span>
          <input
            min={500}
            step={100}
            type="number"
            value={brief.total_word_target}
            onChange={(event) => onBriefChange("total_word_target", Number(event.target.value))}
          />
        </label>
        <label>
          <span>必须出现</span>
          <input value={brief.must_include.join("，")} onChange={(event) => onListFieldChange("must_include", event.target.value)} />
        </label>
        <label>
          <span>风格关键词</span>
          <input value={brief.style_keywords.join("，")} onChange={(event) => onListFieldChange("style_keywords", event.target.value)} />
        </label>
      </div>
    </details>
  );
}
