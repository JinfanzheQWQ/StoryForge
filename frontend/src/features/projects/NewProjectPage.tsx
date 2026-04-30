import { FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { queryKeys } from "../../api/queryKeys";
import { createNovelTask } from "../../api/stageTasks";
import type { StoryBrief } from "../../types";
import { createNovelRequest, initialBrief, parseCommaSeparatedList } from "./creatorDefaults";
import { CreatorPromptForm } from "./CreatorPromptForm";

export function NewProjectPage() {
  const [searchParams] = useSearchParams();
  const [brief, setBrief] = useState<StoryBrief>(() => {
    const ideaFromLanding = searchParams.get("idea")?.trim();
    if (!ideaFromLanding) {
      return initialBrief;
    }
    return {
      ...initialBrief,
      idea: ideaFromLanding
    };
  });
  const [mustIncludeText, setMustIncludeText] = useState(() => initialBrief.must_include.join("，"));
  const [styleKeywordsText, setStyleKeywordsText] = useState(() => initialBrief.style_keywords.join("，"));
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: createNovelTask,
    onSuccess: async (task) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects() });
      navigate(`/console/projects/${task.project_id}/run/${task.task_id}`);
    }
  });

  function updateBrief<K extends keyof StoryBrief>(key: K, value: StoryBrief[K]) {
    setBrief((current) => ({ ...current, [key]: value }));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(
      createNovelRequest({
        ...brief,
        must_include: parseCommaSeparatedList(mustIncludeText),
        style_keywords: parseCommaSeparatedList(styleKeywordsText)
      })
    );
  }

  return (
    <section className="creator-page creator-studio" aria-labelledby="creator-title">
      <form className="creator-console creator-product-shell" onSubmit={submit}>
        <main className="creator-product-main" aria-label="小说转视频生成器">
          <header className="creator-product-hero">
            <span>StoryForge Create</span>
            <h2 id="creator-title">小说转视频</h2>
            <p>写下故事创意，创建一个可继续制作的视频项目。</p>
          </header>

          <CreatorPromptForm
            brief={brief}
            isError={mutation.isError}
            isSubmitting={mutation.isPending}
            mustIncludeText={mustIncludeText}
            onBriefChange={updateBrief}
            onMustIncludeTextChange={setMustIncludeText}
            onStyleKeywordsTextChange={setStyleKeywordsText}
            styleKeywordsText={styleKeywordsText}
          />
        </main>
      </form>
    </section>
  );
}
