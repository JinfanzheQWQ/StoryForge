import { elements } from "./dom.js";

export function fillInput(name, value) {
  const field = elements.form.elements.namedItem(name);
  if (field) {
    field.value = value;
  }
}

export function applyBootstrapToForm(payload) {
  fillInput("title_hint", payload.default_brief.title_hint);
  fillInput("idea", payload.default_brief.idea);
  fillInput("genre", payload.default_brief.genre);
  fillInput("tone", payload.default_brief.tone);
  fillInput("target_audience", payload.default_brief.target_audience);
  fillInput("chapter_count", payload.default_brief.chapter_count);
  fillInput("total_word_target", payload.default_brief.total_word_target);
  fillInput("must_include", payload.default_brief.must_include.join(", "));
  fillInput("style_keywords", payload.default_brief.style_keywords.join(", "));
  elements.form.elements.use_llm.checked = payload.use_llm;
}

export function parseCommaSeparated(value) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function setProjectBinding(projectId, title) {
  elements.form.elements.project_id.value = projectId;
  elements.bindingCard.classList.remove("hidden");
  elements.bindingText.textContent = `当前会提交到故事：${title}`;
}

export function clearProjectBinding() {
  elements.form.elements.project_id.value = "";
  elements.bindingCard.classList.add("hidden");
  elements.bindingText.textContent = "当前将新建故事";
}

export function clearForm() {
  elements.form.reset();
  fillInput("chapter_count", 1);
  fillInput("total_word_target", 1500);
  clearProjectBinding();
  setSubmitStatus("内容已清空，可以重新填写新的故事 brief。");
}

export function readProjectSubmission() {
  const projectId = elements.form.elements.project_id.value.trim();

  return {
    projectId,
    payload: {
      project_id: projectId || null,
      brief: {
        title_hint: elements.form.elements.title_hint.value.trim(),
        idea: elements.form.elements.idea.value.trim(),
        genre: elements.form.elements.genre.value.trim(),
        tone: elements.form.elements.tone.value.trim(),
        target_audience: elements.form.elements.target_audience.value.trim(),
        chapter_count: Number(elements.form.elements.chapter_count.value),
        total_word_target: Number(elements.form.elements.total_word_target.value),
        must_include: parseCommaSeparated(elements.form.elements.must_include.value),
        style_keywords: parseCommaSeparated(elements.form.elements.style_keywords.value),
      },
      use_llm: elements.form.elements.use_llm.checked,
    },
  };
}

export function applyProjectToForm(detail) {
  fillInput("title_hint", detail.brief.title_hint);
  fillInput("idea", detail.brief.idea);
  fillInput("genre", detail.brief.genre);
  fillInput("tone", detail.brief.tone);
  fillInput("target_audience", detail.brief.target_audience);
  fillInput("chapter_count", detail.brief.chapter_count);
  fillInput("total_word_target", detail.brief.total_word_target);
  fillInput("must_include", detail.brief.must_include.join(", "));
  fillInput("style_keywords", detail.brief.style_keywords.join(", "));
  setProjectBinding(detail.project_id, detail.story_title || detail.title_hint);
}

export function setSubmitStatus(message) {
  elements.submitStatus.textContent = message;
}

export function setSubmitPending(isPending) {
  elements.submitButton.disabled = isPending;
}
