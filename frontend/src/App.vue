<script setup lang="ts">
import ChatBox from './components/ChatBox.vue'
import LoginForm from './components/LoginForm.vue'
import { useAuth } from './composables/useAuth'

const { isAuthenticated } = useAuth()
</script>

<template>
  <ChatBox v-if="isAuthenticated" />
  <LoginForm v-else />
</template>
