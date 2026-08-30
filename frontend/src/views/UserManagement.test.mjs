import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./UserManagement.vue', import.meta.url), 'utf8')

assert.ok(source.includes('const passwordSaving = ref(false)'), 'password reset should expose a submitting state')
assert.ok(source.includes('请输入新密码'), 'password reset should warn when the password is empty')
assert.ok(source.includes('新密码至少需要8个字符'), 'password reset should validate the minimum password length')
assert.ok(source.includes('不能超过72字节'), 'password reset should validate bcrypt byte length')
assert.ok(source.includes('密码重置失败'), 'password reset should show API failures')
assert.ok(source.includes(':loading="passwordSaving"'), 'password reset should show a loading state while submitting')
