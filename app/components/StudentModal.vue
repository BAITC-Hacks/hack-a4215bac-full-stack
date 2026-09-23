<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { studentChecks } from '~/utils/readiness.js'

const props = defineProps({ task: { type: Object, required: true } })
const emit = defineEmits(['close'])
const checks = computed(() => studentChecks(props.task))
function onKey(event) { if (event.key === 'Escape') emit('close') }
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="student-modal-title">
      <button class="icon-button modal-close" aria-label="Закрыть" @click="$emit('close')">×</button>
      <div class="modal-icon">◎</div><span class="eyebrow">ДРУГАЯ СТОРОНА ЗАДАЧИ</span>
      <h2 id="student-modal-title">Глазами команды</h2>
      <p class="muted-copy">Вот что студент сможет понять до отклика. Пробелы показывают, что потребуется уточнить у бизнеса.</p>
      <div class="student-checks"><div v-for="item in checks" :key="item.text" class="student-check"><span :class="item.ok ? 'check-good' : 'check-warn'">{{ item.ok ? '✓' : '!' }}</span>{{ item.text }}</div></div>
      <button class="button button-dark full" @click="$emit('close')">Продолжить работу <span>→</span></button>
    </div>
  </div>
</template>
