<script setup lang="ts">
import { onMounted } from 'vue'

import ChatBox from './components/ChatBox.vue'
import LoginForm from './components/LoginForm.vue'
import { useAuth } from './composables/useAuth'

const { isAuthenticated, fetchMe } = useAuth()

onMounted(() => {
  void fetchMe()
})
</script>

<template>
  <ChatBox v-if="isAuthenticated" />
  <LoginForm v-else />
</template>
