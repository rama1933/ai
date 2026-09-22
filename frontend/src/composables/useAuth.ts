import axios from 'axios'
import { computed, ref } from 'vue'

import { api, markSessionEnded, ROLE_KEY, TOKEN_KEY, USERNAME_KEY } from '../services/api'
import { useSessions } from './useSessions'

const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
const role = ref<string | null>(localStorage.getItem(ROLE_KEY))
const username = ref<string | null>(localStorage.getItem(USERNAME_KEY))

export function useAuth() {
  const isAuthenticated = computed(() => token.value !== null)

  // The parameter is named `name`, not `username`: a `username` parameter would shadow the
  // module-level `username` ref above, so the assignment below would write to the string.
  // `register` stores the username verbatim and `login` matches it with an exact
  // filter_by(username=...), so this value is the same one `/auth/me` would return.
  async function login(name: string, password: string): Promise<void> {
    const result = await api.login(name, password)
    token.value = result.token
    role.value = result.role
    username.value = name
    localStorage.setItem(TOKEN_KEY, result.token)
    localStorage.setItem(ROLE_KEY, result.role)
    localStorage.setItem(USERNAME_KEY, name)
  }

  function logout(): void {
    token.value = null
    role.value = null
    username.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(ROLE_KEY)
    localStorage.removeItem(USERNAME_KEY)
    // The active conversation belongs to the account, not the browser: a stale
    // id here would 404 the next account's first message with "unknown session".
    useSessions().forget()
  }

  async function fetchMe(): Promise<void> {
    if (!token.value) return
    try {
      const me = await api.fetchMe()
      username.value = me.username
      role.value = me.role
      localStorage.setItem(USERNAME_KEY, me.username)
      localStorage.setItem(ROLE_KEY, me.role)
    } catch (error) {
      // Sign out only when the server actually rejected the token. A network
      // failure or a 500 leaves the token valid, and the axios interceptor
      // deliberately defers /auth/* 401s to this function (api.ts:51).
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        // The cold-start path: a tab opened the morning after the account was
        // deactivated never sees a 401 from any other call, so the note has to be
        // written here too or the login form has nothing to explain.
        markSessionEnded()
        logout()
      }
    }
  }

  return { token, role, username, isAuthenticated, login, logout, fetchMe }
}
