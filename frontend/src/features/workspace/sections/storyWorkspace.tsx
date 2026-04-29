import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../../../api/queryKeys";
import { getStorySource, updateStorySource } from "../../../api/storySource";
import { TaskButton } from "../../../components/TaskButton";
import type { StorySourceChapter } from "../../../types";
import { StageEmpty, WorkspaceHeading } from "../workspaceCommon";
import { countTextChars, getErrorMessage, normalizeStoryChapter } from "../workspaceModel";

export function StoryWorkspace({
  activeTaskId,
  isSourceTaskReady,
  isTaskBusy,
  projectId
}: {
  activeTaskId: string;
  isSourceTaskReady: boolean;
  isTaskBusy: boolean;
  projectId?: string;
}) {
  const queryClient = useQueryClient();
  const storyQuery = useQuery({
    queryKey: queryKeys.storySource(projectId, activeTaskId),
    queryFn: () => getStorySource(projectId || "", activeTaskId),
    enabled: Boolean(projectId && activeTaskId && isSourceTaskReady)
  });
  const [draftTitle, setDraftTitle] = useState("");
  const [draftChapters, setDraftChapters] = useState<StorySourceChapter[]>([]);
  const [activeChapterIndex, setActiveChapterIndex] = useState(0);
  const [saveStatus, setSaveStatus] = useState("");
  const storySource = storyQuery.data;
  const saveMutation = useMutation({
    mutationFn: () => {
      if (!projectId || !activeTaskId) throw new Error("缺少 project_id 或 source_task_id。");
      return updateStorySource(projectId, activeTaskId, {
        story_title: draftTitle,
        chapters: draftChapters
      });
    },
    onSuccess: (response) => {
      setSaveStatus("正文已保存，后续结构和媒体产物已失效，请重新生成场景结构。");
      queryClient.setQueryData(queryKeys.storySource(projectId, activeTaskId), response);
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.artifacts(activeTaskId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.task(activeTaskId) });
    }
  });

  useEffect(() => {
    if (!storySource) return;
    setDraftTitle(storySource.story_title || "");
    setDraftChapters(
      [...storySource.chapters].sort((left, right) => left.number - right.number).map((chapter) => ({ ...chapter }))
    );
    setActiveChapterIndex(0);
    setSaveStatus("");
  }, [storySource?.source_task_id, storySource?.story_source_revision, storySource]);

  useEffect(() => {
    if (isSourceTaskReady) return;
    setDraftTitle("");
    setDraftChapters([]);
    setActiveChapterIndex(0);
    setSaveStatus("");
  }, [activeTaskId, isSourceTaskReady]);

  useEffect(() => {
    if (!draftChapters.length) {
      setActiveChapterIndex(0);
      return;
    }
    if (activeChapterIndex >= draftChapters.length) {
      setActiveChapterIndex(draftChapters.length - 1);
    }
  }, [activeChapterIndex, draftChapters.length]);

  const originalPayload = storySource
    ? JSON.stringify({
        story_title: storySource.story_title,
        chapters: storySource.chapters.map((chapter) => normalizeStoryChapter(chapter))
      })
    : "";
  const draftPayload = JSON.stringify({
    story_title: draftTitle,
    chapters: draftChapters.map((chapter) => normalizeStoryChapter(chapter))
  });
  const isDirty = Boolean(storySource) && originalPayload !== draftPayload;
  const canSave =
    Boolean(projectId && activeTaskId && storySource) &&
    isSourceTaskReady &&
    !isTaskBusy &&
    !storyQuery.isLoading &&
    !saveMutation.isPending &&
    isDirty &&
    draftChapters.length > 0 &&
    draftChapters.every((chapter) => chapter.title.trim() && chapter.markdown.trim());
  const totalChars = draftChapters.reduce((sum, chapter) => sum + countTextChars(chapter.markdown), 0);
  const activeChapter = draftChapters[activeChapterIndex];

  function updateDraftChapter(index: number, patch: Partial<StorySourceChapter>) {
    setDraftChapters((current) => current.map((chapter, chapterIndex) => (chapterIndex === index ? { ...chapter, ...patch } : chapter)));
    setSaveStatus("");
  }

  return (
    <section className="story-workspace" aria-label="小说正文">
      <WorkspaceHeading eyebrow="Writing Room" title="文稿编辑器" summary="编辑正文真源。保存后需要从场景结构开始重新生成后续产物。" />
      <div className="story-editor-shell">
        <div className="story-editor-command">
          <label htmlFor="story-title-editor">故事标题</label>
          <input
            disabled={!isSourceTaskReady || storyQuery.isLoading || saveMutation.isPending || isTaskBusy}
            id="story-title-editor"
            value={draftTitle}
            onChange={(event) => {
              setDraftTitle(event.target.value);
              setSaveStatus("");
            }}
          />
          {draftChapters.length ? (
            <div className="story-chapter-picker" aria-label="章节切换">
              {draftChapters.map((chapter, index) => (
                <button
                  className={index === activeChapterIndex ? "story-chapter-tab active" : "story-chapter-tab"}
                  key={chapter.number}
                  type="button"
                  onClick={() => setActiveChapterIndex(index)}
                >
                  CH {String(chapter.number).padStart(2, "0")}
                </button>
              ))}
            </div>
          ) : null}
          {activeChapter ? (
            <>
              <label>
                章节标题
                <input
                  disabled={saveMutation.isPending || isTaskBusy}
                  value={activeChapter.title}
                  onChange={(event) => updateDraftChapter(activeChapterIndex, { title: event.target.value })}
                />
              </label>
              <label>
                章节摘要
                <textarea
                  className="story-summary-textarea"
                  disabled={saveMutation.isPending || isTaskBusy}
                  value={activeChapter.summary}
                  onChange={(event) => updateDraftChapter(activeChapterIndex, { summary: event.target.value })}
                />
              </label>
            </>
          ) : null}
          <div className="story-editor-stats" aria-label="正文统计">
            <span>{draftChapters.length} 章</span>
            <span>{totalChars} 字符</span>
            {activeChapter ? <span>当前 {countTextChars(activeChapter.markdown)} 字符</span> : null}
            <span>{storySource?.story_source_revision || "未加载 revision"}</span>
          </div>
          <div className="story-editor-actions">
            <button
              className="ghost-button"
              disabled={!isSourceTaskReady || storyQuery.isFetching || saveMutation.isPending}
              type="button"
              onClick={() => {
                void storyQuery.refetch();
              }}
            >
              重新读取正文
            </button>
            <TaskButton disabled={!canSave} loading={saveMutation.isPending} type="button" onClick={() => saveMutation.mutate()}>
              保存正文真源
            </TaskButton>
          </div>
          {!isSourceTaskReady ? <span className="story-editor-note">小说正文生成完成后，这里会自动加载可编辑正文。</span> : null}
          {isSourceTaskReady && isTaskBusy ? <span className="story-editor-note">当前任务运行中，暂时不能保存正文。</span> : null}
          {saveStatus ? <span className="story-editor-success">{saveStatus}</span> : null}
          {storyQuery.isError ? <div className="error-callout">{getErrorMessage(storyQuery.error)}</div> : null}
          {saveMutation.isError ? <div className="error-callout">{getErrorMessage(saveMutation.error)}</div> : null}
        </div>

        <div className="story-chapter-list" aria-label="章节正文编辑">
          {!isSourceTaskReady ? (
            <StageEmpty title="小说正在生成" description="当前任务还没有可编辑正文产物。等任务完成后，文稿编辑器会自动读取正文。" />
          ) : storyQuery.isLoading ? (
            <StageEmpty title="正在读取正文" description="从 story_source.json 加载可编辑正文。" />
          ) : activeChapter ? (
            <section className="story-chapter-editor story-body-editor" aria-label={`第 ${activeChapter.number} 章正文`}>
              <div className="story-body-topline">
                <span>CH {String(activeChapter.number).padStart(2, "0")}</span>
                <strong>{activeChapter.title || "未命名章节"}</strong>
                <em>{countTextChars(activeChapter.markdown)} 字符</em>
              </div>
              <label className="story-body-field">
                正文 Markdown
                <textarea
                  className="story-body-textarea"
                  disabled={saveMutation.isPending || isTaskBusy}
                  value={activeChapter.markdown}
                  onChange={(event) => updateDraftChapter(activeChapterIndex, { markdown: event.target.value })}
                />
              </label>
            </section>
          ) : (
            <StageEmpty title="没有可编辑正文" description="当前任务还没有 story_source.json，先完成小说生成。" />
          )}
        </div>
      </div>
    </section>
  );
}
