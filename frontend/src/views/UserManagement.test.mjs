import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./UserManagement.vue', import.meta.url), 'utf8')

assert.ok(source.includes('const passwordSaving = ref(false)'), 'password reset should expose a submitting state')
assert.ok(source.includes('请输入新密码'), 'password reset should warn when the password is empty')
assert.ok(source.includes('新密码至少需要8个字符'), 'password reset should validate the minimum password length')
assert.ok(source.includes('不能超过72字节'), 'password reset should validate bcrypt byte length')
assert.ok(source.includes('密码重置失败'), 'password reset should show API failures')
assert.ok(source.includes(':loading="passwordSaving"'), 'password reset should show a loading state while submitting')

assert.ok(
  source.includes('兼容验证账号') &&
    source.includes('兼容验证客户端权限') &&
    source.includes('兼容验证客户端访问权限') &&
    source.includes('业务人员和技术人员直接按业务领域使用平台') &&
    source.includes('验证客户端不拥有企业模型'),
  'user permissions should describe only legacy Agent grants as compatibility access',
)

assert.ok(
  source.includes('user-management-table') &&
    source.includes('table-layout="fixed"') &&
    source.includes('scrollbar-always-on'),
  'User management table should keep a stable fixed layout and scrollbar gutter',
)

assert.ok(
  source.includes('class-name="username-column"') &&
    source.includes('show-overflow-tooltip') &&
    source.includes('word-break: keep-all') &&
    source.includes('white-space: nowrap'),
  'Usernames should not break in the middle and should remain inspectable',
)

assert.ok(
  source.includes('width="180"') &&
    source.includes('class-name="role-column"') &&
    source.includes('class="role-tag"') &&
    source.includes('max-width: none'),
  'Role tags should remain complete without clipping or overflow',
)

assert.ok(
  source.includes('label="最近登录" width="175"') &&
    source.includes('label="操作"') &&
    source.includes('width="360"'),
  'User management should preserve complete login timestamps without an oversized fixed action column',
)

assert.ok(
  source.includes('@click="openEdit(row)"') &&
    source.includes('@click="openAgentPermission(row)"') &&
    source.includes('@click="openResetPassword(row)"') &&
    source.includes('@click="toggleStatus(row)"'),
  'User management action events should remain unchanged',
)
