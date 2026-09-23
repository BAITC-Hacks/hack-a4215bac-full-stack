<script setup>
const props = defineProps({ task: { type: Object, required: true }, busy: { type: Boolean, default: false } })
const emit = defineEmits(['run', 'fix', 'publish'])
const prompts = [
  'Какую проблему нужно решить?', 'Для кого создаётся результат?', 'С какими данными работать?',
  'Что команда должна создать?', 'Как бизнес примет результат?',
]
</script>

<template>
  <section class="handoff-panel"><div class="handoff-hero"><div><span class="eyebrow">HANDOFF TEST · {{ task.task_pack?.version }}</span><h2>Поймёт ли задачу независимая команда?</h2><p>Проверка видит только подтверждённую карточку. История интервью и неподтверждённые AI-подсказки ей недоступны.</p></div><button class="button button-dark" type="button" :disabled="busy" @click="emit('run')">{{ busy ? 'Проверяем...' : task.handoff_result ? 'Запустить повторно' : 'Запустить проверку' }} <ForgeIcon :name="task.handoff_result ? 'refresh' : 'arrow-right'" size="15" /></button></div>
    <div v-if="task.handoff_result" class="handoff-result"><div class="handoff-result-top"><strong>{{ task.handoff_result.passed }}<small>/{{ task.handoff_result.total }}</small></strong><div><span class="eyebrow">ПРОВЕРОК ПРОЙДЕНО</span><p>{{ task.handoff_result.notice }}</p></div></div><div class="handoff-checks"><article v-for="check in task.handoff_result.checks" :key="check.id" :class="{ passed: check.passed }"><span class="handoff-icon"><ForgeIcon :name="check.passed ? 'check' : 'alert'" size="14" /></span><div><h3>{{ check.question }}</h3><p>{{ check.explanation }}</p><small v-if="!check.passed">{{ check.consequence }}</small></div><button v-if="!check.passed" type="button" @click="emit('fix', check.field)">Уточнить <ForgeIcon name="arrow-right" size="14" /></button></article></div></div>
    <div v-else class="handoff-preview"><span v-for="(prompt, index) in prompts" :key="prompt"><b>0{{ index + 1 }}</b>{{ prompt }}</span></div>
    <div class="handoff-publish"><div><strong>{{ task.build?.errors ? 'Есть критические пробелы' : 'Пакет можно передать команде' }}</strong><p>Низкий рейтинг не блокирует публикацию. Предупреждения будут видны командам.</p></div><button class="button button-orange" type="button" @click="emit('publish')">{{ task.build?.errors || task.build?.warnings ? 'Опубликовать с предупреждениями' : 'Опубликовать задачу' }} <ForgeIcon name="arrow-right" size="15" /></button></div>
  </section>
</template>
