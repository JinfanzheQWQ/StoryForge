import type { ArtifactBundle } from "../../../types";
import { resolveApiAssetUrl } from "../../../api/client";
import { AssetLine, StageEmpty, WorkspaceHeading } from "../workspaceCommon";

export function DeliveryWorkspace({ artifacts }: { artifacts?: ArtifactBundle }) {
  const fullStory = artifacts?.full_story || null;
  const fullStoryUrl = resolveApiAssetUrl(fullStory?.url);
  const groups = [
    { title: "可合并片段", items: artifacts?.rendered_clips || [] },
    { title: "场景母图", items: artifacts?.scene_frames || [] },
    { title: "角色图", items: artifacts?.character_images || [] }
  ];
  return (
    <section className="library-workspace delivery-workspace" aria-label="合并交付">
      <WorkspaceHeading eyebrow="Delivery Preview" title="合并交付" summary="合并完成后这里直接展示完整成片；下方保留片段和素材清单用于核对。" />
      <section className={fullStoryUrl ? "delivery-final-film ready" : "delivery-final-film"} aria-label="完整成片">
        {fullStoryUrl ? (
          <>
            <div className="delivery-final-player">
              <video controls src={fullStoryUrl} aria-label="完整成片">
                <track kind="captions" />
              </video>
            </div>
            <div className="delivery-final-copy">
              <p className="eyebrow">Final Film</p>
              <h3>完整成片已生成</h3>
              <span>{fullStory?.name || "full_story.mp4"}</span>
              <a className="primary-link" href={fullStoryUrl} target="_blank" rel="noreferrer">
                打开完整视频
              </a>
            </div>
          </>
        ) : (
          <StageEmpty title="还没有合并总片" description="至少生成两个视频片段后，点击合并总片；完成后完整视频会显示在这里。" />
        )}
      </section>
      <div className="library-columns">
        {groups.map((group) => (
          <div className="library-column" key={group.title}>
            <h3>{group.title}</h3>
            {group.items.length ? (
              group.items.slice(0, 6).map((item, index) => <AssetLine item={item} key={`${item.name}-${index}`} />)
            ) : (
              <span>暂无产物</span>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
