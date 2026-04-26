import assert from "node:assert/strict";

import {
  renderAssetSectionIntro,
  renderSegmentSceneBlockedNotice,
  renderSegmentTaskError,
} from "../../src/storyforge/api/static/app/render/detail_common.js";

const introHtml = renderAssetSectionIntro("审片台", "检查 <风险>", "<span>风险 1</span>");
assert.match(introHtml, /审片台/);
assert.match(introHtml, /检查 &lt;风险&gt;/);
assert.match(introHtml, /detail-chip-row/);
assert.match(introHtml, /风险 1/);

assert.equal(renderSegmentTaskError({ status: "completed" }, "视频失败"), "");
assert.match(
  renderSegmentTaskError({ status: "failed", error: "Seedance <400>" }, "视频失败"),
  /视频失败：Seedance &lt;400&gt;/,
);

assert.match(
  renderSegmentSceneBlockedNotice({
    segment: { sceneReady: false },
    characterStatus: "failed",
  }),
  /角色图生成失败/,
);
assert.match(
  renderSegmentSceneBlockedNotice({
    segment: { sceneReady: false },
    characterStatus: "stale",
  }),
  /角色图仍然对应旧文本版本/,
);
assert.match(
  renderSegmentSceneBlockedNotice({
    segment: { sceneReady: false },
    characterStatus: "running",
  }),
  /角色图正在生成/,
);
assert.match(
  renderSegmentSceneBlockedNotice({
    segment: { sceneReady: false },
    characterStatus: "idle",
  }),
  /请先生成角色图/,
);
assert.match(
  renderSegmentSceneBlockedNotice({
    segment: { sceneReady: true },
    characterStatus: "completed",
    sceneScopeLocked: true,
  }),
  /当前 scene 正在修复或生成场景母图/,
);
assert.match(
  renderSegmentSceneBlockedNotice({
    segment: { sceneReady: true },
    characterStatus: "completed",
    segmentRepairLocked: true,
  }),
  /当前片段正在智能修复/,
);
assert.match(
  renderSegmentSceneBlockedNotice({
    segment: { sceneReady: true },
    characterStatus: "completed",
    sceneTaskStatus: "queued",
  }),
  /当前片段场景图正在生成/,
);
assert.match(
  renderSegmentSceneBlockedNotice({
    segment: { sceneReady: true },
    characterStatus: "completed",
    videoTaskStatus: "running",
  }),
  /当前片段视频正在生成/,
);
assert.equal(
  renderSegmentSceneBlockedNotice({ segment: { sceneReady: true }, characterStatus: "completed" }),
  "",
);

console.log("detail_common tests passed");
