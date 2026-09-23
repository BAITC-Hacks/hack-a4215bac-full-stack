<script setup>
import { computed } from 'vue'
import { scoreTask } from '~/utils/readiness.js'

const props = defineProps({ task: { type: Object, required: true } })
defineEmits(['student-view'])
const result = computed(() => scoreTask(props.task))
const tone = computed(() => ({ Черновик: 'draft', Рабочая: 'working', Готовая: 'ready', Приоритетная: 'priority' })[result.value.level])
</script>

<template>
  <aside class="progress-panel">
    <div class="panel-topline"><span>ГОТОВНОСТЬ ЗАДАЧИ</span><button class="text-button" @click="$emit('student-view')">◎ Глазами команды</button></div>
    <div class="score-hero">
      <div class="score-ring" :style="{ '--score': `${result.score}%` }"><div class="score-ring-inner"><strong>{{ result.score }}</strong><span>/ 100</span></div></div>
      <div><span class="status" :class="`status-${tone}`"><span class="status-dot" />{{ result.level }}</span><p>Баллы получает только заполненная и подтверждённая информация.</p></div>
    </div>
    <div class="score-list"><div v-for="group in result.groups" :key="group.name" class="score-row"><span>{{ group.name }}</span><strong :class="{ muted: !group.earned }">{{ group.earned }}<small>/{{ group.possible }}</small></strong></div></div>
    <div class="next-step"><span class="eyebrow">СЛЕДУЮЩИЙ ШАГ</span><p>{{ result.missing[0] ? `Уточните: ${result.missing[0].label.toLowerCase()}` : 'Карточка полностью готова к работе' }}</p><span v-if="result.missing[0]" class="gain">+{{ result.missing[0].points }} баллов</span></div>
  </aside>
</template>
