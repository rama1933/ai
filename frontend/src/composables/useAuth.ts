import { computed, ref } from 'vue'

import { api, ROLE_KEY, TOKEN_KEY } from '../services/api'

const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
const role = ref<string | null>(localStorage.getItem(ROLE_KEY))

export function useAuth() {
  const isAuthenticated = computed(() => token.value !== null)

  async function login(username: string, password: string): Promise<void> {
    const result = await api.login(username, password)
    token.value = result.token
    role.value = result.role
    localStorage.setItem(TOKEN_KEY, result.token)
    localStorage.setItem(ROLE_KEY, result.role)
  }

  function logout(): void {
    token.value = null
    role.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(ROLE_KEY)
  }

  return { token, role, isAuthenticated, login, logout }
}
