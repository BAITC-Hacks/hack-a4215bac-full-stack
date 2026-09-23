<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { fields, scoreTask, validField } from '~/utils/readiness.js'

const apiBase = useRuntimeConfig().public.apiBase
const categories = ['AI', 'Web', 'Data', 'Design', 'Другое']
const levels = ['Черновик', 'Рабочая', 'Готовая', 'Приоритетная']
const tasks = ref([])
const drafts = ref([])
const teams = ref([])
const proposals = ref([])
const user = ref(null)
const token = ref('')
const authMode = ref('login')
const authBusy = ref(false)
const authForm = reactive({ email: '', password: '', name: '', organization: '', role: 'business', skills: '' })
const aiConfigured = ref(false)
const aiModel = ref('')
const profile = reactive({ name: '', skills: '' })
const view = ref('create')
const phase = ref('start')
const raw = ref('')
const draft = ref(null)
const questions = ref([])
const questionIndex = ref(0)
const answer = ref('')
const busy = ref(false)
const loading = ref(false)
const loadError = ref('')
const toast = ref('')
const topicFilter = ref('Все темы')
const levelFilter = ref('Любой уровень')
const selectedTaskId = ref(null)
const inboxTaskId = ref(null)
const studentModalTask = ref(null)
const proposal = reactive({ idea: '', plan: '', deadline: '', link: '' })
let toastTimer

const published = computed(() => [...tasks.value].sort((a, b) => scoreTask(b).score - scoreTask(a).score || b.created_at.localeCompare(a.created_at)))
const filtered = computed(() => published.value.filter((task) => (topicFilter.value === 'Все темы' || task.category === topicFilter.value) && (levelFilter.value === 'Любой уровень' || scoreTask(task).level === levelFilter.value)))
const selectedTask = computed(() => tasks.value.find((task) => task.id === selectedTaskId.value))
const inboxTask = computed(() => tasks.value.find((task) => task.id === inboxTaskId.value))
const inboxProposals = computed(() => proposals.value.filter((item) => item.task_id === inboxTaskId.value))
const pendingCount = computed(() => proposals.value.filter((item) => item.status === 'pending').length)
const confirmedCount = computed(() => draft.value ? scoreTask(draft.value).items.filter((item) => item.earned).length : 0)
const myTasks = computed(() => published.value.filter((task) => task.owner_id === user.value?.id))
const inboxTasks = computed(() => user.value?.role === 'business' ? myTasks.value : published.value.filter((task) => proposals.value.some((item) => item.task_id === task.id)))
const isBusiness = computed(() => user.value?.role === 'business')

function notify(message) {
  toast.value = message
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 4500)
}

function explain(error) {
  const detail = error?.data?.detail
  return typeof detail === 'string' ? detail : 'Не удалось выполнить действие. Проверьте подключение к API.'
}

async function api(path, options = {}) {
  return await $fetch(`${apiBase}${path}`, { ...options, headers: { ...(options.headers || {}), ...(token.value ? { Authorization: `Bearer ${token.value}` } : {}) } })
}

async function authenticate() {
  authBusy.value = true
  try {
    const body = authMode.value === 'register'
      ? { ...authForm, skills: authForm.skills.split(',').map((item) => item.trim()).filter(Boolean) }
      : { email: authForm.email, password: authForm.password }
    const result = await api(`/api/auth/${authMode.value}`, { method: 'POST', body })
    token.value = result.token
    localStorage.setItem('forge_token', result.token)
    user.value = result.user
    authForm.password = ''
    view.value = isBusiness.value ? 'create' : 'catalog'
    await load()
  } catch (error) { notify(explain(error)) }
  finally { authBusy.value = false }
}

async function logout() {
  try { await api('/api/auth/logout', { method: 'POST' }) } catch { /* local sign-out still works */ }
  localStorage.removeItem('forge_token')
  token.value = ''
  user.value = null
  tasks.value = []; drafts.value = []; teams.value = []; proposals.value = []
  draft.value = null; selectedTaskId.value = null; inboxTaskId.value = null
}

