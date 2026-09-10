import { reactive } from 'vue'
import {
  clearAccessToken,
  fetchCurrentUser,
  getAccessToken,
  loginUser,
  logoutUser,
  registerUser,
  type CurrentUser,
} from '../api'

export const authState = reactive({
  token: getAccessToken(),
  currentUser: null as CurrentUser | null,
  initialized: false,
})

export const adminOnlyPaths = new Set<string>()

export const technicalOnlyPaths = new Set([
  '/agent',
  '/model-config',
  '/datasource',
  '/prompt-config',
  '/system-parameter',
])

export function isLoggedIn() {
  return Boolean(authState.token && authState.currentUser)
}

export function isAdmin() {
  return authState.currentUser?.role === 'admin'
}

export function hasCapability(capability: string) {
  return Boolean(authState.currentUser?.capabilities?.includes(capability))
}

export function isBusinessUser() {
  return authState.currentUser?.role === 'business'
}

export function isTechnicalUser() {
  return authState.currentUser?.role === 'technical' || isAdmin()
}

export function canEditModel() {
  return hasCapability('model_edit') || isAdmin()
}

export function canManageData() {
  return hasCapability('data_source_manage') || isAdmin()
}

export function canPublishModel() {
  return hasCapability('model_publish') || isAdmin()
}

export async function initAuth() {
  authState.token = getAccessToken()
  if (!authState.token) {
    authState.currentUser = null
    authState.initialized = true
    return null
  }
  try {
    authState.currentUser = await fetchCurrentUser()
    return authState.currentUser
  } catch {
    clearAccessToken()
    authState.token = ''
    authState.currentUser = null
    return null
  } finally {
    authState.initialized = true
  }
}

export async function login(username: string, password: string) {
  const result = await loginUser({ username, password })
  authState.token = result.access_token
  authState.currentUser = result.user
  authState.initialized = true
  return result.user
}

export async function register(username: string, password: string, displayName?: string) {
  return registerUser({ username, password, display_name: displayName })
}

export async function logout() {
  await logoutUser()
  authState.token = ''
  authState.currentUser = null
  authState.initialized = true
}
