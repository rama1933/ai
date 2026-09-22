<script setup lang="ts">
/**
 * One stroke-based icon set for the whole app.
 *
 * Emoji were used here before; they render differently per platform, cannot be
 * themed, and are announced badly by screen readers. These are inline SVG on a
 * shared 24x24 grid with one stroke width, so weight stays consistent wherever
 * they appear.
 */
withDefaults(
  defineProps<{
    name:
      | 'sparkle'
      | 'user'
      | 'paperclip'
      | 'send'
      | 'sun'
      | 'moon'
      | 'logout'
      | 'alert'
      | 'close'
      | 'file'
      | 'image'
      | 'table'
      | 'search'
      | 'eye'
      | 'eye-off'
      | 'plus'
      | 'trash'
      | 'pencil'
      | 'more'
      | 'panel'
      | 'message'
      | 'stop'
      | 'copy'
      | 'database'
      | 'history'
      | 'link'
    size?: number
  }>(),
  { size: 18 },
)
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
    class="shrink-0"
  >
    <template v-if="name === 'sparkle'">
      <path d="M12 2.5l2.3 7.2 7.2 2.3-7.2 2.3L12 21.5l-2.3-7.2L2.5 12l7.2-2.3z" />
    </template>

    <template v-else-if="name === 'user'">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </template>

    <template v-else-if="name === 'paperclip'">
      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </template>

    <template v-else-if="name === 'send'">
      <path d="M12 19V5" />
      <path d="M5 12l7-7 7 7" />
    </template>

    <template v-else-if="name === 'sun'">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </template>

    <template v-else-if="name === 'moon'">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </template>

    <template v-else-if="name === 'logout'">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </template>

    <template v-else-if="name === 'alert'">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v4" />
      <path d="M12 16h.01" />
    </template>

    <template v-else-if="name === 'close'">
      <path d="M18 6L6 18M6 6l12 12" />
    </template>

    <template v-else-if="name === 'file'">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </template>

    <template v-else-if="name === 'image'">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <path d="M21 15l-5-5L5 21" />
    </template>

    <template v-else-if="name === 'table'">
      <ellipse cx="12" cy="6" rx="8" ry="3" />
      <path d="M4 6v12c0 1.66 3.58 3 8 3s8-1.34 8-3V6" />
      <path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3" />
    </template>

    <template v-else-if="name === 'search'">
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
    </template>

    <template v-else-if="name === 'eye'">
      <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z" />
      <circle cx="12" cy="12" r="3" />
    </template>

    <template v-else-if="name === 'eye-off'">
      <path d="M9.9 4.24A9.1 9.1 0 0 1 12 4c6.4 0 10 8 10 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <path d="M6.61 6.61A18.5 18.5 0 0 0 2 12s3.6 8 10 8a9.1 9.1 0 0 0 5.39-1.61" />
      <path d="M2 2l20 20" />
    </template>

    <template v-else-if="name === 'plus'">
      <path d="M12 5v14M5 12h14" />
    </template>

    <template v-else-if="name === 'trash'">
      <path d="M3 6h18" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
      <path d="M10 11v6M14 11v6" />
    </template>

    <template v-else-if="name === 'pencil'">
      <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
      <path d="m15 5 4 4" />
    </template>

    <template v-else-if="name === 'more'">
      <circle cx="12" cy="12" r="1" />
      <circle cx="12" cy="5" r="1" />
      <circle cx="12" cy="19" r="1" />
    </template>

    <template v-else-if="name === 'panel'">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M9 3v18" />
    </template>

    <template v-else-if="name === 'message'">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </template>

    <template v-else-if="name === 'link'">
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </template>

    <template v-else-if="name === 'stop'">
      <rect x="6" y="6" width="12" height="12" rx="1.5" />
    </template>

    <template v-else-if="name === 'copy'">
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </template>

    <template v-else-if="name === 'database'">
      <ellipse cx="12" cy="5.5" rx="7.5" ry="2.5" />
      <path d="M4.5 5.5v6c0 1.38 3.36 2.5 7.5 2.5s7.5-1.12 7.5-2.5v-6" />
      <path d="M4.5 11.5v6c0 1.38 3.36 2.5 7.5 2.5s7.5-1.12 7.5-2.5v-6" />
    </template>

    <template v-else-if="name === 'history'">
      <path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3 8.5" />
      <path d="M3 3.5v5h5" />
      <path d="M12 8v4.5l3 1.8" />
    </template>
  </svg>
</template>
