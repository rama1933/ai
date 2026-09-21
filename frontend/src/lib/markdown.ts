import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'
import json from 'highlight.js/lib/languages/json'
import sql from 'highlight.js/lib/languages/sql'
import python from 'highlight.js/lib/languages/python'
import bash from 'highlight.js/lib/languages/bash'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'

// Core build + explicit registration only: the barrel import pulls ~190
// languages into the bundle for a local assistant that emits a handful.
hljs.registerLanguage('json', json)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('python', python)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('xml', xml)

const md = new MarkdownIt({
  linkify: true,
  breaks: true,
  highlight(code, language) {
    const lang = language && hljs.getLanguage(language) ? language : undefined
    if (lang) {
      try {
        return hljs.highlight(code, { language: lang }).value
      } catch {
        // fall through to the escaped plain block
      }
    }
    return '' // empty result makes markdown-it escape the code itself
  },
})

/**
 * Wrap each fenced block in a figure with a language label and a copy button.
 * Runs at render time so every consumer shares the same toolbar markup; the
 * button is wired by delegation in the component, v-html cannot bind handlers.
 */
function decorateCodeBlocks(html: string): string {
  return html.replace(
    /<pre><code( class="([^"]*)")?>([\s\S]*?)<\/code><\/pre>/g,
    (_match, _attr: string | undefined, classes: string | undefined, code: string) => {
      const classList = classes ?? ''
      const language = /language-([\w-]+)/.exec(classList)?.[1]
      const keptClasses = classList.replace(/\bhljs\b/g, '').trim()
      const codeClasses = `hljs${keptClasses ? ` ${keptClasses}` : ''}`
      return (
        `<div class="code-block">` +
        `<div class="code-block-bar"><span>${language ?? 'kode'}</span>` +
        `<button type="button" class="code-copy" aria-label="Salin kode">Salin</button></div>` +
        `<pre><code class="${codeClasses}">${code}</code></pre>` +
        `</div>`
      )
    },
  )
}

/**
 * The one markdown renderer. Model output is untrusted HTML once rendered, so
 * this is the single place a sanitiser config exists: the allow-list must keep
 * `class` on code/span or every highlight is stripped.
 */
export function renderMarkdown(source: string): string {
  const rendered = md.render(source ?? '')
  const decorated = decorateCodeBlocks(rendered)
  return DOMPurify.sanitize(decorated, {
    ALLOWED_TAGS: [
      'div', 'span', 'p', 'br', 'strong', 'em', 's', 'code', 'pre', 'blockquote',
      'ul', 'ol', 'li', 'a', 'img', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr',
      'table', 'thead', 'tbody', 'tr', 'th', 'td', 'button',
    ],
    ALLOWED_ATTR: ['class', 'href', 'target', 'rel', 'src', 'alt', 'title', 'type', 'aria-label'],
  })
}