onMounted(async () => {
  const saved = localStorage.getItem('forge_token')
  if (!saved) return
  token.value = saved
  try {
    user.value = await api('/api/auth/me')
    view.value = isBusiness.value ? 'create' : 'catalog'
    await load()
  } catch {
    localStorage.removeItem('forge_token')
    token.value = ''; user.value = null
  }
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [taskList, draftList, teamList, proposalList, health] = await Promise.all([api('/api/tasks'), isBusiness.value ? api('/api/tasks?published=false') : Promise.resolve([]), api('/api/teams'), api('/api/proposals'), api('/api/health')])
    tasks.value = taskList
    drafts.value = draftList
    teams.value = teamList
    proposals.value = proposalList
    aiConfigured.value = health.ai_configured
    if (!inboxTasks.value.some((task) => task.id === inboxTaskId.value)) inboxTaskId.value = inboxTasks.value[0]?.id || null
    if (user.value?.team) { profile.name = user.value.team.name; profile.skills = user.value.team.skills.join(', ') }
  } catch (error) { loadError.value = explain(error) }
  finally { loading.value = false }
}

async function startTask() {
  if (raw.value.trim().length < 15) { notify('Опишите задачу хотя бы в одном предложении.'); return }
  busy.value = true
  try {
    draft.value = await api('/api/tasks', { method: 'POST', body: { raw: raw.value.trim() } })
    drafts.value = [draft.value, ...drafts.value]
    phase.value = 'review'
    if (aiConfigured.value) {
      try {
        const result = await api(`/api/tasks/${draft.value.id}/analyze`, { method: 'POST' })
        draft.value = result.task
        questions.value = result.questions
        aiModel.value = result.model
        if (questions.value.length) phase.value = 'interview'
        notify('AI выделил факты из описания. Проверьте их перед публикацией.')
      } catch (error) { notify(`AI-анализ не выполнен: ${explain(error)} Черновик сохранён — заполните карточку вручную.`) }
    } else notify('Черновик создан. Добавьте OPENAI_API_KEY в .env и перезапустите API для AI-анализа.')
  } catch (error) { notify(explain(error)); phase.value = 'start' }
  finally { busy.value = false }
}

async function resumeDraft(task) {
  try { draft.value = await api(`/api/tasks/${task.id}`); phase.value = 'review' }
  catch (error) { notify(explain(error)) }
}

async function continueInterview() {
  busy.value = true
  phase.value = 'interview'
  questionIndex.value = 0
  answer.value = ''
  try {
    const result = await api(`/api/tasks/${draft.value.id}/interview`, { method: 'POST' })
    questions.value = result.questions
    aiModel.value = result.model
  } catch (error) { notify(explain(error)); phase.value = 'review' }
  finally { busy.value = false }
}

async function saveAnswer(skip = false) {
  const current = questions.value[questionIndex.value]
  if (!current) { phase.value = 'review'; return }
  const field = fields.find((item) => item.key === current.field)
  if (!skip && !validField(field, answer.value)) { notify(`Ответьте подробнее: минимум ${field.min} символов.`); return }
  try {
    if (!skip) draft.value = await api(`/api/tasks/${draft.value.id}`, { method: 'PATCH', body: { fields: { [current.field]: answer.value.trim() }, confirmed: { [current.field]: true } } })
    answer.value = ''
    if (questionIndex.value + 1 >= questions.value.length) phase.value = 'review'
    else questionIndex.value += 1
  } catch (error) { notify(explain(error)) }
}

function editField(key, value) {
  draft.value = { ...draft.value, fields: { ...draft.value.fields, [key]: value }, confirmed: { ...draft.value.confirmed, [key]: false }, ai_evidence: { ...draft.value.ai_evidence, [key]: null } }
}

async function confirmField(key) {
  const field = fields.find((item) => item.key === key)
  if (!validField(field, draft.value.fields[key])) { notify(`Заполните «${field.label}» подробнее.`); return }
  try { draft.value = await api(`/api/tasks/${draft.value.id}`, { method: 'PATCH', body: { title: draft.value.title, category: draft.value.category, fields: draft.value.fields, confirmed: { ...draft.value.confirmed, [key]: true } } }) }
  catch (error) { notify(explain(error)) }
}

