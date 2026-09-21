import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const FRONTEND_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const TAILWIND_BIN = join(FRONTEND_ROOT, 'node_modules', '.bin', 'tailwindcss')

/**
 * The shadcn-vue colour aliases declared in `tailwind.config.js`, each paired
 * with one utility class that can only exist if its key resolves. SP1-SP3 build
 * their pages on these names, and a typo in a key is silent: Tailwind emits no
 * rule, the class is dead, and nothing at build time complains. So the list is
 * the contract, and it is asserted against the real Tailwind build rather than
 * against the config object -- a key that is present but misspelled in a way the
 * resolver rejects would still pass a keys-only check.
 *
 * All 17 are covered. `primary.DEFAULT` and `primary.fg` are excluded: they
 * predate SP0 and are exercised by every component that renders today.
 */
const ALIASES = {
  background: 'bg-background',
  foreground: 'text-foreground',
  card: 'bg-card',
  'card.foreground': 'text-card-foreground',
  popover: 'bg-popover',
  'popover.foreground': 'text-popover-foreground',
  secondary: 'bg-secondary',
  'secondary.foreground': 'text-secondary-foreground',
  muted: 'bg-muted',
  'muted.foreground': 'text-muted-foreground',
  accent: 'bg-accent',
  'accent.foreground': 'text-accent-foreground',
  destructive: 'bg-destructive',
  'destructive.foreground': 'text-destructive-foreground',
  input: 'border-input',
  ring: 'ring-ring',
  'primary.foreground': 'text-primary-foreground',
} as const

const EXPECTED_ALIAS_COUNT = 17

describe('tailwind alias contract', () => {
  it(`emits a rule for all ${EXPECTED_ALIAS_COUNT} shadcn colour aliases`, () => {
    const work = mkdtempSync(join(tmpdir(), 'tailwind-alias-'))
    const probe = join(work, 'probe.html')
    const output = join(work, 'probe.css')

    const classes = Object.values(ALIASES)
    writeFileSync(probe, `<div class="${classes.join(' ')}"></div>`)

    execFileSync(
      TAILWIND_BIN,
      ['-c', 'tailwind.config.js', '-i', 'src/style.css', '--content', probe, '-o', output],
      { cwd: FRONTEND_ROOT, stdio: 'pipe' },
    )

    const css = readFileSync(output, 'utf8')

    const missing = Object.entries(ALIASES)
      .filter(([, utility]) => !new RegExp(`\\.${utility}(?=[\\s,{:])`).test(css))
      .map(([key]) => key)
    expect(missing).toEqual([])

    // Every alias must resolve to its own rule. A key that silently collapses
    // into another (or into nothing) drops this count without failing above.
    const emitted = css.match(/^\.(?:bg|text|border|ring)-[a-z-]+/gm) ?? []
    expect(emitted).toHaveLength(EXPECTED_ALIAS_COUNT)
  })
})
