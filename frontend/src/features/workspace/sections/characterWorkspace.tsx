import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { selectCharacterImageVersion } from "../../../api/characterImages";
import { updateCharacterPrompt } from "../../../api/prompts";
import { queryKeys } from "../../../api/queryKeys";
import { StatusPill } from "../../../components/StatusPill";
import { TaskButton } from "../../../components/TaskButton";
import type { CharacterArtifactItem, CreateStageTaskRequest, StageTaskKind } from "../../../types";
import { AssetPreview, StageEmpty, WorkspaceHeading } from "../workspaceCommon";
import { getCharacterName, getErrorMessage, selectCharacter } from "../workspaceModel";

export function CharacterWorkspace({
  activeTaskId,
  characters,
  isTaskBusy,
  mutationStage,
  onSubmit,
  projectId,
  selectedCharacterName,
  setSelectedCharacterName
}: {
  activeTaskId: string;
  characters: CharacterArtifactItem[];
  isTaskBusy: boolean;
  mutationStage?: StageTaskKind;
  onSubmit: (stage: StageTaskKind, extraPayload?: Partial<CreateStageTaskRequest>) => void;
  projectId?: string;
  selectedCharacterName: string;
  setSelectedCharacterName: (characterName: string) => void;
}) {
  const queryClient = useQueryClient();
  const [promptDraft, setPromptDraft] = useState("");
  const selectionMutation = useMutation({
    mutationFn: ({ characterName, version }: { characterName: string; version: "current" | "candidate" }) => {
      if (!projectId || !activeTaskId) throw new Error("缺少项目或任务信息，无法选择角色图。");
      return selectCharacterImageVersion(projectId, activeTaskId, characterName, version);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.artifacts(activeTaskId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects() });
    }
  });
  const promptMutation = useMutation({
    mutationFn: ({ characterName, prompt }: { characterName: string; prompt: string }) => {
      if (!projectId || !activeTaskId) throw new Error("缺少项目或任务信息，无法保存角色 prompt。");
      return updateCharacterPrompt(projectId, activeTaskId, characterName, prompt);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.artifacts(activeTaskId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects() });
    }
  });

  const selectedCharacter = selectCharacter(characters, selectedCharacterName) || characters[0];
  const selectedName = selectedCharacter ? getCharacterName(selectedCharacter) : "";
  const hasCandidate = Boolean(selectedCharacter?.candidate_url);
  const persistedPrompt = selectedCharacter?.prompt || "";
  const promptChanged = promptDraft.trim() !== persistedPrompt.trim();
  const promptActionDisabled = !projectId || !activeTaskId || !selectedName || !promptDraft.trim() || promptMutation.isPending || isTaskBusy;

  useEffect(() => {
    setPromptDraft(selectedCharacter?.prompt || "");
  }, [selectedCharacter?.prompt, selectedName]);

  if (!characters.length) {
    return <StageEmpty title="还没有角色图" description="生成角色图后，这里会按角色展示正式图、prompt 状态和候选图状态。" />;
  }

  function savePrompt({ regenerate }: { regenerate: boolean }) {
    const prompt = promptDraft.trim();
    if (!selectedName || !prompt || !projectId || !activeTaskId) return;
    promptMutation.mutate(
      { characterName: selectedName, prompt },
      {
        onSuccess: () => {
          if (regenerate) {
            onSubmit("characters", { character_name: selectedName });
          }
        }
      }
    );
  }

  return (
    <section className="asset-workspace character-wall" aria-label="角色定妆墙">
      <WorkspaceHeading eyebrow="Character Lookbook" title="角色定妆墙" summary="主区域只看当前角色的正式图、状态和候选图提示。" />
      <div className="asset-focus-board">
        <div className="asset-focus-media">
          <AssetPreview item={selectedCharacter} />
        </div>
        <div className="asset-focus-copy">
          <span>当前角色</span>
          <strong>{selectedName || "未选择角色"}</strong>
          <p>{selectedCharacter?.consistency_notes || selectedCharacter?.prompt || "选择一个角色后，这里展示定妆图和稳定性信息。"}</p>
          <div className="asset-focus-meta">
            <StatusPill status={selectedCharacter?.status || (selectedCharacter?.url ? "completed" : "queued")} />
            <em>{selectedCharacter?.candidate_url ? "有新候选图待确认" : "正式图可用"}</em>
          </div>
        </div>
      </div>

      <section className="character-prompt-panel" aria-label="角色 prompt 编辑">
        <div className="character-prompt-heading">
          <div>
            <p className="eyebrow">Prompt</p>
            <h4>调整 {selectedName || "当前角色"} 的定妆 prompt</h4>
          </div>
          <span className={promptChanged ? "status-pill status-edited" : "status-pill status-synced"}>
            {promptChanged ? "有修改" : "已同步"}
          </span>
        </div>
        <textarea
          aria-label={`${selectedName} 角色定妆 prompt`}
          disabled={promptMutation.isPending || isTaskBusy}
          placeholder="写清楚角色姓名、年龄感、外观、发型、服装和三视图约束。"
          value={promptDraft}
          onChange={(event) => setPromptDraft(event.target.value)}
        />
        <div className="character-prompt-actions">
          <TaskButton disabled={promptActionDisabled || !promptChanged} loading={promptMutation.isPending} type="button" onClick={() => savePrompt({ regenerate: false })}>
            保存 Prompt
          </TaskButton>
          <TaskButton
            disabled={promptActionDisabled}
            loading={promptMutation.isPending || (isTaskBusy && mutationStage === "characters")}
            type="button"
            onClick={() => savePrompt({ regenerate: true })}
          >
            保存并重做该角色
          </TaskButton>
        </div>
        {promptMutation.isError ? <div className="error-callout">{getErrorMessage(promptMutation.error)}</div> : null}
      </section>

      {hasCandidate ? (
        <section className="candidate-choice-panel" aria-label="角色候选图选择">
          <div className="candidate-choice-copy">
            <p className="eyebrow">Candidate Review</p>
            <h4>{selectedName} 的新候选图</h4>
            <span>对比当前正式图和新候选图，确认后只保留一个版本进入后续视频生成。</span>
          </div>
          <div className="candidate-choice-media">
            <figure>
              <AssetPreview item={selectedCharacter} />
              <figcaption>当前正式图</figcaption>
            </figure>
            <figure>
              <AssetPreview item={{ name: `${selectedName}-candidate`, url: selectedCharacter?.candidate_url || "" }} />
              <figcaption>新候选图</figcaption>
            </figure>
          </div>
          <div className="candidate-choice-actions">
            <TaskButton
              disabled={!projectId || !activeTaskId}
              loading={selectionMutation.isPending && selectionMutation.variables?.version === "candidate"}
              type="button"
              onClick={() => selectionMutation.mutate({ characterName: selectedName, version: "candidate" })}
            >
              使用候选图
            </TaskButton>
            <TaskButton
              disabled={!projectId || !activeTaskId}
              loading={selectionMutation.isPending && selectionMutation.variables?.version === "current"}
              type="button"
              onClick={() => selectionMutation.mutate({ characterName: selectedName, version: "current" })}
            >
              保留当前图
            </TaskButton>
          </div>
          {selectionMutation.isError ? <div className="error-callout">{getErrorMessage(selectionMutation.error)}</div> : null}
        </section>
      ) : null}

      <div className="asset-ledger">
        {characters.map((item, index) => {
          const characterName = getCharacterName(item);
          const selected = characterName === (selectedCharacterName || selectedName);
          return (
            <button
              aria-pressed={selected}
              className={selected ? "asset-ledger-row selected" : "asset-ledger-row"}
              key={`${item.character_id || item.name}-${index}`}
              type="button"
              onClick={() => setSelectedCharacterName(characterName)}
            >
              <AssetPreview item={item} />
              <div>
                <strong>{characterName}</strong>
                <span>{item.prompt || item.path || "暂无 prompt 摘要"}</span>
              </div>
              <StatusPill status={item.status || (item.url ? "completed" : "queued")} />
              <em>{item.candidate_url ? "有新候选图" : "正式图"}</em>
            </button>
          );
        })}
      </div>
    </section>
  );
}
