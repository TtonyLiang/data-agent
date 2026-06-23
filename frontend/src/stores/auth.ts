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

export const adminOnlyPaths = new Set([
  '/agent',
  '/model-config',
  '/datasource',
  '/knowledge',
  '/system-parameter',
  '/prompt-config',
  '/users',
])

export function isLoggedIn() {
  return Boolean(authState.token && authState.currentUser)
}

export function isAdmin() {
  return authState.currentUser?.role === 'admin'
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
