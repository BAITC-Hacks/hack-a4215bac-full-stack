<script setup>
const props = defineProps({ task: { type: Object, required: true }, busy: { type: Boolean, default: false }, labBusy: { type: Boolean, default: false } })
const emit = defineEmits(['run', 'test-lab', 'scenario', 'fix', 'publish'])
const prompts = [
  'Какую проблему нужно решить?', 'Для кого создаётся результат?', 'С какими данными работать?',
  'Что команда должна создать?', 'Как бизнес примет результат?',
]
</script>

<template>
  <section class="handoff-panel"><div class="handoff-hero"><div><span class="eyebrow">HANDOFF TEST · {{ task.task_pack?.version }}</span><h2>Поймёт ли задачу независимая команда?</h2><p>Проверка видит только подтверждённую карточку. История интервью и неподтверждённые AI-подсказки ей недоступны.</p></div><button class="button button-dark" type="button" :disabled="busy" @click="emit('run')">{{ busy ? 'Проверяем...' : task.handoff_result ? 'Запустить повторно' : 'Запустить проверку' }} <ForgeIcon :name="task.handoff_result ? 'refresh' : 'arrow-right'" size="15" /></button></div>
    <div v-if="task.handoff_result" class="handoff-result"><div class="handoff-result-top"><strong>{{ task.handoff_result.passed }}<small>/{{ task.handoff_result.total }}</small></strong><div><span class="eyebrow">ПРОВЕРОК ПРОЙДЕНО</span><p>{{ task.handoff_result.notice }}</p></div></div><div class="handoff-checks"><article v-for="check in task.handoff_result.checks" :key="check.id" :class="{ passed: check.passed }"><span class="handoff-icon"><ForgeIcon :name="check.passed ? 'check' : 'alert'" size="14" /></span><div><h3>{{ check.question }}</h3><p>{{ check.explanation }}</p><small v-if="!check.passed">{{ check.consequence }}</small></div><button v-if="!check.passed" type="button" @click="emit('fix', check.field)">Уточнить <ForgeIcon name="arrow-right" size="14" /></button></article></div></div>
    <div v-else class="handoff-preview"><span v-for="(prompt, index) in prompts" :key="prompt"><b>0{{ index + 1 }}</b>{{ prompt }}</span></div>
    <div class="test-lab"><div class="test-lab-header"><div><span class="eyebrow">NVIDIA NIM · ТЕСТ-ЛАБОРАТОРИЯ</span><h2>Проверьте задачу на практике</h2><p>NVIDIA предложит основной, пограничный и сбойный сценарии по подтверждённому Task Pack. Это черновые гипотезы: каждая станет видна командам только после вашего подтверждения.</p></div><button class="button button-dark" type="button" :disabled="labBusy" @click="emit('test-lab')">{{ labBusy ? 'Готовим...' : task.test_lab_result ? 'Пересоздать сценарии' : 'Создать сценарии' }} <ForgeIcon name="arrow-right" size="14" /></button></div>
      <div v-if="task.test_lab_result?.items?.length" class="test-lab-grid"><article v-for="item in task.test_lab_result.items" :key="item.kind"><span>{{ { normal: '01 · ОСНОВНОЙ', edge: '02 · ПОГРАНИЧНЫЙ', failure: '03 · СБОЙНЫЙ' }[item.kind] }}</span><h3>{{ item.title }}</h3><p><b>Шаги:</b> {{ item.steps }}</p><p><b>Ожидается:</b> {{ item.expected }}</p><small>Открытый вопрос: {{ item.open_question }}</small><button class="button" :class="item.confirmed ? 'button-ghost' : 'button-orange'" type="button" :disabled="labBusy" @click="emit('scenario', item.kind, !item.confirmed)">{{ item.confirmed ? 'Скрыть от команд' : 'Подтвердить сценарий' }}</button></article></div>
      <p v-else class="test-lab-empty">Для генерации подтвердите проблему и ожидаемый результат. Если NVIDIA-ключ ещё не добавлен, укажите его в серверном `.env`.</p>
    </div>
    <div class="handoff-publish"><div><strong>{{ task.build?.errors ? 'Есть критические пробелы' : 'Пакет можно передать команде' }}</strong><p>Низкий рейтинг не блокирует публикацию. Предупреждения будут видны командам.</p></div><button class="button button-orange" type="button" @click="emit('publish')">{{ task.build?.errors || task.build?.warnings ? 'Опубликовать с предупреждениями' : 'Опубликовать задачу' }} <ForgeIcon name="arrow-right" size="15" /></button></div>
  </section>
</template>
