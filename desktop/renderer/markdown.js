(() => {
  'use strict';

  // Provider responses are untrusted. Only safe, presentation-oriented HTML
  // from Markdown is allowed into the sandboxed Electron renderer.
  const ALLOWED_TAGS = [
    'a', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'hr', 'li', 'ol', 'p', 'pre', 's', 'span',
    'strong', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul',
  ];
  const ALLOWED_ATTR = ['href', 'title', 'start', 'align'];

  function renderInto(element, text) {
    const answer = String(text ?? '');
    if (!window.marked?.parse || !window.DOMPurify?.sanitize) {
      element.textContent = answer;
      return;
    }
    try {
      const rendered = window.marked.parse(answer, { gfm: true, breaks: true });
      const safe = window.DOMPurify.sanitize(rendered, {
        ALLOWED_TAGS,
        ALLOWED_ATTR,
        ALLOW_ARIA_ATTR: false,
        ALLOW_DATA_ATTR: false,
      });
      element.innerHTML = safe;
    } catch {
      // Never render unsanitized HTML, even if a library fails.
      element.textContent = answer;
    }
  }

  window.editingCoachMarkdown = Object.freeze({ renderInto });
})();
