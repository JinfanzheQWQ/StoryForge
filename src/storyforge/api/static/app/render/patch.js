const markupCache = new WeakMap();

export function renderInto(element, markup) {
  if (!element) {
    return false;
  }

  if (markupCache.get(element) === markup) {
    return false;
  }

  element.innerHTML = markup;
  markupCache.set(element, markup);
  return true;
}
