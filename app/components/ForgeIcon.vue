<script setup>
import { computed } from 'vue'
const props = defineProps({ name: { type: String, required: true }, size: { type: [String, Number], default: 18 } })
const paths = {
  'arrow-up-right': ['M7 17 17 7', 'M8 7h9v9'], 'arrow-right': ['M4 12h15', 'm13 6 6 6-6 6'], 'arrow-left': ['M20 12H5', 'm11 18-6-6 6-6'], 'chevron-right': ['m9 18 6-6-6-6'], 'arrow-down': ['M12 4v15', 'm18 13-6 6-6-6'],
  plus: ['M12 5v14', 'M5 12h14'], search: ['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z', 'm21 21-4.35-4.35'],
  folder: ['M3.5 7.5h6l2 2H21v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-9a2 2 0 0 1 .5-2Z'],
  grid: ['M4 4h6v6H4z', 'M14 4h6v6h-6z', 'M4 14h6v6H4z', 'M14 14h6v6h-6z'],
  message: ['M20 11.5a7.5 7.5 0 0 1-8 7.5 8 8 0 0 1-3.4-.75L4 20l1.2-3.65A7.1 7.1 0 0 1 4 12.5 7.5 7.5 0 0 1 12 5a7.5 7.5 0 0 1 8 6.5Z'],
  person: ['M20 20a8 8 0 0 0-16 0', 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z'],
  briefcase: ['M4 8h16v12H4z', 'M9 8V5h6v3', 'M4 12h16', 'M10 12v2h4v-2'],
  spark: ['m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z', 'm19 16 .8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16Z'],
  check: ['m5 12 4 4L19 6'], alert: ['M12 9v4', 'M12 17h.01', 'M10.3 4.8 2.9 18a2 2 0 0 0 1.8 3h14.6a2 2 0 0 0 1.8-3l-7.4-13.2a2 2 0 0 0-3.4 0Z'],
  close: ['M6 6l12 12', 'M18 6 6 18'], clock: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z', 'M12 6v6l4 2'],
  document: ['M7 3h7l5 5v13H7z', 'M14 3v6h5', 'M10 13h6', 'M10 17h6'], chart: ['M4 19V5', 'M4 19h16', 'm7 15 4-4 3 2 5-6'],
  team: ['M16 20v-1.5a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4V20', 'M9.5 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z', 'M17 4.3a3.5 3.5 0 0 1 0 6.7', 'M21 20v-1.5a4 4 0 0 0-3-3.87'],
  logout: ['M10 17l5-5-5-5', 'M15 12H3', 'M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6'],
  refresh: ['M20 7v5h-5', 'M4 17v-5h5', 'M5.6 9A7 7 0 0 1 18 6l2 2', 'M18.4 15A7 7 0 0 1 6 18l-2-2'],
  shield: ['M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z', 'm9 12 2 2 4-4'],
}
const segments = computed(() => paths[props.name] || paths.spark)
</script>
<template>
  <svg class="forge-icon" :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path v-for="(d, index) in segments" :key="index" :d="d" />
  </svg>
</template>
<style scoped>
.forge-icon{display:inline-block;flex:none;vertical-align:middle}
</style>
