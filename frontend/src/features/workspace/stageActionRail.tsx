import { TaskButton } from "../../components/TaskButton";
import type { CreateStageTaskRequest, PlannedSegmentArtifact, StageTaskKind } from "../../types";
import {
  STORYBOARD_MODEL_OPTIONS,
  getStoryboardModelOption,
  getStoryboardSizeOption
} from "../projects/creatorStoryboardOptions";
import type { ImageGenerationOptions } from "./ProjectWorkspacePage";
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
  imageOptions,
  isBusy,
  mutationStage,
  onImageAspectRatioChange,
  onImageModelChange,
  onImageSizeChange,
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
  imageOptions: ImageGenerationOptions;
  isBusy: boolean;
  mutationStage?: StageTaskKind;
  onImageAspectRatioChange: (aspectRatio: string) => void;
  onImageModelChange: (model: string) => void;
  onImageSizeChange: (size: string) => void;
  onSubmit: (stage: StageTaskKind, extraPayload?: Partial<CreateStageTaskRequest>) => void;
  stageStatus?: string;
  stageBlockReason?: string;
  selectedScene?: SceneRow;
  selectedSegment?: PlannedSegmentArtifact;
}) {
  const sceneId = selectedScene?.sceneId || selectedSegment?.scene_id || "";
  const segmentId = selectedSegment?.segment_id || "";
  const disabled = !activeTaskId || isBusy || Boolean(stageBlockReason);
  const gridMode = selectedSegment?.video_mode === "grid_storyboard";
  const storyboardReady = Boolean(selectedSegment?.storyboard_ready || selectedSegment?.storyboard_grid?.url);
  const showImageOptions =
    activeSection === "角色图" ||
    activeSection === "场景母图" ||
    (activeSection === "分段视频" && gridMode);
  const selectedImageModel = getStoryboardModelOption(imageOptions.model);
  const selectedImageSize = getStoryboardSizeOption(imageOptions.model, imageOptions.size);
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
      label: completion.segmentContractsComplete
        ? "分段合同已完成"
        : completion.segmentContractsFailed
          ? completion.segmentContractsResumeReady
            ? "继续生成分段合同"
            : "重新生成分段合同"
          : "生成分段合同",
      payload: completion.segmentContractsFailed && completion.segmentContractsResumeReady
        ? { resume_from_progress: true }
        : undefined,
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
    if (gridMode) {
      actions.push({
        disabled: !segmentId || !selectedSegment?.scene_ready,
        label: storyboardReady ? "重新生成九宫格" : "生成当前九宫格",
        payload: { segment_id: segmentId, video_mode: "grid_storyboard" },
        stage: "storyboards"
      });
      if (storyboardReady) {
        actions.push({
          disabled: !segmentId,
          label: selectedSegment?.rendered_clip?.url ? "重新生成视频" : "生成当前视频",
          payload: { segment_id: segmentId },
          stage: "videos"
        });
      }
    } else {
      actions.push({
        disabled: !segmentId,
        label: selectedSegment?.rendered_clip?.url ? "重新生成视频" : "生成当前视频",
        payload: { segment_id: segmentId },
        stage: "videos"
      });
    }
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
        {showImageOptions ? (
          <div className="stage-image-options" aria-label="生图模型设置">
            <label>
              <span>模型</span>
              <select disabled={isBusy} value={imageOptions.model} onChange={(event) => onImageModelChange(event.target.value)}>
                {STORYBOARD_MODEL_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>分辨率</span>
              <select disabled={isBusy} value={imageOptions.size} onChange={(event) => onImageSizeChange(event.target.value)}>
                {selectedImageModel.sizes.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>比例</span>
              <select disabled={isBusy} value={imageOptions.aspectRatio} onChange={(event) => onImageAspectRatioChange(event.target.value)}>
                {selectedImageSize.aspectRatios.map((ratio) => (
                  <option key={ratio} value={ratio}>{ratio === "auto" ? "自动" : ratio}</option>
                ))}
              </select>
            </label>
          </div>
        ) : null}
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
