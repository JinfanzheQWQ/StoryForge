import { fetchStorySource, updateStorySource } from "./api.js";
import { state } from "./state.js";

function cloneStorySource(payload) {
  return {
    project_id: payload.project_id,
    source_task_id: payload.source_task_id,
    story_title: payload.story_title,
    story_source_revision: payload.story_source_revision,
    chapters: (payload.chapters || []).map((chapter) => ({
      number: chapter.number,
      title: chapter.title,
      summary: chapter.summary,
      markdown: chapter.markdown,
    })),
  };
}

export function buildStorySourceKey(projectId, sourceTaskId) {
  return `${projectId}:${sourceTaskId}`;
}

export function resolveStorySourceLocator(task, run = null) {
  const projectId = task?.project_id;
  const sourceTaskId =
    run?.rootTask?.task_id
    || (task?.task_type === "project.story" || task?.task_type === "project.build"
      ? task?.task_id
      : task?.result?.source_task_id || task?.payload?.source_task_id);
  const hasStorySource =
    Boolean(run?.rootTask?.result?.story_source_path)
    || Boolean(task?.result?.story_source_path);

  if (!projectId || !sourceTaskId || !hasStorySource) {
    return null;
  }

  return { projectId, sourceTaskId };
}

export function getStorySourceDraft(projectId, sourceTaskId) {
  const key = buildStorySourceKey(projectId, sourceTaskId);
  return state.storySourceDrafts.get(key) || state.storySources.get(key) || null;
}

export function getStorySourceMeta(projectId, sourceTaskId) {
  const key = buildStorySourceKey(projectId, sourceTaskId);
  return {
    dirty: state.storySourceDirtyKeys.has(key),
    loading: state.storySourceLoadingKeys.has(key),
    saving: state.storySourceSavingKeys.has(key),
    message: state.storySourceMessages.get(key) || "",
  };
}

export async function ensureStorySourceLoaded(
  projectId,
  sourceTaskId,
  { force = false } = {},
) {
  const key = buildStorySourceKey(projectId, sourceTaskId);
  if (state.storySourceLoadingKeys.has(key)) {
    return getStorySourceDraft(projectId, sourceTaskId);
  }
  if (state.storySourceDirtyKeys.has(key) && !force) {
    return getStorySourceDraft(projectId, sourceTaskId);
  }

  state.storySourceLoadingKeys.add(key);
  try {
    const payload = cloneStorySource(await fetchStorySource(projectId, sourceTaskId));
    state.storySources.set(key, payload);
    if (!state.storySourceDirtyKeys.has(key) || force || !state.storySourceDrafts.has(key)) {
      state.storySourceDrafts.set(key, cloneStorySource(payload));
    }
    if (!state.storySourceDirtyKeys.has(key)) {
      state.storySourceMessages.delete(key);
    }
    return payload;
  } catch (error) {
    state.storySourceMessages.set(key, error.message || "故事文本加载失败。");
    return null;
  } finally {
    state.storySourceLoadingKeys.delete(key);
  }
}

function mutateStorySourceDraft(projectId, sourceTaskId, mutator) {
  const current = getStorySourceDraft(projectId, sourceTaskId);
  if (!current) {
    return;
  }

  const key = buildStorySourceKey(projectId, sourceTaskId);
  const draft = cloneStorySource(current);
  mutator(draft);
  state.storySourceDrafts.set(key, draft);
  state.storySourceDirtyKeys.add(key);
  state.storySourceMessages.set(key, "文本已修改，尚未保存。");
}

export function updateStoryTitleDraft(projectId, sourceTaskId, value) {
  mutateStorySourceDraft(projectId, sourceTaskId, (draft) => {
    draft.story_title = value;
  });
}

export function updateStoryChapterDraft(projectId, sourceTaskId, chapterIndex, field, value) {
  mutateStorySourceDraft(projectId, sourceTaskId, (draft) => {
    const chapter = draft.chapters[chapterIndex];
    if (!chapter) {
      return;
    }
    chapter[field] = value;
  });
}

export async function saveStorySourceDraft(projectId, sourceTaskId) {
  const key = buildStorySourceKey(projectId, sourceTaskId);
  const draft = getStorySourceDraft(projectId, sourceTaskId);
  if (!draft) {
    throw new Error("当前没有可保存的故事文本。");
  }

  state.storySourceSavingKeys.add(key);
  state.storySourceMessages.set(key, "正在保存故事文本...");
  try {
    const saved = cloneStorySource(
      await updateStorySource(projectId, sourceTaskId, {
        story_title: draft.story_title,
        chapters: draft.chapters.map((chapter) => ({
          number: chapter.number,
          title: chapter.title,
          summary: chapter.summary,
          markdown: chapter.markdown,
        })),
      }),
    );
    state.storySources.set(key, saved);
    state.storySourceDrafts.set(key, cloneStorySource(saved));
    state.storySourceDirtyKeys.delete(key);
    state.storySourceMessages.set(key, "故事文本已保存，后续结构化信息和媒体资产需要按新文本重新生成。");
    return saved;
  } catch (error) {
    state.storySourceMessages.set(key, error.message || "故事文本保存失败。");
    throw error;
  } finally {
    state.storySourceSavingKeys.delete(key);
  }
}
