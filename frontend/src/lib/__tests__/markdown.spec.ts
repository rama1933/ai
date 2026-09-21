import { describe, expect, it } from 'vitest'

import { renderMarkdown } from '../markdown'

describe('renderMarkdown', () => {
  it('keeps hljs-* classes on fenced code through sanitising', () => {
    // The allow-list must permit class on code/span, or every highlight is
    // stripped -- proven here, not by eye.
    const html = renderMarkdown('```sql\nSELECT * FROM documents;\n```')

    expect(html).toContain('code-block')
    expect(html).toContain('hljs-keyword')
    expect(html).toContain('language-sql')
    expect(html).toContain('SELECT')
  })

  it('drops a <script> in model output', () => {
    const html = renderMarkdown('halo <script>window.alert(1)</script> dunia')

    expect(html).not.toContain('<script')
    expect(html).not.toContain('alert(1)</')
  })

  it('wraps each block with a language label and a copy button', () => {
    const html = renderMarkdown('```python\nprint(1)\n```')

    expect(html).toContain('>python<')
    expect(html).toContain('code-copy')
  })

  it('renders an unclosed fence as plain text until it closes', () => {
    const html = renderMarkdown('kalimat biasa ```python\nprint(1)')

    expect(html).not.toContain('code-block')
  })

  it('escapes raw HTML such as an onerror-bearing img tag', () => {
    // markdown-it leaves raw HTML disabled, so the tag never becomes an element.
    const html = renderMarkdown('<img src="x" onerror="alert(1)">')

    expect(html).toContain('&lt;img')
    expect(html).not.toContain('<img')
  })
})
