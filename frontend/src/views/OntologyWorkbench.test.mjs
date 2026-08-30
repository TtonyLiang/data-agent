import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./OntologyWorkbench.vue', import.meta.url), 'utf8')
const apiSource = readFileSync(new URL('../api/index.ts', import.meta.url), 'utf8')
const routerSource = readFileSync(new URL('../router/index.ts', import.meta.url), 'utf8')
const appSource = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')

for (const tab of ['关系图谱', '对象类型', '关系类型', '动作类型', '对象实例', '决策活动']) {
  assert.ok(source.includes(tab), `Ontology workbench should include ${tab}`)
}

for (const workflow of [
  'saveObjectType',
  'saveLinkType',
  'saveActionType',
  'saveObjectInstance',
  'runAction',
  'handleValidate',
  'handlePublish',
  'handleImport',
  'handleExport',
]) {
  assert.ok(source.includes(workflow), `Ontology workbench should expose ${workflow}`)
}

assert.ok(
  source.includes('before_state') && source.includes('after_state') && source.includes('decision_context'),
  'decision activity should render context and before/after state',
)

assert.ok(
  apiSource.includes('/ontology/domains/${domainId}/publish') &&
    apiSource.includes('/ontology/domains/${domainId}/actions/${actionTypeId}/execute'),
  'frontend API should include publish and action execution contracts',
)

assert.ok(
  routerSource.includes("path: '/ontology'") && appSource.includes('index="/ontology"'),
  'ontology workbench should be routable from the primary navigation',
)

assert.ok(
  source.includes('ResizeObserver') && source.includes('graphSize'),
  'ontology graph should react to container size changes before rendering',
)

assert.ok(
  source.includes("initLayout: 'circular'"),
  'ontology graph should use a stable centered initial layout',
)
