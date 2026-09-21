<script setup lang="ts">
import { useTheme } from '../composables/useTheme'
import AppIcon from './AppIcon.vue'

const { theme, toggle } = useTheme()
</script>

<template>
  <button
    type="button"
    class="grid h-11 w-11 cursor-pointer place-items-center rounded-xl text-subtle transition-colors duration-200 hover:bg-elevated hover:text-fg"
    :aria-label="theme === 'dark' ? 'Aktifkan mode terang' : 'Aktifkan mode gelap'"
    :title="theme === 'dark' ? 'Aktifkan mode terang' : 'Aktifkan mode gelap'"
    @click="toggle"
  >
    <AppIcon :name="theme === 'dark' ? 'sun' : 'moon'" :size="18" />
  </button>
</template>
