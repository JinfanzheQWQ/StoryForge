import type {
  ArtifactBundle,
  CreateStageTaskRequest,
  PlannedSegmentArtifact,
  SegmentContractProgress,
  StageTaskKind
} from "../../types";
import { CharacterWorkspace } from "./sections/characterWorkspace";
import { DeliveryWorkspace } from "./sections/deliveryWorkspace";
import { OverviewWorkspace } from "./sections/overviewWorkspace";
import { PlanningWorkspace } from "./sections/planningWorkspace";
import { ReviewWorkspace } from "./sections/reviewWorkspace";
import { SceneWorkspace } from "./sections/sceneWorkspace";
import { StoryWorkspace } from "./sections/storyWorkspace";
import type { SceneRow } from "./workspaceModel";

export { StageActionRail } from "./stageActionRail";

export function WorkspaceSection({
  activeSection,
  activeTaskId,
  artifacts,
  characterCount,
  clipCount,
  isTaskBusy,
  isSourceTaskReady,
  mutationStage,
  onSubmit,
  onTaskAccepted,
  plannedSegments,
  projectId,
  readySegments,
  sceneRows,
  sceneCount,
  segmentContractProgress,
  stageBlockReason,
  selectedCharacterName,
  selectedSceneId,
  selectedSegment,
  setSelectedCharacterName,
  setSelectedSceneId,
  setSelectedSegmentId
}: {
  activeSection: string;
  activeTaskId: string;
  artifacts?: ArtifactBundle;
  characterCount: number;
  clipCount: number;
  isTaskBusy: boolean;
  isSourceTaskReady: boolean;
  mutationStage?: StageTaskKind;
  onSubmit: (stage: StageTaskKind, extraPayload?: Partial<CreateStageTaskRequest>) => void;
  onTaskAccepted: (taskId: string) => void;
  plannedSegments: PlannedSegmentArtifact[];
  projectId?: string;
  readySegments: number;
  sceneRows: SceneRow[];
  sceneCount: number;
  segmentContractProgress?: SegmentContractProgress | null;
  stageBlockReason?: string;
  selectedCharacterName: string;
  selectedSceneId: string;
  selectedSegment?: PlannedSegmentArtifact;
  setSelectedCharacterName: (characterName: string) => void;
  setSelectedSceneId: (sceneId: string) => void;
  setSelectedSegmentId: (segmentId: string) => void;
}) {
  if (activeSection === "角色图") {
    return (
      <CharacterWorkspace
        activeTaskId={activeTaskId}
        characters={artifacts?.character_images || []}
        isTaskBusy={isTaskBusy}
        mutationStage={mutationStage}
        onSubmit={onSubmit}
        projectId={projectId}
        selectedCharacterName={selectedCharacterName}
        setSelectedCharacterName={setSelectedCharacterName}
      />
    );
  }
  if (activeSection === "场景母图") {
    return <SceneWorkspace sceneRows={sceneRows} selectedSceneId={selectedSceneId} setSelectedSceneId={setSelectedSceneId} />;
  }
  if (activeSection === "结构化信息") {
    return (
      <PlanningWorkspace
        plannedSegments={plannedSegments}
        scenes={artifacts?.scenes || []}
        segmentContractProgress={segmentContractProgress}
        setSelectedSegmentId={setSelectedSegmentId}
      />
    );
  }
  if (activeSection === "合并视频") {
    return <DeliveryWorkspace artifacts={artifacts} />;
  }
  if (activeSection === "小说") {
    return <StoryWorkspace activeTaskId={activeTaskId} isSourceTaskReady={isSourceTaskReady} isTaskBusy={isTaskBusy} projectId={projectId} />;
  }
  if (activeSection === "分段视频") {
    return (
      <ReviewWorkspace
        activeTaskId={activeTaskId}
        artifacts={artifacts}
        isTaskBusy={isTaskBusy}
        mutationStage={mutationStage}
        onSubmit={onSubmit}
        onTaskAccepted={onTaskAccepted}
        plannedSegments={plannedSegments}
        projectId={projectId}
        sceneRows={sceneRows}
        selectedSegment={selectedSegment}
        stageBlockReason={stageBlockReason}
        setSelectedSegmentId={setSelectedSegmentId}
      />
    );
  }
  return (
    <OverviewWorkspace
      characterCount={characterCount}
      clipCount={clipCount}
      plannedSegments={plannedSegments}
      readySegments={readySegments}
      sceneCount={sceneCount}
    />
  );
}
