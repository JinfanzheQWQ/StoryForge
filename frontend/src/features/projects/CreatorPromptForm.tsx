import { ArrowRight } from "lucide-react";
import { TaskButton } from "../../components/TaskButton";
import type { StoryBrief } from "../../types";
import { CreatorAdvancedSettings } from "./CreatorAdvancedSettings";

type CreatorPromptFormProps = {
  brief: StoryBrief;
  isError: boolean;
  isSubmitting: boolean;
  onBriefChange: <K extends keyof StoryBrief>(key: K, value: StoryBrief[K]) => void;
  onListFieldChange: (key: "must_include" | "style_keywords", value: string) => void;
};

export function CreatorPromptForm({ brief, isError, isSubmitting, onBriefChange, onListFieldChange }: CreatorPromptFormProps) {
  return (
    <section className="creator-composer" aria-label="创作输入">
      <label className="composer-title-field">
        <span>项目名称</span>
        <input value={brief.title_hint} onChange={(event) => onBriefChange("title_hint", event.target.value)} required />
      </label>

      <label className="composer-prompt-field">
        <span>小说创意</span>
        <textarea
          value={brief.idea}
          onChange={(event) => onBriefChange("idea", event.target.value)}
          placeholder="例如：傍晚校园花园里，一个内向男生误以为自己叫住了喜欢的女生，最后鼓起勇气表白。"
          required
        />
      </label>

      <div className="composer-toolbar">
        <div className="composer-inline-fields">
          <label>
            <span>类型</span>
            <input value={brief.genre} onChange={(event) => onBriefChange("genre", event.target.value)} />
          </label>
          <label>
            <span>气质</span>
            <input value={brief.tone} onChange={(event) => onBriefChange("tone", event.target.value)} />
          </label>
          <label>
            <span>章节</span>
            <input min={1} type="number" value={brief.chapter_count} onChange={(event) => onBriefChange("chapter_count", Number(event.target.value))} />
          </label>
        </div>

        <TaskButton loading={isSubmitting} type="submit">
          开始生成 <ArrowRight size={17} aria-hidden="true" />
        </TaskButton>
      </div>

      <CreatorAdvancedSettings brief={brief} onBriefChange={onBriefChange} onListFieldChange={onListFieldChange} />

      {isError ? <div className="error-callout">创建失败，请检查后端 API 和数据库连接。</div> : null}
    </section>
  );
}
