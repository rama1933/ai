<script setup lang="ts">
import { computed, onMounted, watchEffect } from 'vue'

import AdminLayout from './components/admin/AdminLayout.vue'
import KnowledgeView from './components/admin/KnowledgeView.vue'
import LogsView from './components/admin/LogsView.vue'
import UsersView from './components/admin/UsersView.vue'
import ChatBox from './components/ChatBox.vue'
import LoginForm from './components/LoginForm.vue'
import { useAuth } from './composables/useAuth'
import { useView } from './composables/useView'

const { isAuthenticated, role, fetchMe } = useAuth()
const { view, isAdminView, go } = useView()

const showConsole = computed(() => isAuthenticated.value && role.value === 'ADMIN' && isAdminView.value)

// Courtesy, not the boundary -- the API's 403 is. A non-admin who lands on an admin
// hash is sent back to the chat instead of to a screen that would only error.
// Replaced, not pushed: a pushed entry would put the back button on the hash it was
// just bounced off, so back would never reach the screen before it.
watchEffect(() => {
  if (isAdminView.value && role.value !== 'ADMIN') go('chat', { replace: true })
})

onMounted(() => {
  void fetchMe()
})
</script>

<template>
  <AdminLayout v-if="showConsole">
    <KnowledgeView v-if="view === 'admin/knowledge'" />
    <LogsView v-else-if="view === 'admin/logs'" />
    <UsersView v-else-if="view === 'admin/users'" />
  </AdminLayout>
  <ChatBox v-else-if="isAuthenticated" />
  <LoginForm v-else />
</template>
