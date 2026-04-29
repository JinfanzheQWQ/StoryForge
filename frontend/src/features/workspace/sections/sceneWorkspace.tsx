import { StatusPill } from "../../../components/StatusPill";
import { AssetPreview, StageEmpty, WorkspaceHeading } from "../workspaceCommon";
import { selectSceneRow, type SceneRow } from "../workspaceModel";

export function SceneWorkspace({
  sceneRows,
  selectedSceneId,
  setSelectedSceneId
}: {
  sceneRows: SceneRow[];
  selectedSceneId: string;
  setSelectedSceneId: (sceneId: string) => void;
}) {
  if (!sceneRows.length) {
    return <StageEmpty title="还没有场景母图" description="生成场景母图后，这里会按 scene 展示环境母图、状态和被哪些片段引用。" />;
  }
  const selectedScene = selectSceneRow(sceneRows, selectedSceneId);
  return (
    <section className="asset-workspace scene-board" aria-label="场景空间板">
      <WorkspaceHeading eyebrow="Scene Space" title="场景空间板" summary="主区域检查当前 scene 的母图、复用状态和被哪些片段引用。" />
      <div className="asset-focus-board scene-focus-board">
        <div className="asset-focus-media">
          <AssetPreview item={selectedScene?.frame} />
        </div>
        <div className="asset-focus-copy">
          <span>当前场景</span>
          <strong>{selectedScene?.sceneTitle || selectedScene?.sceneId || "未选择场景"}</strong>
          <p>{selectedScene?.summary || "选择一个 scene 后，这里展示场景母图摘要和空间锚点。"}</p>
          <div className="asset-focus-meta">
            <StatusPill status={selectedScene?.ready ? "completed" : "queued"} />
            <em>{selectedScene?.segmentCount || 0} 个片段引用</em>
          </div>
        </div>
      </div>
      <div className="asset-ledger">
        {sceneRows.map((row) => (
          <button
            aria-pressed={row.sceneId === selectedSceneId}
            className={row.sceneId === selectedSceneId ? "asset-ledger-row scene-row selected" : "asset-ledger-row scene-row"}
            key={row.sceneId}
            type="button"
            onClick={() => setSelectedSceneId(row.sceneId)}
          >
            <AssetPreview item={row.frame} />
            <div>
              <strong>{row.sceneTitle || row.sceneId}</strong>
              <span>{row.summary || "暂无场景摘要"}</span>
            </div>
            <StatusPill status={row.ready ? "completed" : "queued"} />
            <em>{row.segmentCount} 个片段引用</em>
          </button>
        ))}
      </div>
    </section>
  );
}
