import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./App.vue', import.meta.url), 'utf8')
const themeSource = readFileSync(new URL('./theme.css', import.meta.url), 'utf8')
const loginSource = readFileSync(new URL('./views/LoginView.vue', import.meta.url), 'utf8')
const registerSource = readFileSync(new URL('./views/RegisterView.vue', import.meta.url), 'utf8')
const authStoreSource = readFileSync(new URL('./stores/auth.ts', import.meta.url), 'utf8')
const contrastViewSources = [
  './views/OntologyWorkbench.vue',
  './views/TwinRuntimeCenter.vue',
  './views/CapabilityPublishCenter.vue',
  './views/KnowledgeConfig.vue',
  './views/ChatView.vue',
  './views/RiskDeliveryWorkbench.vue',
].map((path) => readFileSync(new URL(path, import.meta.url), 'utf8'))

function styleSource(value) {
  return [...value.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((match) => match[1]).join('\n')
}

function tokenHex(name) {
  const match = source.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))
  assert.ok(match, `theme token should exist: --${name}`)
  return match[1]
}

function relativeLuminance(hex) {
  const value = hex.replace('#', '')
  const channels = [0, 2, 4].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16) / 255)
  const linear = channels.map((channel) => channel <= 0.04045
    ? channel / 12.92
    : ((channel + 0.055) / 1.055) ** 2.4)
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
}

function contrastRatio(foreground, background) {
  const first = relativeLuminance(foreground)
  const second = relativeLuminance(background)
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05)
}

function assertContrast(label, foreground, background, minimum) {
  const ratio = contrastRatio(foreground, background)
  assert.ok(ratio >= minimum, `${label} contrast ${ratio.toFixed(2)} should be at least ${minimum}:1`)
}

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

const modelIndex = source.indexOf('index="/enterprise-model"')
const twinIndex = source.indexOf('index="/twin-runtime"')
const capabilityIndex = source.indexOf('index="/capability-center"')
const validationIndex = source.indexOf('index="validation-apps"')
const managementIndex = source.indexOf('index="platform-management"')

assert.ok(
  modelIndex < twinIndex && twinIndex < capabilityIndex && capabilityIndex < validationIndex,
  'enterprise model, twin runtime, and capability publishing should remain one continuous foundation path',
)

assert.ok(
  source.includes('验证应用') &&
    source.includes('对话验证') &&
    source.includes('风险交付验证') &&
    source.includes('平台管理') &&
    validationIndex < managementIndex,
  'validation scenarios and administrative configuration should be grouped below the platform foundation',
)

assert.ok(
  !source.includes('@keydown.enter.space') &&
  source.includes(':tabindex="isNavigationDisabled(\'/enterprise-model\') ? -1 : 0"') &&
    source.includes('@keydown.enter.prevent.stop="activateRoute(\'/enterprise-model\')"') &&
    source.includes('@keydown.space.prevent.stop="activateRoute(\'/enterprise-model\')"') &&
    source.includes('@keydown.enter.prevent.stop="activateRoute(\'/twin-runtime\')"') &&
    source.includes('@keydown.space.prevent.stop="activateRoute(\'/twin-runtime\')"') &&
    source.includes('@keydown.enter.prevent.stop="activateRoute(\'/capability-center\')"') &&
    source.includes('@keydown.space.prevent.stop="activateRoute(\'/capability-center\')"') &&
    source.includes('@keydown.enter.prevent.stop="activateRoute(\'/risk-delivery\')"') &&
    source.includes('@keydown.space.prevent.stop="activateRoute(\'/risk-delivery\')"') &&
    source.includes('@keydown.enter.prevent.stop="openSubmenu(\'validation-apps\')"') &&
    source.includes('@keydown.space.prevent.stop="openSubmenu(\'validation-apps\')"') &&
    source.includes('@keydown.enter.prevent.stop="openSubmenu(\'platform-management\')"') &&
    source.includes('@keydown.space.prevent.stop="openSubmenu(\'platform-management\')"') &&
    source.includes('ref="mainMenu"') &&
    source.includes('mainMenu.value?.open(index)') &&
    source.includes('class="validation-menu-item"') &&
    source.includes('class="platform-menu-item"') &&
    source.includes("document.querySelector<HTMLElement>(selector)?.focus()"),
  'main and submenu navigation should be reachable and activatable with Enter or Space',
)

assert.ok(
  source.includes('aria-label="验证应用"') &&
    source.includes('aria-label="平台管理"') &&
    source.includes(':aria-current="route.path === \'/enterprise-model\' ? \'page\' : undefined"') &&
    source.includes('aria-label="用户工具"') &&
    !source.includes('通知功能暂未开放'),
  'navigation should expose landmarks and current page without a disabled placeholder control',
)

assert.ok(
  source.includes('ref="mainContent"') &&
    source.includes('id="main-content"') &&
    source.includes('role="main" tabindex="-1"') &&
    source.includes('watch(() => route.path') &&
    source.includes("mainMenu.value?.close('validation-apps')") &&
    source.includes('window.setTimeout(focusMainContent, 100)') &&
    source.includes('target?.focus()'),
  'route changes should move focus to the main content landmark',
)

