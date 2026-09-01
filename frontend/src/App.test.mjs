import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./App.vue', import.meta.url), 'utf8')

assert.ok(
  source.includes(':ellipsis="true"') &&
    source.includes('grid-template-columns: minmax(190px, 220px) minmax(0, 1fr) auto;'),
  'header navigation should use bounded grid tracks and Element Plus overflow handling',
)

assert.ok(
  source.includes('@media (max-width: 1560px)') &&
    source.includes('.header-tools .env-tag {') &&
    source.includes('display: none;') &&
    source.includes('padding-inline: 9px;'),
  'mid-size desktop headers should reclaim environment-tag space and tighten navigation',
)

assert.ok(
  source.includes('.user-pill > span:last-child {') &&
    source.includes('text-overflow: ellipsis;') &&
    source.includes('white-space: nowrap;'),
  'long user names should truncate instead of pushing into navigation',
)

assert.ok(
  source.includes('flex: 0 0 auto;') && source.includes('white-space: nowrap;'),
  'navigation labels should remain stable single-line items',
)