async function saveDraft() {
  try {
    draft.value = await api(`/api/tasks/${draft.value.id}`, { method: 'PATCH', body: { title: draft.value.title, category: draft.value.category, fields: draft.value.fields, confirmed: draft.value.confirmed } })
    drafts.value = drafts.value.map((item) => item.id === draft.value.id ? draft.value : item)
    notify('Черновик сохранён.')
  } catch (error) { notify(explain(error)) }
}

async function publishTask() {
  if (!draft.value.title.trim()) { notify('Укажите название задачи.'); return }
  try {
    await api(`/api/tasks/${draft.value.id}`, { method: 'PATCH', body: { title: draft.value.title, category: draft.value.category, fields: draft.value.fields, confirmed: draft.value.confirmed } })
    const publishedTask = await api(`/api/tasks/${draft.value.id}/publish`, { method: 'POST' })
    tasks.value = [publishedTask, ...tasks.value.filter((task) => task.id !== publishedTask.id)]
    drafts.value = drafts.value.filter((task) => task.id !== publishedTask.id)
    selectedTaskId.value = publishedTask.id
    inboxTaskId.value = publishedTask.id
    view.value = 'catalog'
    notify('Задача опубликована и доступна всем командам.')
  } catch (error) { notify(explain(error)) }
}

function startNew() { view.value = 'create'; phase.value = 'start'; raw.value = ''; draft.value = null; questions.value = []; questionIndex.value = 0; answer.value = '' }

async function submitProposal() {
  if (!proposal.idea.trim() || !proposal.plan.trim() || !proposal.deadline.trim() || !proposal.link.trim()) { notify('Заполните все поля предложения.'); return }
  try {
    const created = await api('/api/proposals', { method: 'POST', body: { task_id: selectedTask.value.id, ...proposal } })
    proposals.value = [created, ...proposals.value]
    inboxTaskId.value = selectedTask.value.id
    Object.assign(proposal, { idea: '', plan: '', deadline: '', link: '' })
    notify('Предложение отправлено. Бизнес сам примет решение.')
  } catch (error) { notify(explain(error)) }
}

async function setDecision(item, status) {
  try {
    const updated = await api(`/api/proposals/${item.id}/decision`, { method: 'PATCH', body: { status } })
    proposals.value = proposals.value.map((entry) => entry.id === item.id ? updated : entry)
    notify(status === 'accepted' ? 'Команда выбрана вручную.' : 'Предложение отклонено.')
  } catch (error) { notify(explain(error)) }
}

async function rejectAll() {
  try {
    await api(`/api/tasks/${inboxTaskId.value}/reject-all`, { method: 'POST' })
    proposals.value = await api('/api/proposals')
    notify('Бизнес решил пока не выбирать команду.')
  } catch (error) { notify(explain(error)) }
}

async function confirmProgress(item) {
  try {
    const result = await api(`/api/proposals/${item.id}/progress`, { method: 'POST' })
    proposals.value = proposals.value.map((entry) => entry.id === item.id ? result.proposal : entry)
    teams.value = await api('/api/teams')
    notify('Этап подтверждён: команда получила 20 баллов за прогресс.')
  } catch (error) { notify(explain(error)) }
}

function teamFor(item) { return teams.value.find((team) => team.id === item.team_id) }
function toneFor(task) { return ({ Черновик: 'draft', Рабочая: 'working', Готовая: 'ready', Приоритетная: 'priority' })[scoreTask(task).level] }
function showCatalog() { view.value = 'catalog'; selectedTaskId.value = null }

async function saveProfile() {
  try {
    user.value = await api('/api/teams/me', { method: 'PATCH', body: { name: profile.name.trim(), skills: profile.skills.split(',').map((item) => item.trim()).filter(Boolean) } })
    teams.value = await api('/api/teams')
    notify('Профиль команды обновлён.')
  } catch (error) { notify(explain(error)) }
}
</script>