for (const authSource of [loginSource, registerSource]) {
  assert.ok(
    authSource.includes(':aria-busy="loading"') && authSource.includes('name="username" autofocus'),
    'authentication pages should expose loading state and focus the username field',
  )
}

assert.ok(
  loginSource.includes("route.query.redirect || '/enterprise-model'") &&
    loginSource.includes("redirect === '/' ? '/enterprise-model' : redirect"),
  'login should open the enterprise model unless a deeper redirect was requested',
)

assert.ok(
  !loginSource.includes('/register') &&
    !loginSource.includes('注册公司内部账号'),
  'login should not offer self-service registration',
)

assert.ok(
  authStoreSource.includes('} catch {') &&
    authStoreSource.includes('authState.token = \'\'') &&
    authStoreSource.includes('authState.currentUser = null') &&
    authStoreSource.includes('authState.initialized = true'),
  'logout should clear local authentication state even when the server rejects an expired token',
)

const palette = {
  background: tokenHex('wq-bg'),
  surface: tokenHex('wq-surface'),
  text: tokenHex('wq-text'),
  muted: tokenHex('wq-muted'),
  subtle: tokenHex('wq-subtle'),
  primary: tokenHex('wq-primary'),
  primaryStrong: tokenHex('wq-primary-strong'),
  primarySoft: tokenHex('wq-primary-soft'),
  success: tokenHex('wq-success'),
  warning: tokenHex('wq-warning'),
  danger: tokenHex('wq-danger'),
  borderStrong: tokenHex('wq-border-strong'),
}

for (const [label, foreground, background] of [
  ['primary body text', palette.text, palette.surface],
  ['secondary body text', palette.muted, palette.surface],
  ['subtle body text', palette.subtle, palette.surface],
  ['subtle body text on page', palette.subtle, palette.background],
  ['primary button label', '#ffffff', palette.primary],
  ['primary-strong button label', '#ffffff', palette.primaryStrong],
  ['active navigation text', palette.primaryStrong, palette.primarySoft],
  ['success status text', palette.success, '#ecfdf3'],
  ['warning status text', palette.warning, '#fff7ed'],
  ['danger status text', palette.danger, '#fef3f2'],
  ['code text', '#31506f', '#eef3f8'],
  ['dark code text', '#d0d5dd', '#182230'],
  ['chat code text', '#e8edf5', '#101828'],
  ['authentication muted text', '#536174', '#f5f7fa'],
  ['authentication placeholder text', '#687586', '#ffffff'],
]) {
  assertContrast(label, foreground, background, 4.5)
}

for (const [label, foreground, background] of [
  ['control border on surface', palette.borderStrong, palette.surface],
  ['control border on page', palette.borderStrong, palette.background],
  ['focus outline on surface', palette.primary, palette.surface],
  ['focus outline on page', palette.primary, palette.background],
  ['blue interactive border on surface', '#7489ca', palette.surface],
  ['blue interactive border on soft surface', '#7489ca', '#f8fbff'],
]) {
  assertContrast(label, foreground, background, 3)
}

assert.ok(
  source.includes('--wq-border-strong: #7f8c9f;') &&
    themeSource.includes('box-shadow: 0 0 0 1px var(--wq-subtle) inset !important;') &&
    themeSource.includes('background-color: var(--wq-border-strong);') &&
    themeSource.includes('.el-checkbox__inner,') &&
    themeSource.includes('--el-switch-off-color: var(--wq-border-strong);') &&
    loginSource.includes('box-shadow: 0 0 0 1px #7f8c9f inset !important;') &&
    registerSource.includes('box-shadow: 0 0 0 1px #7f8c9f inset !important;'),
  'form controls and scrollbars should use AA-visible non-text boundaries',
)

assert.ok(
  contrastViewSources.every((view) => !/color:\s*#98a2b3\b/i.test(styleSource(view))) &&
    contrastViewSources.every((view) => !/color:\s*#079455\b/i.test(styleSource(view))),
  'core page CSS should not use low-contrast legacy colors for visible text',
)

const [ontologySource, twinSource, , knowledgeSource, chatSource, riskSource] = contrastViewSources
assert.ok(
  ontologySource.includes('color: var(--wq-subtle); font-size: 24px;') &&
    twinSource.includes('border: 1px solid #7489ca;') &&
    twinSource.includes('border: 1px solid var(--wq-border-strong) !important;') &&
    knowledgeSource.includes('border: 1px solid var(--wq-border-strong);') &&
    chatSource.includes('border-color: var(--wq-border-strong);') &&
    chatSource.includes('color: #067647;') &&
    riskSource.includes('.metric-item.tone-success { border-top-color: var(--wq-success); }') &&
    riskSource.includes('.audit-event-cell.event-reviewed::before { background: var(--wq-warning); }'),
  'core custom controls and non-text state indicators should retain the visual language at AA contrast',
)
