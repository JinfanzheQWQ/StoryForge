import { TaskButton } from "../../components/TaskButton";
import type { CreateStageTaskRequest, PlannedSegmentArtifact, StageTaskKind } from "../../types";
import {
  getSceneMasterActionState,
  type ProductionStep,
  type SceneRow,
  type StageCompletionState
} from "./workspaceModel";

export function StageActionRail({
  activeSection,
  activeTaskId,
  activeStep,
  activeStepIndex,
  completion,
  isBusy,
  mutationStage,
  onSubmit,
  stageStatus,
  stageBlockReason,
  selectedScene,
  selectedSegment
}: {
  activeSection: string;
  activeTaskId: string;
  activeStep: ProductionStep;
  activeStepIndex: number;
  completion: StageCompletionState;
  isBusy: boolean;
  mutationStage?: StageTaskKind;
  onSubmit: (stage: StageTaskKind, extraPayload?: Partial<CreateStageTaskRequest>) => void;
  stageStatus?: string;
  stageBlockReason?: string;
  selectedScene?: SceneRow;
  selectedSegment?: PlannedSegmentArtifact;
}) {
  const sceneId = selectedScene?.sceneId || selectedSegment?.scene_id || "";
  const segmentId = selectedSegment?.segment_id || "";
  const disabled = !activeTaskId || isBusy || Boolean(stageBlockReason);
  const actions: Array<{
    disabled?: boolean;
    label: string;
    payload?: Partial<CreateStageTaskRequest>;
    stage: StageTaskKind;
    state?: "complete" | "waiting";
  }> = [];

  if (activeSection === "结构化信息") {
    actions.push({
      disabled: completion.sceneStructureComplete,
      label: completion.sceneStructureComplete ? "场景结构已完成" : "生成场景结构",
      stage: "scene-structure",
      state: completion.sceneStructureComplete ? "complete" : undefined
    });
    actions.push({
      disabled: completion.segmentContractsComplete || !completion.sceneStructureComplete,
      label: completion.segmentContractsComplete ? "分段合同已完成" : "生成分段合同",
      stage: "segment-contracts",
      state: completion.segmentContractsComplete
        ? "complete"
        : completion.sceneStructureComplete
          ? undefined
          : "waiting"
    });
  } else if (activeSection === "角色图") {
    actions.push({
      disabled: completion.charactersComplete,
      label: completion.charactersComplete ? "角色图已完成" : "生成角色图",
      stage: "characters",
      state: completion.charactersComplete ? "complete" : undefined
    });
  } else if (activeSection === "场景母图") {
    const sceneAction = getSceneMasterActionState(selectedScene, sceneId);
    actions.push({
      disabled: sceneAction.disabled,
      label: sceneAction.label,
      payload: { master_only: true, scene_id: sceneAction.sceneId },
      stage: "scenes",
      state: sceneAction.state
    });
  } else if (activeSection === "分段视频") {
    actions.push({
      disabled: !segmentId,
      label: "生成当前视频",
      payload: { segment_id: segmentId },
      stage: "videos"
    });
  } else if (activeSection === "合并视频") {
    actions.push({ label: "合并总片", payload: { merge_only: true }, stage: "videos" });
  }

  if (!actions.length) return null;

  return (
    <section className="stage-action-rail" aria-label="生产任务调度">
      <div>
        <p className="eyebrow">Step {String(activeStepIndex + 1).padStart(2, "0")}</p>
        <strong>{activeStep.title}</strong>
        <span className="stage-action-description">{activeStep.description}</span>
      </div>
      <div className="stage-action-buttons">
        {actions.map((action) => (
          <TaskButton
            className={action.state ? `task-button-${action.state}` : ""}
            disabled={disabled || action.disabled}
            key={`${action.stage}-${action.label}`}
            loading={isBusy && mutationStage === action.stage}
            onClick={() => onSubmit(action.stage, action.payload)}
            type="button"
          >
            {action.label}
          </TaskButton>
        ))}
      </div>
      {stageStatus ? <span className="stage-action-status">{stageStatus}</span> : null}
      {stageBlockReason ? <span className="stage-action-note">{stageBlockReason}</span> : null}
    </section>
  );
}
