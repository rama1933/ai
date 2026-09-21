import { computed, ref } from 'vue'

import { api } from '../services/api'

const token = ref<string | null>(localStorage.getItem(api.tokenKey))
const role = ref<string | null>(localStorage.getItem('agentic-rag-role'))

export function useAuth() {
  const isAuthenticated = computed(() => token.value !== null)

  async function login(username: string, password: string): Promise<void> {
    const result = await api.login(username, password)
    token.value = result.token
    role.value = result.role
    localStorage.setItem(api.tokenKey, result.token)
    localStorage.setItem('agentic-rag-role', result.role)
  }

  function logout(): void {
    token.value = null
    role.value = null
    localStorage.removeItem(api.tokenKey)
    localStorage.removeItem('agentic-rag-role')
  }

  return { token, role, isAuthenticated, login, logout }
}
