import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

const patchFile = new URL("../../src/storyforge/api/static/app/render/patch.js", import.meta.url);
const patchSource = await fs.readFile(patchFile, "utf8");
const patchModuleUrl = `data:text/javascript;base64,${Buffer.from(patchSource).toString("base64")}`;
const { renderInto } = await import(patchModuleUrl);

function createElementStub() {
  let innerHTML = "";
  let writeCount = 0;

  return {
    get innerHTML() {
      return innerHTML;
    },
    set innerHTML(value) {
      innerHTML = value;
      writeCount += 1;
    },
    get writeCount() {
      return writeCount;
    },
  };
}

test("renderInto only rewrites DOM when markup changes", () => {
  const element = createElementStub();
  const firstMarkup = '<video controls src="/outputs/demo.mp4"></video>';
  const secondMarkup = '<video controls src="/outputs/demo-v2.mp4"></video>';

  assert.equal(renderInto(element, firstMarkup), true);
  assert.equal(element.innerHTML, firstMarkup);
  assert.equal(element.writeCount, 1);

  assert.equal(renderInto(element, firstMarkup), false);
  assert.equal(element.innerHTML, firstMarkup);
  assert.equal(element.writeCount, 1);

  assert.equal(renderInto(element, secondMarkup), true);
  assert.equal(element.innerHTML, secondMarkup);
  assert.equal(element.writeCount, 2);
});
