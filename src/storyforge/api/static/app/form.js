import { elements } from "./dom.js";

function populateLlmOptions(options, selectedProvider) {
  if (!elements.llmProviderSelect || !Array.isArray(options) || options.length === 0) {
    return;
  }

  const provider = selectedProvider || elements.llmProviderSelect.value;
  elements.llmProviderSelect.replaceChildren();

  options.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.provider;
    option.textContent = item.label;
    option.dataset.defaultModel = item.model;
    if (item.provider === provider) {
      option.selected = true;
    }
    elements.llmProviderSelect.append(option);
  });
}

export function fillInput(name, value) {
  const field = elements.form.elements.namedItem(name);
  if (field) {
    if (field instanceof HTMLInputElement && field.type === "checkbox") {
      field.checked = Boolean(value);
      return;
    }
    field.value = value;
  }
}

function resolveProjectTaskOption(detail, key, fallback) {
  const tasks = Array.isArray(detail?.tasks)
    ? [...detail.tasks].sort((left, right) => String(left.created_at || "").localeCompare(String(right.created_at || "")))
    : [];
  for (let index = tasks.length - 1; index >= 0; index -= 1) {
    const task = tasks[index];
    if (task?.result && Object.prototype.hasOwnProperty.call(task.result, key)) {
      return Boolean(task.result[key]);
    }
    if (task?.payload && Object.prototype.hasOwnProperty.call(task.payload, key)) {
      return Boolean(task.payload[key]);
    }
  }
  return fallback;
}

export function applyBootstrapToForm(payload) {
  populateLlmOptions(payload.available_llm_options, payload.llm_provider);
  fillInput("title_hint", payload.default_brief.title_hint);
  fillInput("idea", payload.default_brief.idea);
  fillInput("genre", payload.default_brief.genre);
  fillInput("tone", payload.default_brief.tone);
  fillInput("target_audience", payload.default_brief.target_audience);
  fillInput("chapter_count", payload.default_brief.chapter_count);
  fillInput("total_word_target", payload.default_brief.total_word_target);
  fillInput("must_include", payload.default_brief.must_include.join(", "));
  fillInput("style_keywords", payload.default_brief.style_keywords.join(", "));
  fillInput("llm_provider", payload.llm_provider);
  fillInput("llm_model", payload.llm_model);
  fillInput("continuity_review_mode", payload.continuity_review_mode || "auto");
  fillInput("seedream_watermark", payload.seedream_watermark);
  fillInput("seedance_watermark", payload.seedance_watermark);
  setSubmitStatus(
    `${payload.llm_provider} / ${payload.llm_model} 已就绪。`,
  );
}

export function syncLlmModelPreset() {
  if (!elements.llmProviderSelect || !elements.llmModelInput) {
    return;
  }
  const preset = elements.llmProviderSelect.selectedOptions[0]?.dataset.defaultModel;
  if (!preset) {
    return;
  }
  elements.llmModelInput.value = preset;
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
  if (window.storyforgeBootstrap) {
    fillInput("llm_provider", window.storyforgeBootstrap.llm_provider);
    fillInput("llm_model", window.storyforgeBootstrap.llm_model);
    fillInput("continuity_review_mode", window.storyforgeBootstrap.continuity_review_mode || "auto");
    fillInput("seedream_watermark", window.storyforgeBootstrap.seedream_watermark);
    fillInput("seedance_watermark", window.storyforgeBootstrap.seedance_watermark);
  } else {
    syncLlmModelPreset();
    fillInput("continuity_review_mode", "auto");
    fillInput("seedream_watermark", false);
    fillInput("seedance_watermark", false);
  }
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
      use_llm: true,
      llm_provider: elements.form.elements.llm_provider.value.trim(),
      llm_model: elements.form.elements.llm_model.value.trim(),
      continuity_review_mode: elements.form.elements.continuity_review_mode.value.trim(),
      seedream_watermark: Boolean(elements.form.elements.seedream_watermark.checked),
      seedance_watermark: Boolean(elements.form.elements.seedance_watermark.checked),
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
  fillInput(
    "continuity_review_mode",
    detail.tasks?.[0]?.result?.continuity_review_mode
      || detail.tasks?.[0]?.payload?.continuity_review_mode
      || window.storyforgeBootstrap?.continuity_review_mode
      || "auto",
  );
  fillInput(
    "seedream_watermark",
    resolveProjectTaskOption(detail, "seedream_watermark", Boolean(window.storyforgeBootstrap?.seedream_watermark)),
  );
  fillInput(
    "seedance_watermark",
    resolveProjectTaskOption(detail, "seedance_watermark", Boolean(window.storyforgeBootstrap?.seedance_watermark)),
  );
  setProjectBinding(detail.project_id, detail.story_title || detail.title_hint);
}

export function setSubmitStatus(message) {
  elements.submitStatus.textContent = message;
}

export function setSubmitPending(isPending) {
  elements.submitButton.disabled = isPending;
}
