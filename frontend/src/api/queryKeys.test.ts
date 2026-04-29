import { describe, expect, it } from "vitest";
import { queryKeys } from "./queryKeys";

describe("queryKeys", () => {
  it("keeps project and task query keys stable", () => {
    expect(queryKeys.projects()).toEqual(["projects"]);
    expect(queryKeys.project("p1")).toEqual(["project", "p1"]);
    expect(queryKeys.task("t1")).toEqual(["task", "t1"]);
  });

  it("keeps artifact and story source query keys stable", () => {
    expect(queryKeys.artifacts("t1")).toEqual(["artifacts", "t1"]);
    expect(queryKeys.projectCardArtifacts("t2")).toEqual(["project-card-artifacts", "t2"]);
    expect(queryKeys.storySource("p1", "t1")).toEqual(["story-source", "p1", "t1"]);
  });
});