<template>
  <div v-if="!user" class="auth-shell">
    <div class="auth-brand"><div class="brand-mark">F<span>.</span></div><span>FORGE</span></div>
    <div class="auth-layout">
      <section class="auth-story"><span class="eyebrow">AI SANA · ПРАКТИЧЕСКИЕ ЗАДАНИЯ</span><h1>Из настоящей проблемы — в сильный проект.</h1><p>Бизнес формулирует задачу с помощью AI. Команды выбирают вызов, предлагают решение и получают признание за реальный прогресс.</p><div class="auth-steps"><span>01 · Опишите проблему</span><span>02 · Сверьте факты</span><span>03 · Найдите команду</span></div></section>
      <section class="auth-card"><span class="eyebrow accent-text">ДОБРО ПОЖАЛОВАТЬ</span><h2>{{ authMode === 'login' ? 'Войти в FORGE' : 'Создать аккаунт' }}</h2><p>{{ authMode === 'login' ? 'Продолжите работу со своими задачами и откликами.' : 'Выберите свою роль и начните работать с реальными проектами.' }}</p><div class="auth-switch"><button :class="{ active: authMode === 'login' }" @click="authMode = 'login'">Вход</button><button :class="{ active: authMode === 'register' }" @click="authMode = 'register'">Регистрация</button></div>
        <form class="auth-form" @submit.prevent="authenticate"><template v-if="authMode === 'register'"><div class="role-picker"><button type="button" :class="{ active: authForm.role === 'business' }" @click="authForm.role = 'business'"><strong>Бизнес</strong><span>Публикую задачи</span></button><button type="button" :class="{ active: authForm.role === 'team' }" @click="authForm.role = 'team'"><strong>Команда</strong><span>Предлагаю решения</span></button></div><label>Ваше имя<input v-model="authForm.name" autocomplete="name" required minlength="2" placeholder="Как к вам обращаться" /></label><label>{{ authForm.role === 'business' ? 'Организация' : 'Название команды' }}<input v-model="authForm.organization" required minlength="2" :placeholder="authForm.role === 'business' ? 'Название компании' : 'Название команды'" /></label><label v-if="authForm.role === 'team'">Навыки команды<input v-model="authForm.skills" required placeholder="Например: Python, UX, Data" /><small>Через запятую, хотя бы один навык</small></label></template><label>Электронная почта<input v-model="authForm.email" type="email" autocomplete="email" required placeholder="you@example.com" /></label><label>Пароль<input v-model="authForm.password" type="password" :autocomplete="authMode === 'register' ? 'new-password' : 'current-password'" required :minlength="authMode === 'register' ? 10 : 1" placeholder="Минимум 10 символов при регистрации" /></label><button class="button button-orange full" type="submit" :disabled="authBusy">{{ authBusy ? 'Подождите...' : authMode === 'login' ? 'Войти →' : 'Зарегистрироваться →' }}</button></form>
      </section>
    </div><div v-if="toast" role="status" class="toast">{{ toast }}<button aria-label="Закрыть уведомление" @click="toast = ''">×</button></div>
  </div>
  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark">F<span>.</span></div><span>FORGE</span></div>
      <div class="side-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <nav aria-label="Основная навигация">
        <button v-if="isBusiness" class="nav-item" :class="{ active: view === 'create' }" @click="view = 'create'"><span class="nav-icon">＋</span> Создать задачу</button>
        <button class="nav-item" :class="{ active: view === 'catalog' }" @click="showCatalog"><span class="nav-icon">▦</span> Каталог <span class="nav-count">{{ published.length }}</span></button>
        <button class="nav-item" :class="{ active: view === 'inbox' }" @click="view = 'inbox'"><span class="nav-icon">▣</span> {{ isBusiness ? 'Предложения' : 'Мои отклики' }} <span class="nav-count">{{ pendingCount }}</span></button>
        <button v-if="!isBusiness" class="nav-item" :class="{ active: view === 'profile' }" @click="view = 'profile'"><span class="nav-icon">◉</span> Профиль</button>
      </nav>
      <div class="sidebar-bottom"><span class="little-star">✳</span><p>Хорошие решения начинаются с ясной задачи.</p><small>AI Sana · FORGE</small></div>
    </aside>

    <main class="main">
      <header class="topbar"><div class="mobile-brand"><div class="brand"><div class="brand-mark">F<span>.</span></div><span>FORGE</span></div></div><span class="topbar-path">FORGE <span>/</span> {{ view === 'create' ? 'Конструктор задачи' : view === 'catalog' ? 'Открытый каталог' : view === 'profile' ? 'Профиль команды' : 'Предложения' }}</span><div class="topbar-right"><span v-if="isBusiness" class="demo-badge" :class="{ 'ai-off': !aiConfigured }"><span /> {{ aiConfigured ? 'AI подключён' : 'AI не настроен' }}</span><span class="topbar-user">{{ user.name }} · {{ user.organization }}</span><button class="logout-button" @click="logout">Выйти</button></div></header>

      <div v-if="loading" class="page loading-page"><div class="loading-state"><div class="loading-mark">✳</div><strong>Загружаем FORGE...</strong></div></div>
      <div v-else-if="loadError" class="page error-page"><h1>Не удалось подключиться к API</h1><p>{{ loadError }}</p><p>Запустите FastAPI на порту 8000 и повторите попытку.</p><button class="button button-dark" @click="load">Повторить →</button></div>

      <div v-else-if="view === 'create'" class="page create-page">
        <div class="page-heading"><div><span class="eyebrow accent-text">КОНСТРУКТОР ЗАДАЧИ</span><h1>{{ phase === 'start' ? 'Начните с проблемы.' : phase === 'interview' ? 'Собираем задачу.' : 'Проверьте карточку.' }}</h1><p>{{ phase === 'start' ? 'Опишите ситуацию своими словами. FORGE поможет уточнить детали и подготовить задачу для студентов.' : phase === 'interview' ? 'Ответы сразу попадают в Blueprint. Каждый подтверждённый факт повышает готовность.' : 'Проверьте каждый раздел. После изменений подтвердите поле, чтобы оно учитывалось в рейтинге.' }}</p></div><button v-if="phase !== 'start'" class="button button-ghost" @click="startNew">＋ Новая задача</button></div>

        <div v-if="phase === 'start'" class="start-grid">
          <div class="start-card"><div class="card-heading"><span class="round-icon">✳</span><div><strong>Опишите вашу задачу</strong><span>Достаточно одного абзаца, даже если детали ещё неизвестны.</span></div></div><textarea v-model="raw" class="hero-textarea" maxlength="5000" placeholder="Например: наша команда тратит много времени на ручную обработку обращений клиентов. Хотим ускорить этот процесс..." /><div class="textarea-footer"><span>{{ raw.length }} / 5000 символов</span><button class="button button-orange" :disabled="busy" @click="startTask">{{ busy ? 'Создаём...' : 'Создать Blueprint' }} <span>→</span></button></div></div>
          <div class="intro-panel"><span class="eyebrow">КАК ЭТО РАБОТАЕТ</span><div class="intro-step"><b>01</b><div><strong>Опишите проблему</strong><span>Без длинной анкеты и специальных терминов.</span></div></div><div class="intro-step"><b>02</b><div><strong>Проверьте AI-анализ</strong><span>Модель предложит поля только с подтверждаемыми цитатами из описания.</span></div></div><div class="intro-step"><b>03</b><div><strong>Подтвердите и опубликуйте</strong><span>Рейтинг покажет готовность к работе.</span></div></div><div class="ai-hint" v-if="!aiConfigured">AI пока не настроен. Добавьте OPENAI_API_KEY в .env на сервере и перезапустите FastAPI. Ручное заполнение доступно уже сейчас.</div><div class="ai-hint" v-else>AI-анализ подключён. Подсказки не считаются подтверждёнными до вашей проверки.</div></div>
        </div>
        <section v-if="phase === 'start' && drafts.length" class="drafts-section"><div class="drafts-head"><span class="eyebrow">СОХРАНЁННЫЕ ЧЕРНОВИКИ</span><span>{{ drafts.length }} задач</span></div><div class="drafts-grid"><button v-for="task in drafts.slice(0, 6)" :key="task.id" class="draft-resume" @click="resumeDraft(task)"><span class="draft-icon">↗</span><strong>{{ task.title }}</strong><small>{{ scoreTask(task).score }} / 100 · Продолжить</small></button></div></section>

        <div v-else-if="phase === 'interview' && draft" class="workspace-grid">
          <section class="work-card interview-card"><div class="work-card-head"><div><span class="eyebrow">AI ИНТЕРВЬЮ</span><h2>Давайте уточним детали</h2></div><span class="step-count">{{ busy ? 'Подготовка' : `${Math.min(questionIndex + 1, questions.length)} / ${questions.length}` }}</span></div>
            <div v-if="busy" class="loading-state"><div class="loading-mark">✳</div><strong>Анализируем описание...</strong><span>Подбираем вопросы по недостающим сведениям</span></div>
            <template v-else-if="questions[questionIndex]"><div class="interview-chat"><div class="ai-message"><span class="ai-avatar">F</span><div><span class="message-name">FORGE AI</span><p>Уточните недостающие детали, чтобы команде было легче начать работу.</p></div></div><div class="question-box"><span class="question-number">ВОПРОС {{ questionIndex + 1 }}</span><h3>{{ questions[questionIndex].question }}</h3><span class="gain">До +{{ fields.find((field) => field.key === questions[questionIndex].field)?.points }} баллов</span></div></div><textarea v-model="answer" class="answer-textarea" placeholder="Напишите конкретный ответ..." /><div class="interview-actions"><button class="text-button" @click="saveAnswer(true)">Пропустить вопрос</button><button class="button button-dark" @click="saveAnswer(false)">Сохранить ответ <span>→</span></button></div><div class="interview-bottom"><span>Вопросы сформированы {{ aiModel || 'AI' }}</span><button @click="phase = 'review'">Перейти к карточке →</button></div></template>
            <div v-else class="done-state"><div class="done-icon">✓</div><h3>Интервью завершено</h3><p>Теперь проверьте сформированную карточку.</p><button class="button button-orange" @click="phase = 'review'">Открыть карточку →</button></div>
          </section><ScorePanel :task="draft" @student-view="studentModalTask = draft" />
        </div>

        <div v-else-if="phase === 'review' && draft" class="workspace-grid">
          <section class="work-card review-card">
            <div class="work-card-head"><div><span class="eyebrow">TASK BLUEPRINT</span><h2>Карточка задачи</h2></div><div class="review-head-actions"><button class="text-button" :disabled="!aiConfigured" @click="continueInterview">✳ Уточнить с AI</button><span class="review-count">{{ confirmedCount }} / 9 подтверждено</span></div></div>
            <div class="form-row"><label>Название задачи<input v-model="draft.title" maxlength="140" placeholder="Короткое название" /></label><label>Тема<select v-model="draft.category"><option v-for="category in categories" :key="category">{{ category }}</option></select></label></div>
            <div class="fields-list"><div v-for="field in fields" :key="field.key" class="field-block"><div class="field-header"><label :for="`field-${field.key}`">{{ field.label }} <span>+{{ field.points }}</span></label><span class="field-state" :class="{ 'is-confirmed': draft.confirmed[field.key] && validField(field, draft.fields[field.key]) }">{{ draft.confirmed[field.key] && validField(field, draft.fields[field.key]) ? '✓ Подтверждено' : 'Не подтверждено' }}</span></div><textarea :id="`field-${field.key}`" :value="draft.fields[field.key]" :placeholder="field.hint" rows="2" @input="editField(field.key, $event.target.value)" /><div v-if="draft.ai_evidence?.[field.key]" class="ai-source">AI-подсказка · источник: «{{ draft.ai_evidence[field.key] }}»</div><div class="field-footer"><small>{{ field.hint }}</small><button v-if="!draft.confirmed[field.key]" @click="confirmField(field.key)">Подтвердить ✓</button></div></div></div>
            <div class="publish-footer"><div><strong>Информация проверена вами</strong><span>Неполные задачи тоже видны в каталоге и открыты для откликов.</span></div><div class="publish-buttons"><button class="button button-ghost" @click="saveDraft">Сохранить</button><button class="button button-orange" @click="publishTask">Опубликовать задачу <span>→</span></button></div></div>
          </section><ScorePanel :task="draft" @student-view="studentModalTask = draft" />
        </div>
      </div>

      <div v-else-if="view === 'catalog'" class="page catalog-page"><div class="page-heading catalog-heading"><div><span class="eyebrow accent-text">ОТКРЫТЫЕ ЗАДАЧИ</span><h1>Выберите свою миссию.</h1><p>Все опубликованные задачи доступны каждой команде. Рейтинг показывает, насколько легко начать работу.</p></div><div class="catalog-total"><strong>{{ published.length }}</strong><span>задач в каталоге</span></div></div>
        <div v-if="selectedTask" class="detail-layout"><div class="detail-main"><button class="back-link" @click="selectedTaskId = null">← Назад к каталогу</button><div class="detail-card"><div class="detail-head"><span class="topic-label">{{ selectedTask.category }} / {{ selectedTask.owner }}</span><span class="status" :class="`status-${toneFor(selectedTask)}`"><span class="status-dot" />{{ scoreTask(selectedTask).level }}</span></div><h2>{{ selectedTask.title }}</h2><div class="detail-score"><strong>{{ scoreTask(selectedTask).score }}</strong><span>/ 100 готовность к работе</span></div><div class="detail-sections"><section v-for="field in fields" :key="field.key"><h3>{{ field.label }}</h3><p>{{ selectedTask.fields[field.key] || 'Пока не указано — можно уточнить у бизнеса.' }}</p></section></div></div></div>
          <aside v-if="!isBusiness" class="proposal-card"><span class="eyebrow">ОТКЛИК КОМАНДЫ</span><h2>Предложите решение</h2><p>От имени {{ user.team?.name }}. Бизнес сравнит отклики и сам выберет команду.</p><form @submit.prevent="submitProposal"><label>Идея решения<textarea v-model="proposal.idea" required minlength="12" placeholder="Как вы решите задачу?" rows="3" /></label><label>План работы<textarea v-model="proposal.plan" required minlength="12" placeholder="Этапы работы и проверки" rows="3" /></label><label>Срок<input v-model="proposal.deadline" required placeholder="Например, 14 дней" /></label><label>Ссылка на прототип<input v-model="proposal.link" type="url" required placeholder="https://example.com/prototype" /></label><button class="button button-orange full" type="submit">Отправить предложение <span>→</span></button></form></aside>
          <aside v-else class="proposal-card"><span class="eyebrow">ЗАДАЧА БИЗНЕСА</span><h2>Отклики команд</h2><p>Предложения доступны владельцу задачи в личном кабинете.</p><button v-if="selectedTask.owner_id === user.id" class="button button-dark full" @click="inboxTaskId = selectedTask.id; view = 'inbox'">Смотреть предложения →</button></aside>
        </div>
        <template v-else><div class="filters"><span class="filter-label">ФИЛЬТРЫ</span><select v-model="topicFilter" aria-label="Фильтр по теме"><option>Все темы</option><option v-for="category in categories" :key="category">{{ category }}</option></select><select v-model="levelFilter" aria-label="Фильтр по готовности"><option>Любой уровень</option><option v-for="level in levels" :key="level">{{ level }}</option></select><span class="filter-result">Показано {{ filtered.length }} из {{ published.length }}</span></div><div class="task-grid"><button v-for="task in filtered" :key="task.id" class="task-card" @click="selectedTaskId = task.id"><div class="task-card-top"><span class="topic-label">{{ task.category }} · {{ task.owner }}</span><span class="task-card-arrow">↗</span></div><h2>{{ task.title }}</h2><p>{{ task.fields.need || task.fields.context }}</p><div class="task-card-bottom"><div><strong>{{ scoreTask(task).score }}</strong><span>/ 100 готовность</span></div><span class="status" :class="`status-${toneFor(task)}`"><span class="status-dot" />{{ scoreTask(task).level }}</span></div></button></div><div v-if="!filtered.length" class="empty-state">{{ published.length ? 'По выбранным фильтрам задач нет.' : 'Пока нет опубликованных задач. Бизнес может создать первую задачу в конструкторе.' }}</div></template>
      </div>

      <div v-else-if="view === 'profile' && !isBusiness" class="page profile-page"><div class="page-heading"><div><span class="eyebrow accent-text">ПРОФИЛЬ КОМАНДЫ</span><h1>{{ user.team?.name }}</h1><p>Расскажите бизнесу о вашей команде и поддерживайте навыки в актуальном состоянии.</p></div></div><div class="profile-grid"><form class="work-card profile-form" @submit.prevent="saveProfile"><label>Название команды<input v-model="profile.name" required minlength="2" maxlength="140" /></label><label>Навыки через запятую<input v-model="profile.skills" required placeholder="Python, UX, Data" /></label><button class="button button-orange" type="submit">Сохранить профиль →</button></form><div class="work-card profile-points"><span class="eyebrow">ПРОГРЕСС КОМАНДЫ</span><strong>{{ user.team?.points || 0 }}</strong><p>Баллы начисляются после подтверждения этапа бизнесом.</p></div></div></div>
      <div v-else class="page inbox-page"><div class="page-heading"><div><span class="eyebrow accent-text">{{ isBusiness ? 'РЕШЕНИЕ БИЗНЕСА' : 'МОИ ОТКЛИКИ' }}</span><h1>{{ isBusiness ? 'Предложения команд.' : 'Ваши предложения.' }}</h1><p>{{ isBusiness ? 'Сравните идеи и вручную выберите одну, несколько команд или никого.' : 'Следите за решениями бизнеса и прогрессом команды.' }}</p></div></div><div class="inbox-layout"><aside class="task-selector"><span class="eyebrow">ЗАДАЧИ</span><button v-for="task in inboxTasks" :key="task.id" :class="{ selected: inboxTaskId === task.id }" @click="inboxTaskId = task.id"><span>{{ task.title }}</span><b>{{ proposals.filter((item) => item.task_id === task.id).length }}</b></button></aside><div class="inbox-main"><div class="inbox-head"><div><span class="eyebrow">ОТКЛИКИ НА ЗАДАЧУ</span><h2>{{ inboxTask?.title || 'Выберите задачу' }}</h2><p>{{ inboxProposals.length }} {{ isBusiness ? 'предложений · решение принимает представитель бизнеса' : 'ваших предложений' }}</p></div><button v-if="isBusiness && inboxProposals.some((item) => item.status === 'pending')" class="button button-ghost" @click="rejectAll">Пока никого не выбирать</button></div><div v-if="inboxProposals.length" class="proposal-list"><article v-for="item in inboxProposals" :key="item.id" class="proposal-item"><div class="proposal-top"><div class="team-identity"><div class="team-avatar">{{ teamFor(item)?.initials || 'TM' }}</div><div><strong>{{ teamFor(item)?.name || 'Команда' }}</strong><span>{{ teamFor(item)?.skills.join(' · ') }}</span></div></div><span class="proposal-status" :class="item.status">{{ item.status === 'accepted' ? 'Выбрана' : item.status === 'rejected' ? 'Отклонена' : 'Ожидает решения' }}</span></div><div class="proposal-content"><div><span>ИДЕЯ</span><p>{{ item.idea }}</p></div><div><span>ПЛАН</span><p>{{ item.plan }}</p></div></div><div class="proposal-meta"><span>Срок: {{ item.deadline }}</span><a :href="item.link" target="_blank" rel="noopener noreferrer">↗ Прототип</a><span>Баллы команды: {{ teamFor(item)?.points || 0 }}</span></div><div v-if="isBusiness" class="proposal-actions"><template v-if="item.status === 'pending'"><button class="button button-dark" @click="setDecision(item, 'accepted')">Выбрать команду ✓</button><button class="button button-ghost" @click="setDecision(item, 'rejected')">Отклонить</button></template><template v-else-if="item.status === 'accepted'"><span v-if="item.progress_awarded" class="stage-confirmed">✓ Этап подтверждён · +20 баллов</span><button v-else class="button button-orange" @click="confirmProgress(item)">Подтвердить этап · +20 баллов</button></template></div><div v-else-if="item.progress_awarded" class="proposal-actions stage-confirmed">✓ Этап подтверждён · +20 баллов</div></article></div><div v-else class="empty-state">{{ isBusiness ? 'Пока нет откликов. Задача доступна командам в каталоге.' : 'Вы ещё не отправили предложений. Откройте каталог и выберите задачу.' }}</div></div></div></div>
    </main>
    <StudentModal v-if="studentModalTask" :task="studentModalTask" @close="studentModalTask = null" />
    <div v-if="toast" role="status" class="toast"><span>✓</span>{{ toast }}<button aria-label="Закрыть уведомление" @click="toast = ''">×</button></div>
  </div>
</template>
