<script setup>
import { computed } from 'vue'

const props = defineProps({ task: { type: Object, required: true }, compact: { type: Boolean, default: false } })
const emit = defineEmits(['fix'])
const build = computed(() => props.task.build || { status: 'failed', errors: 0, warnings: 0, diagnostics: [], next_step: null })
const statusTitle = computed(() => build.value.status === 'success' ? 'Задача готова' : build.value.status === 'warning' ? 'Остались уточнения' : 'Нужны важные детали')
const visible = computed(() => props.compact ? build.value.diagnostics.filter((item) => item.severity !== 'passed').slice(0, 3) : build.value.diagnostics)
</script>

<template>
  <section class="compiler-card" :class="`compiler-${build.status}`" aria-label="Проверка готовности задачи">
    <div class="compiler-head"><div><span class="eyebrow">ПРОВЕРКА ЗАДАЧИ</span><h3>{{ statusTitle }}</h3></div><strong>{{ build.score }}<small>/100</small></strong></div>
    <div class="compiler-counts"><span :class="{ severe: build.errors }">{{ build.errors }} ошибок</span><span :class="{ caution: build.warnings }">{{ build.warnings }} предупреждений</span><span>{{ task.task_pack?.version || 'v0.1' }}</span></div>
    <div v-if="visible.length" class="diagnostic-list"><article v-for="item in visible" :key="item.code" class="diagnostic" :class="`diagnostic-${item.severity}`"><div class="diagnostic-title"><span>{{ item.code }}</span><strong>{{ item.title }}</strong></div><p>{{ item.consequence }}</p><div v-if="item.severity !== 'passed'" class="diagnostic-action"><small>{{ item.max_score_impact ? `До +${item.max_score_impact} баллов` : item.action }}</small><button type="button" @click="emit('fix', item.field)">Исправить →</button></div></article></div>
    <div v-if="build.next_step" class="compiler-next">Самый полезный следующий шаг: <strong>{{ build.next_step.action.toLowerCase() }}</strong></div>
    <div v-else class="compiler-next">Критических пробелов не осталось. Проверьте передачу задачи команде.</div>
  </section>
</template>
