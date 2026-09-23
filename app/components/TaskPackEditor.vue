<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({ task: { type: Object, required: true }, focusKey: { type: String, default: '' } })
const emit = defineEmits(['edit', 'confirm', 'accept', 'handoff', 'save'])
const active = ref('TASK BRIEF')
const sections = computed(() => props.task.task_pack?.sections || [])
const current = computed(() => sections.value.find((section) => section.name === active.value) || sections.value[0])
watch(() => props.focusKey, (key) => { const section = sections.value.find((entry) => entry.items.some((item) => item.key === key)); if (section) active.value = section.name }, { immediate: true })
const names = {
  'TASK BRIEF': 'Краткое описание',
  'STARTER DATA': 'Стартовые данные',
  'EXPECTED DELIVERABLE': 'Ожидаемый результат',
  'DEFINITION OF DONE': 'Критерии приёмки',
  'FIRST SPRINT': 'Первый спринт',
  'COLLABORATION': 'Взаимодействие',
  'RISKS AND CONSTRAINTS': 'Риски и ограничения',
}
function valueFor(item) { return item.key === 'deadline' ? props.task.deadline : item.key in props.task.fields ? props.task.fields[item.key] : props.task.extras?.[item.key] || '' }
function isConfirmed(item) { return item.key in props.task.fields ? props.task.confirmed?.[item.key] : props.task.extra_confirmed?.[item.key] }
function sourceLabel(item) { return item.source === 'ai' ? 'AI · цитата из описания' : item.source === 'answer' ? 'Ответ в интервью' : item.source === 'user' ? 'Представитель бизнеса' : 'Источник не указан' }
</script>

<template>
  <section class="pack-editor" aria-label="Редактор Task Pack">
    <div class="pack-intro"><div><span class="eyebrow">TASK PACK · {{ task.task_pack?.version }}</span><h2>Рабочий пакет задачи</h2><p>Только подтверждённые сведения считаются готовыми к передаче. Каждый раздел можно уточнить отдельно.</p></div><button class="button button-ghost" type="button" @click="emit('save')">Сохранить изменения</button></div>
    <div class="pack-layout"><nav class="pack-nav" aria-label="Разделы Task Pack"><button v-for="section in sections" :key="section.name" type="button" :class="{ active: current?.name === section.name }" @click="active = section.name"><span>{{ names[section.name] }}</span><small>{{ section.items.filter((item) => isConfirmed(item)).length }}/{{ section.items.length }}</small></button></nav>
      <div v-if="current" class="pack-content"><div class="pack-section-head"><span class="eyebrow">{{ current.name }}</span><h3>{{ names[current.name] }}</h3></div>
        <div v-for="item in current.items" :key="item.key" class="pack-field" :data-field="item.key"><div class="pack-field-head"><label :for="`pack-${item.key}`">{{ item.label }} <small v-if="item.points">+{{ item.points }}</small></label><span class="pack-field-status" :class="{ confirmed: isConfirmed(item), ai: item.source === 'ai' && !isConfirmed(item) }"><ForgeIcon v-if="isConfirmed(item)" name="check" size="13" /> {{ isConfirmed(item) ? 'Подтверждено' : item.source === 'ai' ? 'AI-черновик' : 'Не подтверждено' }}</span></div>
          <template v-if="item.key === 'acceptance_responsibility'"><p class="responsibility-note">Критерии приёмки определяет и утверждает представитель бизнеса. Система не создаёт числовые пороги без ваших данных.</p><button type="button" class="button button-ghost" :disabled="isConfirmed(item)" @click="emit('accept')"><ForgeIcon v-if="isConfirmed(item)" name="check" size="14" /> {{ isConfirmed(item) ? 'Ответственность принята' : 'Я принимаю ответственность за критерии' }}</button></template>
          <textarea v-else :id="`pack-${item.key}`" :value="valueFor(item)" rows="3" :placeholder="item.key === 'success' || item.key === 'acceptance_check' ? 'Если порог неизвестен — напишите: Требуется подтверждение бизнеса' : 'Укажите конкретные сведения; не добавляйте непроверенные факты'" @input="emit('edit', item.key, $event.target.value)" />
          <div class="pack-field-foot"><span>Источник: {{ sourceLabel(item) }}<template v-if="item.updated_at"> · {{ new Date(item.updated_at).toLocaleDateString('ru-RU') }}</template></span><button v-if="item.key !== 'acceptance_responsibility' && !isConfirmed(item)" type="button" @click="emit('confirm', item.key)">Подтвердить раздел <ForgeIcon name="arrow-right" size="14" /></button></div><div v-if="item.source === 'ai' && task.ai_evidence?.[item.key]" class="ai-source">Основание: «{{ task.ai_evidence[item.key] }}»</div>
        </div>
        <div class="pack-section-foot"><button class="button button-dark" type="button" @click="emit('handoff')">Перейти к Handoff Test <ForgeIcon name="arrow-right" size="15" /></button></div>
      </div>
    </div>
  </section>
</template>
