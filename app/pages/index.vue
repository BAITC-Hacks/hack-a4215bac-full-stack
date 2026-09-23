<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { fields, scoreTask, validField } from '~/utils/readiness.js'

const apiBase = useRuntimeConfig().public.apiBase
const categories = ['AI', 'Web', 'Data', 'Design', 'Другое']
const levels = ['Черновик', 'Рабочая', 'Готовая', 'Приоритетная']
const tasks = ref([])
const drafts = ref([])
const teams = ref([])
const proposals = ref([])
const user = ref(null)
const booting = ref(true)
const token = ref('')
const authMode = ref('login')
const authStarted = ref(false)
const authBusy = ref(false)
const authForm = reactive({ email: '', password: '', name: '', organization: '', role: 'business', skills: '' })
const aiConfigured = ref(false)
const aiModel = ref('')
const adminOverview = ref(null)
const bootstrapStatus = ref(null)
const bootstrapSecret = ref('')
const adminBusy = ref(false)
const profile = reactive({ name: '', skills: '' })
const view = ref('workspace')
const phase = ref('start')
const raw = ref('')
const industry = ref('')
const deadline = ref('')
const draft = ref(null)
const questions = ref([])
const answerHistory = ref([])
const focusKey = ref('')
const questionIndex = ref(0)
const answer = ref('')
const busy = ref(false)
const loading = ref(false)
const loadError = ref('')
const toast = ref('')
const topicFilter = ref('Все темы')
const levelFilter = ref('Любой уровень')
const dataFilter = ref('Любые данные')
const deadlineFilter = ref('Любой срок')
const query = ref('')
const selectedTaskId = ref(null)
const inboxTaskId = ref(null)
const proposal = reactive({ idea: '', plan: '', deadline: '', link: '', questions: '' })
let toastTimer

const published = computed(() => [...tasks.value].sort((a, b) => scoreTask(b).score - scoreTask(a).score || b.created_at.localeCompare(a.created_at)))
const filtered = computed(() => published.value.filter((task) =>
  (topicFilter.value === 'Все темы' || task.category === topicFilter.value) &&
  (levelFilter.value === 'Любой уровень' || scoreTask(task).level === levelFilter.value) &&
  (dataFilter.value === 'Любые данные' || (dataFilter.value === 'Данные подтверждены') === !!task.confirmed?.data) &&
  (deadlineFilter.value === 'Любой срок' || (deadlineFilter.value === 'Срок указан') === !!task.deadline) &&
  (!query.value.trim() || `${task.title} ${task.owner} ${task.fields.context} ${task.industry}`.toLowerCase().includes(query.value.trim().toLowerCase()))))
const selectedTask = computed(() => tasks.value.find((task) => task.id === selectedTaskId.value))
const inboxTask = computed(() => tasks.value.find((task) => task.id === inboxTaskId.value))
const inboxProposals = computed(() => proposals.value.filter((item) => item.task_id === inboxTaskId.value))
const pendingCount = computed(() => proposals.value.filter((item) => item.status === 'pending').length)
const confirmedCount = computed(() => draft.value ? scoreTask(draft.value).items.filter((item) => item.earned).length : 0)
const myTasks = computed(() => published.value.filter((task) => task.owner_id === user.value?.id))
const inboxTasks = computed(() => user.value?.role === 'business' ? myTasks.value : published.value.filter((task) => proposals.value.some((item) => item.task_id === task.id)))
const isBusiness = computed(() => user.value?.role === 'business')
const isAdmin = computed(() => user.value?.role === 'admin')
const workspaceTasks = computed(() => [...drafts.value, ...myTasks.value].sort((a, b) => b.created_at.localeCompare(a.created_at)))
const averageScore = computed(() => workspaceTasks.value.length ? Math.round(workspaceTasks.value.reduce((sum, item) => sum + scoreTask(item).score, 0) / workspaceTasks.value.length) : 0)
const attentionCount = computed(() => workspaceTasks.value.filter((item) => item.build?.errors).length)
function proposalCount(task) { return proposals.value.filter((item) => item.task_id === task.id).length }

function notify(message) {
  toast.value = message
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 4500)
}

function beginAuth(mode = 'register') {
  authMode.value = mode
  authStarted.value = true
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function explain(error) {
  const detail = error?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) return `Проверьте заполнение: ${detail.map((item) => item.loc?.at(-1)).filter(Boolean).join(', ')}`
  if (!error?.data && !error?.response) return 'Не удалось связаться с сервером FORGE. Проверьте, что API запущен, и повторите попытку.'
  return 'Не удалось выполнить действие. Проверьте данные и повторите попытку.'
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
    view.value = isAdmin.value ? 'admin' : isBusiness.value ? 'workspace' : 'catalog'
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
  adminOverview.value = null; bootstrapStatus.value = null; bootstrapSecret.value = ''
  draft.value = null; selectedTaskId.value = null; inboxTaskId.value = null
  Object.assign(authForm, { email: '', password: '', name: '', organization: '', role: 'business', skills: '' })
  authMode.value = 'login'
  authStarted.value = false
}

onMounted(async () => {
  const saved = localStorage.getItem('forge_token')
  if (!saved) { booting.value = false; return }
  token.value = saved
  try {
    user.value = await api('/api/auth/me')
    view.value = isAdmin.value ? 'admin' : isBusiness.value ? 'workspace' : 'catalog'
    await load()
  } catch {
    localStorage.removeItem('forge_token')
    token.value = ''; user.value = null
  } finally { booting.value = false }
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    if (isAdmin.value) {
      adminOverview.value = await api('/api/admin/overview')
      bootstrapStatus.value = null
      return
    }
    const [taskList, draftList, teamList, proposalList, health] = await Promise.all([api('/api/tasks'), isBusiness.value ? api('/api/tasks?published=false') : Promise.resolve([]), api('/api/teams'), api('/api/proposals'), api('/api/health')])
    tasks.value = taskList
    drafts.value = draftList
    teams.value = teamList
    proposals.value = proposalList
    aiConfigured.value = health.ai_configured
    bootstrapStatus.value = await api('/api/admin/bootstrap-status')
    if (!inboxTasks.value.some((task) => task.id === inboxTaskId.value)) inboxTaskId.value = inboxTasks.value[0]?.id || null
    if (user.value?.team) { profile.name = user.value.team.name; profile.skills = user.value.team.skills.join(', ') }
  } catch (error) { loadError.value = explain(error) }
  finally { loading.value = false }
}

async function bootstrapAdmin() {
  if (!bootstrapSecret.value.trim()) { notify('Введите секрет администратора из .env.'); return }
  adminBusy.value = true
  try {
    user.value = await api('/api/admin/bootstrap', { method: 'POST', body: { token: bootstrapSecret.value } })
    bootstrapSecret.value = ''
    view.value = 'admin'
    await load()
    notify('Администратор назначен. Панель управления открыта.')
  } catch (error) { notify(explain(error)) }
  finally { adminBusy.value = false }
}

async function changeUserRole(target, role) {
  if (role === target.role) return
  adminBusy.value = true
  try {
    await api(`/api/admin/users/${target.id}/role`, { method: 'PATCH', body: { role } })
    adminOverview.value = await api('/api/admin/overview')
    notify(`Роль ${target.email} изменена на «${role}».`)
  } catch (error) { notify(explain(error)) }
  finally { adminBusy.value = false }
}

function localQuestions(task) {
  const candidates = [
    { field: 'need', question: 'Что именно нужно изменить в текущем процессе и почему это важно?' },
    { field: 'data', question: 'Какие данные или материалы будут доступны команде? Укажите формат и способ доступа.' },
    { field: 'outcome', question: 'Какой конкретный результат должна создать команда к завершению проекта?' },
    { field: 'success', question: 'По каким проверяемым признакам вы примете результат?' },
    { field: 'users', question: 'Кто будет пользоваться будущим решением?' },
    { field: 'contact', question: 'Кто сможет отвечать на вопросы команды и как с ним связаться?' },
  ]
  return candidates.filter((item) => !task.confirmed?.[item.field])
    .sort((a, b) => (fields.find((field) => field.key === b.field)?.points || 0) - (fields.find((field) => field.key === a.field)?.points || 0))
    .slice(0, 5)
}

async function startTask() {
  if (raw.value.trim().length < 15) { notify('Опишите задачу хотя бы в одном предложении.'); return }
  busy.value = true
  try {
    draft.value = await api('/api/tasks', { method: 'POST', body: { raw: raw.value.trim(), industry: industry.value, deadline: deadline.value } })
    drafts.value = [draft.value, ...drafts.value]
    phase.value = 'interview'
    questionIndex.value = 0
    answerHistory.value = []
    if (aiConfigured.value) {
      try {
        const result = await api(`/api/tasks/${draft.value.id}/analyze`, { method: 'POST' })
        draft.value = result.task
        drafts.value = drafts.value.map((item) => item.id === draft.value.id ? draft.value : item)
        questions.value = result.questions
        aiModel.value = result.model
        if (questions.value.length) phase.value = 'interview'
        notify('AI выделил факты из описания. Проверьте их перед публикацией.')
      } catch (error) {
        questions.value = localQuestions(draft.value)
        aiModel.value = 'Правиловые вопросы'
        notify(`AI-анализ не выполнен: ${explain(error)} Продолжайте с проверенными вопросами.`)
      }
    } else {
      questions.value = localQuestions(draft.value)
      aiModel.value = 'Правиловые вопросы'
      notify('AI-ключ не настроен. Используются открыто обозначенные правиловые вопросы.')
    }
  } catch (error) { notify(explain(error)); phase.value = 'start' }
  finally { busy.value = false }
}

async function resumeDraft(task) {
  try { draft.value = await api(`/api/tasks/${task.id}`); answerHistory.value = await api(`/api/tasks/${task.id}/answers`); phase.value = 'review'; view.value = 'create' }
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
  } catch (error) {
    questions.value = localQuestions(draft.value)
    aiModel.value = 'Правиловые вопросы'
    notify(`${explain(error)} Используются правиловые вопросы.`)
  }
  finally { busy.value = false }
}

async function saveAnswer(skip = false) {
  const current = questions.value[questionIndex.value]
  if (!current) { phase.value = 'review'; return }
  const field = fields.find((item) => item.key === current.field)
  if (!skip && !validField(field, answer.value)) { notify(`Ответьте подробнее: минимум ${field.min} символов.`); return }
  try {
    if (!skip) {
      const result = await api(`/api/tasks/${draft.value.id}/answers`, { method: 'POST', body: { field: current.field, question: current.question, answer: answer.value.trim() } })
      draft.value = result.task
      answerHistory.value.push({ id: result.answer_id, field_key: current.field, question: current.question, answer: answer.value.trim() })
      drafts.value = drafts.value.map((item) => item.id === draft.value.id ? draft.value : item)
    }
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
    draft.value = await api(`/api/tasks/${draft.value.id}`, { method: 'PATCH', body: { title: draft.value.title, category: draft.value.category, industry: draft.value.industry, deadline: draft.value.deadline, fields: draft.value.fields, confirmed: draft.value.confirmed, extras: draft.value.extras, extra_confirmed: draft.value.extra_confirmed } })
    drafts.value = drafts.value.map((item) => item.id === draft.value.id ? draft.value : item)
    tasks.value = tasks.value.map((item) => item.id === draft.value.id ? draft.value : item)
    notify('Черновик сохранён.')
    return draft.value
  } catch (error) { notify(explain(error)); return null }
}

async function goToPack() { if (await saveDraft()) phase.value = 'pack' }

async function publishTask() {
  if (!draft.value.title.trim()) { notify('Укажите название задачи.'); return }
  try {
    if (!await saveDraft()) return
    const publishedTask = await api(`/api/tasks/${draft.value.id}/publish`, { method: 'POST' })
    tasks.value = [publishedTask, ...tasks.value.filter((task) => task.id !== publishedTask.id)]
    drafts.value = drafts.value.filter((task) => task.id !== publishedTask.id)
    selectedTaskId.value = publishedTask.id
    inboxTaskId.value = publishedTask.id
    view.value = 'catalog'
    notify(publishedTask.build?.errors || publishedTask.build?.warnings ? 'Задача опубликована с предупреждениями и доступна командам.' : 'Задача опубликована и доступна командам.')
  } catch (error) { notify(explain(error)) }
}

function startNew() { view.value = 'create'; phase.value = 'start'; raw.value = ''; industry.value = ''; deadline.value = ''; draft.value = null; questions.value = []; answerHistory.value = []; questionIndex.value = 0; answer.value = '' }

function editPackField(key, value) {
  if (key === 'deadline') draft.value = { ...draft.value, deadline: value, extra_confirmed: { ...draft.value.extra_confirmed, deadline: false } }
  else if (key in draft.value.fields) editField(key, value)
  else draft.value = { ...draft.value, extras: { ...draft.value.extras, [key]: value }, extra_confirmed: { ...draft.value.extra_confirmed, [key]: false } }
}

async function confirmPackField(key) {
  const value = key === 'deadline' ? draft.value.deadline : key in draft.value.fields ? draft.value.fields[key] : draft.value.extras?.[key]
  if (!value?.trim()) { notify('Сначала заполните раздел.'); return }
  if (!await saveDraft()) return
  try {
    const body = key in draft.value.fields ? { confirmed: { [key]: true } } : { extra_confirmed: { [key]: true } }
    draft.value = await api(`/api/tasks/${draft.value.id}`, { method: 'PATCH', body })
    drafts.value = drafts.value.map((item) => item.id === draft.value.id ? draft.value : item)
    tasks.value = tasks.value.map((item) => item.id === draft.value.id ? draft.value : item)
    notify('Раздел подтверждён. Рейтинг и версия обновлены.')
  } catch (error) { notify(explain(error)) }
}

async function acceptResponsibility() {
  try {
    draft.value = await api(`/api/tasks/${draft.value.id}`, { method: 'PATCH', body: { extras: { acceptance_responsibility: 'Ответственность за критерии приёмки принимаю' }, extra_confirmed: { acceptance_responsibility: true } } })
    notify('Ответственность за критерии подтверждена.')
  } catch (error) { notify(explain(error)) }
}

async function runHandoff() {
  if (!await saveDraft()) return
  busy.value = true
  try {
    draft.value = { ...draft.value, handoff_result: await api(`/api/tasks/${draft.value.id}/handoff`, { method: 'POST' }) }
    phase.value = 'handoff'
  } catch (error) { notify(explain(error)) }
  finally { busy.value = false }
}

async function focusField(key) {
  focusKey.value = key
  phase.value = fields.some((item) => item.key === key) ? 'review' : 'pack'
  view.value = 'create'
  await nextTick()
  const target = document.querySelector(`#field-${key}, #pack-${key}`)
  target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  target?.focus()
}

async function submitProposal() {
  if (!proposal.idea.trim() || !proposal.plan.trim() || !proposal.deadline.trim()) { notify('Заполните идею, план и срок предложения.'); return }
  try {
    const created = await api('/api/proposals', { method: 'POST', body: { task_id: selectedTask.value.id, ...proposal } })
    proposals.value = [created, ...proposals.value]
    tasks.value = tasks.value.map((task) => task.id === created.task_id ? { ...task, proposal_count: (task.proposal_count || 0) + 1 } : task)
    inboxTaskId.value = selectedTask.value.id
    Object.assign(proposal, { idea: '', plan: '', deadline: '', link: '', questions: '' })
    notify('Предложение отправлено. Бизнес сам примет решение.')
  } catch (error) { notify(explain(error)) }
}

async function setDecision(item, status) {
  try {
    const updated = await api(`/api/proposals/${item.id}/decision`, { method: 'PATCH', body: { status } })
    proposals.value = proposals.value.map((entry) => entry.id === item.id ? updated : entry)
    notify(status === 'accepted' ? 'Команда выбрана вручную.' : status === 'rejected' ? 'Предложение отклонено.' : 'Предложение оставлено на рассмотрении.')
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
  <div v-if="booting" class="boot-screen"><div class="loading-mark"><ForgeIcon name="spark" size="25" /></div><strong>FORGE</strong></div>
  <div v-else-if="!user && !authStarted" class="landing-shell">
    <header class="landing-nav">
      <a class="landing-logo" href="#top" aria-label="FORGE — в начало"><span class="brand-mark">F<span>.</span></span><b>FORGE</b></a>
      <nav aria-label="Разделы страницы"><a href="#how">Как работает</a><a href="#roles">Для кого</a><a href="#principles">Принципы</a></nav>
      <div class="landing-nav-actions"><button class="landing-login" @click="beginAuth('login')">Войти</button><button class="button button-orange" @click="beginAuth('register')">Начать работу <ForgeIcon name="arrow-up-right" size="15" /></button></div>
    </header>
    <main id="top">
      <section class="landing-hero">
        <div class="landing-hero-copy"><span class="eyebrow">ПРАКТИЧЕСКИЕ ЗАДАЧИ · AI SANA</span><h1>Хорошее решение<br>начинается с <em>ясной задачи.</em></h1><p>FORGE помогает бизнесу описать реальную проблему и передать её команде с понятными требованиями, материалами и критериями результата.</p><div class="landing-hero-actions"><button class="button button-orange" @click="beginAuth('register')">Создать аккаунт <ForgeIcon name="arrow-up-right" size="15" /></button><a class="landing-text-link" href="#how">Посмотреть, как это устроено <ForgeIcon name="arrow-down" size="14" /></a></div><div class="landing-proof"><span class="proof-mark"><ForgeIcon name="spark" size="15" /></span><span>От первого описания до готового к передаче Task Pack</span></div></div>
        <div class="landing-hero-visual" aria-label="Путь задачи в FORGE">
          <div class="visual-orbit orbit-one"></div><div class="visual-orbit orbit-two"></div><div class="visual-core"><span>F.</span><small>ЗАДАЧА<br>ГОТОВА К СТАРТУ</small></div>
          <div class="visual-node node-problem"><i>01</i><span>Проблема</span><b>Что нужно изменить?</b></div><div class="visual-node node-pack"><i>02</i><span>Task Pack</span><b>Контекст · данные · успех</b></div><div class="visual-node node-team"><i>03</i><span>Команда</span><b>План и предложение</b></div><div class="visual-caption"><span class="live-dot"></span> ПОНЯТНЫЙ МАРШРУТ РАБОТЫ</div>
        </div>
        <div class="landing-scroll-note">ПРОКРУТИТЕ, ЧТОБЫ УЗНАТЬ БОЛЬШЕ <ForgeIcon name="arrow-down" size="13" /></div>
      </section>

      <section class="landing-intro" id="how"><div class="landing-section-kicker"><span>01 / ЧТО ТАКОЕ FORGE</span><i></i><span>ОТ ИДЕИ К ДЕЙСТВИЮ</span></div><div class="landing-intro-grid"><h2>Меньше догадок.<br><em>Больше ясности</em><br>до старта.</h2><div><p>FORGE — рабочая платформа, которая превращает бизнес-запрос в структурированное практическое задание для команд. Автор не просто публикует текст: он уточняет детали, подтверждает факты и видит, чего пока не хватает для уверенного старта.</p><p>Команда изучает описание и открытые замечания, задаёт вопросы и отправляет свой план. Бизнес сравнивает подходы и сам принимает решение.</p><button class="inline-arrow" @click="beginAuth('register')">Попробовать FORGE <ForgeIcon name="arrow-up-right" size="15" /></button></div></div></section>

      <section class="landing-flow"><div class="landing-section-heading"><span class="eyebrow">02 / ОДИН ПОНЯТНЫЙ ПРОЦЕСС</span><h2>От описания до передачи<br>задачи — <em>по шагам.</em></h2><p>Каждый этап помогает снять конкретную неопределённость до того, как команда начнёт работу.</p></div><div class="landing-flow-grid">
        <article><span class="flow-number">01</span><div class="flow-glyph"><ForgeIcon name="arrow-up-right" size="20" /></div><h3>Опишите ситуацию</h3><p>Расскажите своими словами, что происходит, где возникает проблема и какого изменения вы ждёте.</p><small>ЧЕРНОВИК СОХРАНЯЕТСЯ В КАБИНЕТЕ</small></article>
        <article><span class="flow-number">02</span><div class="flow-glyph"><ForgeIcon name="search" size="20" /></div><h3>Уточните важное</h3><p>Разберите контекст, доступные данные, ограничения, пользователей и критерии успешного результата.</p><small>AI-ПОДСКАЗКИ НУЖНО ПРОВЕРИТЬ</small></article>
        <article><span class="flow-number">03</span><div class="flow-glyph"><ForgeIcon name="document" size="20" /></div><h3>Соберите Task Pack</h3><p>Проверьте структурированную карточку, источники сведений и замечания компилятора готовности.</p><small>ОЦЕНКА ОБЪЯСНЯЕТСЯ ПО ПОЛЯМ</small></article>
        <article><span class="flow-number">04</span><div class="flow-glyph"><ForgeIcon name="arrow-right" size="20" /></div><h3>Передайте командам</h3><p>Опубликуйте задачу, изучите планы и прототипы команд и вручную выберите дальнейший формат работы.</p><small>РЕШЕНИЕ ОСТАЁТСЯ ЗА БИЗНЕСОМ</small></article>
      </div></section>

      <section class="landing-roles" id="roles"><div class="landing-section-heading"><span class="eyebrow">03 / ДВА ВЗГЛЯДА НА ОДНУ ЗАДАЧУ</span><h2>Вы приносите опыт.<br>Платформа помогает <em>свести его вместе.</em></h2></div><div class="landing-role-grid"><article class="role-card role-business"><span class="eyebrow">ДЛЯ БИЗНЕСА</span><div class="role-illustration business-illustration"><span class="role-line"></span><b>ЗАДАЧА<br><em>01</em></b><span class="role-chip">контекст</span><span class="role-chip">результат</span><span class="role-chip">данные</span></div><h3>Объяснить проблему<br>и найти подход</h3><p>Создайте задачу, заполните карточку, проверьте готовность, опубликуйте её и сравните предложения команд. Вы контролируете описание и решение.</p><button class="inline-arrow" @click="beginAuth('register'); authForm.role = 'business'">Я представляю бизнес <ForgeIcon name="arrow-up-right" size="15" /></button></article><article class="role-card role-team"><span class="eyebrow">ДЛЯ КОМАНД</span><div class="role-illustration team-illustration"><div class="avatar-stack"><i>UX</i><i>AI</i><i>DA</i></div><span class="team-connector"><ForgeIcon name="arrow-right" size="25" /></span><b>ИДЕЯ<br><em>В ПРОТОТИП</em></b></div><h3>Найти задачу<br>для своих навыков</h3><p>Изучайте опубликованные задания и их открытые замечания, отправляйте идею и план работы, добавляйте срок и ссылку на прототип.</p><button class="inline-arrow" @click="beginAuth('register'); authForm.role = 'team'">Я представляю команду <ForgeIcon name="arrow-up-right" size="15" /></button></article></div></section>

      <section class="landing-detail" id="principles"><div class="detail-side"><span class="eyebrow">04 / ЧТО ПОМОГАЕТ РАБОТАТЬ УВЕРЕННЕЕ</span><h2>Понятность —<br>это <em>функция.</em></h2><p>FORGE показывает не только карточку задачи, но и логику её подготовки.</p><button class="button button-orange" @click="beginAuth('register')">Начать с FORGE <ForgeIcon name="arrow-up-right" size="15" /></button></div><div class="detail-list"><article><b>01</b><div><h3>Проверяемая готовность</h3><p>Компилятор считает баллы по подтверждённым полям и показывает ошибки, предупреждения и следующий полезный шаг. Оценка — ориентир по полноте, а не гарантия успеха проекта.</p></div><ForgeIcon name="arrow-up-right" size="15" /></article><article><b>02</b><div><h3>AI с понятной ролью</h3><p>При подключённом серверном ключе AI помогает разобрать текст и сформулировать вопросы. Его предложения не становятся подтверждёнными фактами без проверки автором. Без ключа работают явно обозначенные вопросы по правилам.</p></div><ForgeIcon name="arrow-up-right" size="15" /></article><article><b>03</b><div><h3>Честная передача</h3><p>Handoff Test помогает заметить, что ещё нужно другой команде для старта. Опубликованная задача может содержать замечания — они остаются видны командам.</p></div><ForgeIcon name="arrow-up-right" size="15" /></article><article><b>04</b><div><h3>Решение принимает человек</h3><p>Команды отправляют идеи и планы; бизнес сам сравнивает их и вручную выбирает одну, несколько или ни одной. Алгоритм не назначает победителя.</p></div><ForgeIcon name="arrow-up-right" size="15" /></article></div></section>

      <section class="landing-faq"><div><span class="eyebrow">05 / ПЕРЕД СТАРТОМ</span><h2>Частые вопросы</h2><p>Коротко о том, как устроена работа в FORGE.</p></div><div class="faq-list"><details><summary>Нужен ли AI, чтобы пользоваться платформой?<ForgeIcon name="plus" size="16" /></summary><p>Нет. Создание задач, оценка готовности по правилам, Task Pack, публикация и отклики доступны без AI. Если OpenAI API не настроен, интерфейс прямо сообщает, что вместо AI-интервью используются правиловые вопросы.</p></details><details><summary>Можно ли опубликовать неидеально заполненную задачу?<ForgeIcon name="plus" size="16" /></summary><p>Да. Платформа показывает открытые ошибки и предупреждения, чтобы автор мог осознанно решить, готов ли передать задание в таком виде. Замечания также видны командам.</p></details><details><summary>Кто выбирает команду для работы?<ForgeIcon name="plus" size="16" /></summary><p>Представитель бизнеса. FORGE помогает изучить предложения, но не ранжирует их как автоматическое решение и не выбирает победителя.</p></details><details><summary>Кому подходит платформа?<ForgeIcon name="plus" size="16" /></summary><p>Бизнесу, которому нужно ясно описать практическую задачу, и командам, которые хотят предложить решение на основе своих навыков.</p></details></div></section>

      <section class="landing-cta"><div><span class="eyebrow">ГОТОВЫ НАЧАТЬ?</span><h2>Сделайте следующий шаг<br><em>понятным для всех.</em></h2><p>Создайте аккаунт и выберите, с какой стороны вы хотите работать с задачами.</p></div><button class="button button-orange" @click="beginAuth('register')">Создать аккаунт в FORGE <ForgeIcon name="arrow-up-right" size="15" /></button><span class="cta-orbit cta-orbit-a"></span><span class="cta-orbit cta-orbit-b"></span></section>
    </main>
    <footer class="landing-footer"><a class="landing-logo" href="#top"><span class="brand-mark">F<span>.</span></span><b>FORGE</b></a><span>AI Sana · Практические задачи для совместной работы</span><button @click="beginAuth('login')">Уже есть аккаунт? Войти <ForgeIcon name="arrow-up-right" size="14" /></button></footer>
  </div>
  <div v-else-if="!user" class="auth-shell">
    <div class="auth-brand"><div class="brand-mark">F<span>.</span></div><span>FORGE</span></div>
    <div class="auth-layout">
      <section class="auth-story"><span class="eyebrow">AI SANA · ПРАКТИЧЕСКИЕ ЗАДАНИЯ</span><h1>От сырой идеи к задаче, готовой для команды.</h1><p>FORGE проверяет полноту постановки, собирает Task Pack и помогает передать работу студенческой команде без лишней неопределённости.</p></section>
      <section class="auth-card"><span class="eyebrow accent-text">ДОБРО ПОЖАЛОВАТЬ</span><h2>{{ authMode === 'login' ? 'Войти в FORGE' : 'Создать аккаунт' }}</h2><p>{{ authMode === 'login' ? 'Продолжите работу со своими задачами и откликами.' : 'Выберите свою роль и начните работать с реальными проектами.' }}</p><div class="auth-switch"><button :class="{ active: authMode === 'login' }" @click="authMode = 'login'">Вход</button><button :class="{ active: authMode === 'register' }" @click="authMode = 'register'">Регистрация</button></div>
        <form class="auth-form" @submit.prevent="authenticate"><template v-if="authMode === 'register'"><div class="role-picker"><button type="button" :class="{ active: authForm.role === 'business' }" @click="authForm.role = 'business'"><strong>Бизнес</strong><span>Публикую задачи</span></button><button type="button" :class="{ active: authForm.role === 'team' }" @click="authForm.role = 'team'"><strong>Команда</strong><span>Предлагаю решения</span></button></div><label>Ваше имя<input v-model="authForm.name" autocomplete="name" required minlength="2" placeholder="Как к вам обращаться" /></label><label>{{ authForm.role === 'business' ? 'Организация' : 'Название команды' }}<input v-model="authForm.organization" required minlength="2" :placeholder="authForm.role === 'business' ? 'Название компании' : 'Название команды'" /></label><label v-if="authForm.role === 'team'">Навыки команды<input v-model="authForm.skills" required placeholder="Например: Python, UX, Data" /><small>Через запятую, хотя бы один навык</small></label></template><label>Электронная почта<input v-model="authForm.email" type="email" autocomplete="email" required placeholder="you@example.com" /></label><label>Пароль<input v-model="authForm.password" type="password" :autocomplete="authMode === 'register' ? 'new-password' : 'current-password'" required :minlength="authMode === 'register' ? 10 : 1" placeholder="Минимум 10 символов при регистрации" /></label><button class="button button-orange full" type="submit" :disabled="authBusy">{{ authBusy ? 'Подождите...' : authMode === 'login' ? 'Войти' : 'Зарегистрироваться' }} <ForgeIcon :name="authMode === 'login' ? 'arrow-right' : 'arrow-up-right'" size="15" /></button></form>
      </section>
    </div><div v-if="toast" role="status" class="toast">{{ toast }}<button aria-label="Закрыть уведомление" @click="toast = ''"><ForgeIcon name="close" size="15" /></button></div>
  </div>
  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark">F<span>.</span></div><span>FORGE</span></div>
      <div class="side-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <nav aria-label="Основная навигация">
        <button v-if="isAdmin" class="nav-item" :class="{ active: view === 'admin' }" @click="view = 'admin'"><span class="nav-icon"><ForgeIcon name="chart" /></span> Панель управления</button>
        <button v-if="isBusiness" class="nav-item" :class="{ active: view === 'workspace' }" @click="view = 'workspace'"><span class="nav-icon"><ForgeIcon name="folder" /></span> Обзор задач <span class="nav-count">{{ workspaceTasks.length }}</span></button>
        <button v-if="isBusiness" class="nav-item" :class="{ active: view === 'create' }" @click="view = 'create'"><span class="nav-icon"><ForgeIcon name="plus" /></span> Создать задачу</button>
        <button v-if="!isAdmin" class="nav-item" :class="{ active: view === 'catalog' }" @click="showCatalog"><span class="nav-icon"><ForgeIcon name="grid" /></span> Каталог <span class="nav-count">{{ published.length }}</span></button>
        <button v-if="!isAdmin" class="nav-item" :class="{ active: view === 'inbox' }" @click="view = 'inbox'"><span class="nav-icon"><ForgeIcon name="message" /></span> {{ isBusiness ? 'Предложения' : 'Мои отклики' }} <span class="nav-count">{{ pendingCount }}</span></button>
        <button v-if="!isBusiness && !isAdmin" class="nav-item" :class="{ active: view === 'profile' }" @click="view = 'profile'"><span class="nav-icon"><ForgeIcon name="person" /></span> Профиль</button>
      </nav>
      <div class="sidebar-bottom"><span class="little-star"><ForgeIcon name="spark" size="23" /></span><p>Хорошие решения начинаются с ясной задачи.</p><small>AI Sana · FORGE</small></div>
    </aside>

    <main class="main">
      <header class="topbar"><div class="mobile-brand"><div class="brand"><div class="brand-mark">F<span>.</span></div><span>FORGE</span></div></div><span class="topbar-path">FORGE <span>/</span> {{ view === 'admin' ? 'Управление' : view === 'workspace' ? 'Обзор задач' : view === 'create' ? 'Создание задачи' : view === 'catalog' ? 'Каталог задач' : view === 'profile' ? 'Профиль команды' : 'Предложения' }}</span><div class="topbar-right"><span v-if="isBusiness" class="demo-badge" :class="{ 'ai-off': !aiConfigured }"><span /> {{ aiConfigured ? 'AI подключён' : 'AI не настроен' }}</span><span class="topbar-user">{{ user.name }} · {{ user.organization }}</span><button class="logout-button" @click="logout">Выйти</button></div></header>
      <div v-if="!isAdmin && bootstrapStatus?.available" class="bootstrap-banner"><div><strong>Первый администратор FORGE</strong><span>{{ bootstrapStatus.configured ? 'Введите секрет из .env, чтобы открыть панель управления.' : 'Задайте ADMIN_BOOTSTRAP_TOKEN в .env и перезапустите API.' }}</span></div><form v-if="bootstrapStatus.configured" @submit.prevent="bootstrapAdmin"><input v-model="bootstrapSecret" type="password" autocomplete="off" aria-label="Секрет администратора" placeholder="Секрет администратора" /><button class="button button-dark" :disabled="adminBusy" type="submit">Назначить себя <ForgeIcon name="arrow-right" size="14" /></button></form></div>

      <div v-if="loading" class="page loading-page"><div class="loading-state"><div class="loading-mark"><ForgeIcon name="spark" size="25" /></div><strong>Загружаем FORGE...</strong></div></div>
      <div v-else-if="loadError" class="page error-page"><h1>Не удалось подключиться к API</h1><p>{{ loadError }}</p><p>Запустите FastAPI на порту 8000 и повторите попытку.</p><button class="button button-dark" @click="load">Повторить <ForgeIcon name="arrow-right" size="14" /></button></div>

      <AdminPanel v-else-if="view === 'admin' && adminOverview" :overview="adminOverview" :busy="adminBusy" @refresh="load" @role="changeUserRole" />

      <div v-else-if="view === 'workspace' && isBusiness" class="page workspace-page"><div class="workspace-hero"><div class="workspace-hero-copy"><span class="eyebrow">ВАШЕ РАБОЧЕЕ ПРОСТРАНСТВО</span><h1>Превратите идею<br>в задачу, <em>понятную всем.</em></h1><p>Один маршрут: опишите проблему, уточните детали, проверьте готовность и передайте её команде.</p><div class="workspace-hero-actions"><button class="button button-orange" @click="startNew">Создать задачу <ForgeIcon name="arrow-up-right" size="15" /></button><button v-if="workspaceTasks.length" class="button button-ghost" @click="resumeDraft(workspaceTasks[0])">Продолжить работу <ForgeIcon name="arrow-right" size="14" /></button></div></div><div class="workspace-hero-art" aria-hidden="true" /></div><div class="page-heading"><div><span class="eyebrow accent-text">WORKSPACE</span><h1>Ваши задачи.</h1><p>От первой формулировки до передачи команде — все задачи и пробелы в одном месте.</p></div><button class="button button-orange" @click="startNew"><ForgeIcon name="plus" size="16" /> Создать задачу</button></div><div class="workspace-stats"><div><span>Всего задач</span><strong>{{ workspaceTasks.length }}</strong></div><div><span>Средняя готовность</span><strong>{{ averageScore }}<small>/100</small></strong></div><div><span>Требуют уточнений</span><strong>{{ attentionCount }}</strong></div><div><span>Новые предложения</span><strong>{{ pendingCount }}</strong></div></div><div v-if="workspaceTasks.length" class="workspace-list"><article v-for="task in workspaceTasks" :key="task.id" class="workspace-item"><div><span class="eyebrow">{{ task.published ? 'ОПУБЛИКОВАНА' : 'ЧЕРНОВИК' }} · {{ task.task_pack?.version }}</span><h2>{{ task.title }}</h2><p>{{ task.industry || task.category }} · {{ task.build?.errors }} ошибок · {{ task.build?.warnings }} предупреждений · {{ proposalCount(task) }} предложений</p></div><div class="workspace-item-actions"><span class="build-pill" :class="`build-${task.build?.status}`">{{ task.build?.status === 'success' ? 'Готова' : task.build?.status === 'warning' ? 'Есть уточнения' : 'Нужны детали' }}</span><strong>{{ scoreTask(task).score }}<small>/100</small></strong><button class="button button-ghost" @click="resumeDraft(task)">Открыть <ForgeIcon name="arrow-right" size="14" /></button></div></article></div><div v-else class="empty-state">Пока нет задач. Опишите первую проблему — FORGE сохранит черновик и покажет, что нужно уточнить.</div></div>

      <div v-else-if="view === 'create'" class="page create-page">
        <div class="page-heading"><div><span class="eyebrow accent-text">{{ phase === 'start' ? 'NEW TASK' : phase === 'interview' ? 'READINESS LAB' : phase === 'review' ? 'TASK BLUEPRINT' : phase === 'pack' ? 'TASK PACK EDITOR' : 'HANDOFF TEST' }}</span><h1>{{ phase === 'start' ? 'Начните с проблемы.' : phase === 'interview' ? 'Уточняем постановку.' : phase === 'review' ? 'Исправьте пробелы.' : phase === 'pack' ? 'Соберите Task Pack.' : 'Проверьте передачу.' }}</h1><p>{{ phase === 'start' ? 'Опишите ситуацию своими словами. Система покажет начальную готовность и путь к понятной задаче.' : phase === 'interview' ? 'Один вопрос за раз. Ответы сохраняются как подтверждённые сведения.' : phase === 'review' ? 'Диагностики связаны с разделами карточки. Подтверждайте только проверенные факты.' : phase === 'pack' ? 'Проверьте рабочие материалы, критерии приёмки и детали сотрудничества.' : 'Проверка использует только подтверждённый Task Pack.' }}</p></div><button v-if="phase !== 'start'" class="button button-ghost" @click="startNew"><ForgeIcon name="plus" size="16" /> Новая задача</button></div>
        <div v-if="draft" class="flow-steps" aria-label="Этапы создания задачи"><button :class="{ active: phase === 'interview' }" :aria-current="phase === 'interview' ? 'step' : undefined" @click="phase = 'interview'">1. Ответы</button><button :class="{ active: phase === 'review' }" :aria-current="phase === 'review' ? 'step' : undefined" @click="phase = 'review'">2. Карточка</button><button :class="{ active: phase === 'pack' }" :aria-current="phase === 'pack' ? 'step' : undefined" @click="goToPack">3. Материалы</button><button :class="{ active: phase === 'handoff' }" :aria-current="phase === 'handoff' ? 'step' : undefined" @click="runHandoff">4. Проверка</button></div>

        <div v-if="phase === 'start'" class="start-grid">
          <div class="start-card"><div class="card-heading"><span class="round-icon"><ForgeIcon name="spark" size="18" /></span><div><strong>Опишите вашу задачу</strong><span>Достаточно одного абзаца, даже если детали ещё неизвестны.</span></div></div><textarea v-model="raw" class="hero-textarea" maxlength="5000" placeholder="Например: хотим использовать AI, чтобы улучшить обработку обращений клиентов..." /><div class="new-task-meta"><label>Отрасль или направление<input v-model="industry" maxlength="80" placeholder="Например: клиентский сервис" /></label><label>Предполагаемый срок<input v-model="deadline" maxlength="100" placeholder="Например: 10 дней" /></label></div><div class="textarea-footer"><span>{{ raw.length }} / 5000 символов</span><button class="button button-orange" :disabled="busy" @click="startTask">{{ busy ? 'Анализируем...' : 'Создать и проверить задачу' }} <ForgeIcon name="arrow-right" size="15" /></button></div></div>
          <div class="intro-panel"><span class="eyebrow">ПУТЬ ЗАДАЧИ</span><div class="intro-step"><b>01</b><div><strong>Проверим полноту</strong><span>Детерминированный рейтинг и диагностики покажут критические пробелы.</span></div></div><div class="intro-step"><b>02</b><div><strong>Соберём материалы</strong><span>Соберите материалы, результат и критерии приёмки из подтверждённых фактов.</span></div></div><div class="intro-step"><b>03</b><div><strong>Проверим передачу</strong><span>Проверьте, сможет ли независимая команда начать работу.</span></div></div><div class="ai-hint" v-if="!aiConfigured">OpenAI пока не настроен. Вопросы формируются правилами и явно помечаются; рабочие данные сохраняются. Добавьте ключ в серверный .env для AI-анализа.</div><div class="ai-hint" v-else>AI-анализ подключён. Подсказки требуют ручного подтверждения.</div></div>
        </div>
        <section v-if="phase === 'start' && drafts.length" class="drafts-section"><div class="drafts-head"><span class="eyebrow">СОХРАНЁННЫЕ ЧЕРНОВИКИ</span><span>{{ drafts.length }} задач</span></div><div class="drafts-grid"><button v-for="task in drafts.slice(0, 6)" :key="task.id" class="draft-resume" @click="resumeDraft(task)"><span class="draft-icon"><ForgeIcon name="arrow-up-right" size="15" /></span><strong>{{ task.title }}</strong><small>{{ scoreTask(task).score }} / 100 · Продолжить</small></button></div></section>

        <div v-else-if="phase === 'interview' && draft" class="workspace-grid">
          <section class="work-card interview-card"><div class="work-card-head"><div><span class="eyebrow">{{ aiModel === 'Правиловые вопросы' ? 'ПРАВИЛОВОЕ ИНТЕРВЬЮ' : 'AI ИНТЕРВЬЮ' }}</span><h2>Давайте уточним детали</h2></div><span class="step-count">{{ busy ? 'Подготовка' : `${Math.min(questionIndex + 1, questions.length)} / ${questions.length}` }}</span></div>
            <div v-if="busy" class="loading-state"><div class="loading-mark"><ForgeIcon name="spark" size="25" /></div><strong>Анализируем описание...</strong><span>Подбираем вопросы по недостающим сведениям</span></div>
            <template v-else-if="questions[questionIndex]"><div class="interview-chat"><div class="ai-message"><span class="ai-avatar">F</span><div><span class="message-name">{{ aiModel === 'Правиловые вопросы' ? 'FORGE · ПРАВИЛА' : 'FORGE AI' }}</span><p>Уточните недостающие детали, чтобы команде было легче начать работу.</p></div></div><div class="question-box"><span class="question-number">ВОПРОС {{ questionIndex + 1 }}</span><h3>{{ questions[questionIndex].question }}</h3><span class="gain">До +{{ fields.find((field) => field.key === questions[questionIndex].field)?.points }} баллов</span><p class="question-why">Почему важно: {{ draft.build?.diagnostics.find((item) => item.field === questions[questionIndex].field && item.severity === 'error')?.consequence || 'Ответ снимет неопределённость для команды.' }}</p></div></div><textarea v-model="answer" class="answer-textarea" placeholder="Напишите конкретный ответ..." /><div class="interview-actions"><button class="text-button" @click="saveAnswer(true)">Пропустить вопрос</button><button class="button button-dark" @click="saveAnswer(false)">Сохранить ответ <ForgeIcon name="arrow-right" size="15" /></button></div><div class="interview-bottom"><span>Источник вопросов: {{ aiModel || 'AI' }}</span><button @click="phase = 'review'">Перейти к карточке <ForgeIcon name="arrow-right" size="14" /></button></div><div v-if="answerHistory.length" class="answer-history"><span class="eyebrow">УЖЕ УТОЧНЕНО</span><div v-for="item in answerHistory.slice(-3)" :key="item.id"><strong>{{ item.question }}</strong><p>{{ item.answer }}</p></div></div></template>
            <div v-else class="done-state"><div class="done-icon"><ForgeIcon name="check" size="20" /></div><h3>Интервью завершено</h3><p>Теперь проверьте сформированную карточку.</p><button class="button button-orange" @click="phase = 'review'">Открыть карточку <ForgeIcon name="arrow-right" size="14" /></button></div>
          </section><ReadinessCompiler :task="draft" compact @fix="focusField" />
        </div>

        <div v-else-if="phase === 'review' && draft" class="workspace-grid">
          <section class="work-card review-card">
            <div class="work-card-head"><div><span class="eyebrow">TASK BLUEPRINT</span><h2>Карточка задачи</h2></div><div class="review-head-actions"><button class="text-button" @click="continueInterview"><ForgeIcon name="spark" size="14" /> Уточнить ещё</button><span class="review-count">{{ confirmedCount }} / 9 подтверждено</span></div></div>
            <div class="form-row"><label>Название задачи<input v-model="draft.title" maxlength="140" placeholder="Короткое название" /></label><label>Тема<select v-model="draft.category"><option v-for="category in categories" :key="category">{{ category }}</option></select></label></div>
            <div class="fields-list"><div v-for="field in fields" :key="field.key" class="field-block"><div class="field-header"><label :for="`field-${field.key}`">{{ field.label }} <span>+{{ field.points }}</span></label><span class="field-state" :class="{ 'is-confirmed': draft.confirmed[field.key] && validField(field, draft.fields[field.key]) }"><ForgeIcon v-if="draft.confirmed[field.key] && validField(field, draft.fields[field.key])" name="check" size="13" /> {{ draft.confirmed[field.key] && validField(field, draft.fields[field.key]) ? 'Подтверждено' : 'Не подтверждено' }}</span></div><textarea :id="`field-${field.key}`" :value="draft.fields[field.key]" :placeholder="field.hint" rows="2" @input="editField(field.key, $event.target.value)" /><div v-if="draft.ai_evidence?.[field.key]" class="ai-source">AI-подсказка · источник: «{{ draft.ai_evidence[field.key] }}»</div><div class="field-footer"><small>{{ field.hint }}</small><button v-if="!draft.confirmed[field.key]" @click="confirmField(field.key)">Подтвердить <ForgeIcon name="check" size="13" /></button></div></div></div>
            <div class="publish-footer"><div><strong>Далее — рабочий пакет</strong><span>Дополните данные, критерии и правила взаимодействия перед передачей команде.</span></div><div class="publish-buttons"><button class="button button-ghost" @click="saveDraft">Сохранить</button><button class="button button-orange" @click="goToPack">Открыть Task Pack <ForgeIcon name="arrow-right" size="15" /></button></div></div>
          </section><div class="right-rail"><ScorePanel :task="draft" @handoff="runHandoff" /><ReadinessCompiler :task="draft" compact @fix="focusField" /></div>
        </div>
        <div v-else-if="phase === 'pack' && draft" class="pack-page"><div class="pack-topline"><button class="back-link" @click="phase = 'review'"><ForgeIcon name="arrow-left" size="14" /> Вернуться к Blueprint</button><span class="build-pill" :class="`build-${draft.build?.status}`">{{ draft.build?.errors }} ошибок · {{ draft.build?.warnings }} предупреждений</span></div><TaskPackEditor :task="draft" :focus-key="focusKey" @edit="editPackField" @confirm="confirmPackField" @accept="acceptResponsibility" @save="saveDraft" @handoff="runHandoff" /></div>
        <div v-else-if="phase === 'handoff' && draft" class="handoff-page"><button class="back-link" @click="phase = 'pack'"><ForgeIcon name="arrow-left" size="14" /> Вернуться к Task Pack</button><HandoffPanel :task="draft" :busy="busy" @run="runHandoff" @fix="focusField" @publish="publishTask" /></div>
      </div>

      <div v-else-if="view === 'catalog'" class="page catalog-page"><div class="page-heading catalog-heading"><div><span class="eyebrow accent-text">КАТАЛОГ ЗАДАЧ</span><h1>Реальные задачи для команд.</h1><p>Все опубликованные задачи видны независимо от рейтинга. Перед откликом изучите Task Pack и открытые предупреждения.</p></div><div class="catalog-total"><strong>{{ published.length }}</strong><span>задач в каталоге</span></div></div>
        <div v-if="selectedTask" class="detail-layout"><div class="detail-main"><button class="back-link" @click="selectedTaskId = null"><ForgeIcon name="arrow-left" size="14" /> Назад к каталогу</button><div class="detail-card"><div class="detail-head"><span class="topic-label">{{ selectedTask.industry || selectedTask.category }} · {{ selectedTask.owner }}</span><span class="status" :class="`status-${toneFor(selectedTask)}`"><span class="status-dot" />{{ scoreTask(selectedTask).level }}</span></div><h2>{{ selectedTask.title }}</h2><div class="detail-score"><strong>{{ scoreTask(selectedTask).score }}</strong><span>/ 100 готовность к работе · {{ selectedTask.task_pack?.version }}</span></div><div class="detail-signals"><span>{{ selectedTask.build?.errors }} критических пробелов</span><span>{{ selectedTask.build?.warnings }} предупреждений</span><span>Handoff Test · {{ selectedTask.handoff_result?.passed ?? '—' }}/5</span><span>{{ selectedTask.confirmed?.data ? 'Данные подтверждены' : 'Данные требуют уточнения' }}</span></div><div class="public-pack"><section v-for="section in selectedTask.task_pack?.sections" :key="section.name"><h3>{{ section.name }}</h3><div v-for="item in section.items" :key="item.key" class="public-pack-row"><strong>{{ item.label }}</strong><p>{{ item.confirmed ? item.value : 'Требуется подтверждение бизнеса' }}</p></div></section></div><div v-if="selectedTask.build?.errors || selectedTask.build?.warnings" class="public-warnings"><h3>Открытые замечания</h3><p v-for="item in selectedTask.build.diagnostics.filter((entry) => entry.severity !== 'passed')" :key="item.code"><strong>{{ item.code }} · {{ item.title }}</strong> — {{ item.consequence }}</p></div></div></div>
          <aside v-if="!isBusiness" class="proposal-card"><span class="eyebrow">ОТКЛИК КОМАНДЫ</span><h2>Предложите решение</h2><p><strong>{{ user.team?.name }}</strong> · {{ user.team?.skills.join(', ') }}. Выбор команды остаётся за бизнесом.</p><form @submit.prevent="submitProposal"><label>Идея решения<textarea v-model="proposal.idea" required minlength="12" placeholder="Как вы решите задачу?" rows="3" /></label><label>План работы<textarea v-model="proposal.plan" required minlength="12" placeholder="Этапы работы и проверки" rows="3" /></label><label>Срок<input v-model="proposal.deadline" required placeholder="Например, 14 дней" /></label><label>Ссылка на прототип<input v-model="proposal.link" type="url" placeholder="https://example.com/prototype" /></label><label>Вопросы бизнесу<textarea v-model="proposal.questions" placeholder="Что ещё необходимо уточнить?" rows="2" /></label><button class="button button-orange full" type="submit">Отправить предложение <ForgeIcon name="arrow-right" size="15" /></button></form></aside>
          <aside v-else class="proposal-card"><span class="eyebrow">ЗАДАЧА БИЗНЕСА</span><h2>Отклики команд</h2><p>Предложения доступны владельцу задачи в личном кабинете.</p><button v-if="selectedTask.owner_id === user.id" class="button button-dark full" @click="inboxTaskId = selectedTask.id; view = 'inbox'">Смотреть предложения <ForgeIcon name="arrow-right" size="14" /></button></aside>
        </div>
        <template v-else><div class="filters catalog-filters"><input v-model="query" type="search" aria-label="Поиск задач" placeholder="Поиск по названию, компании, описанию..." /><select v-model="topicFilter" aria-label="Фильтр по теме"><option>Все темы</option><option v-for="category in categories" :key="category">{{ category }}</option></select><select v-model="levelFilter" aria-label="Фильтр по готовности"><option>Любой уровень</option><option v-for="level in levels" :key="level">{{ level }}</option></select><select v-model="dataFilter" aria-label="Фильтр по данным"><option>Любые данные</option><option>Данные подтверждены</option><option>Данные не подтверждены</option></select><select v-model="deadlineFilter" aria-label="Фильтр по сроку"><option>Любой срок</option><option>Срок указан</option><option>Срок не указан</option></select><span class="filter-result">Показано {{ filtered.length }} из {{ published.length }}</span></div><div class="task-grid"><button v-for="task in filtered" :key="task.id" class="task-card" @click="selectedTaskId = task.id"><div class="task-card-top"><span class="topic-label">{{ task.industry || task.category }} · {{ task.owner }}</span><span class="task-card-arrow"><ForgeIcon name="arrow-up-right" size="18" /></span></div><h2>{{ task.title }}</h2><p>{{ task.fields.need || task.fields.context }}</p><div class="catalog-meta"><span><ForgeIcon v-if="task.confirmed?.data" name="check" size="12" /> {{ task.confirmed?.data ? 'Данные подтверждены' : 'Данные требуют уточнения' }}</span><span>{{ task.deadline || 'Срок не указан' }}</span><span>{{ task.handoff_result ? `Handoff ${task.handoff_result.passed}/5` : 'Handoff не проведён' }}</span><span>{{ task.build?.errors }} ошибок · {{ task.build?.warnings }} предупреждений</span><span>{{ task.proposal_count || 0 }} откликов</span></div><div class="task-card-bottom"><div><strong>{{ scoreTask(task).score }}</strong><span>/ 100 готовность</span></div><span class="status" :class="`status-${toneFor(task)}`"><span class="status-dot" />{{ scoreTask(task).level }}</span></div></button></div><div v-if="!filtered.length" class="empty-state">{{ published.length ? 'По выбранным фильтрам задач нет. Измените поиск или параметры.' : 'Пока нет опубликованных задач. Бизнес может создать первую задачу в конструкторе.' }}</div></template>
      </div>

      <div v-else-if="view === 'profile' && !isBusiness" class="page profile-page"><div class="page-heading"><div><span class="eyebrow accent-text">ПРОФИЛЬ КОМАНДЫ</span><h1>{{ user.team?.name }}</h1><p>Расскажите бизнесу о вашей команде и поддерживайте навыки в актуальном состоянии.</p></div></div><div class="profile-grid"><form class="work-card profile-form" @submit.prevent="saveProfile"><label>Название команды<input v-model="profile.name" required minlength="2" maxlength="140" /></label><label>Навыки через запятую<input v-model="profile.skills" required placeholder="Python, UX, Data" /></label><button class="button button-orange" type="submit">Сохранить профиль <ForgeIcon name="arrow-right" size="14" /></button></form><div class="work-card profile-points"><span class="eyebrow">ПРОГРЕСС КОМАНДЫ</span><strong>{{ user.team?.points || 0 }}</strong><p>Баллы начисляются после подтверждения этапа бизнесом.</p></div></div></div>
      <div v-else class="page inbox-page"><div class="page-heading"><div><span class="eyebrow accent-text">{{ isBusiness ? 'РЕШЕНИЕ БИЗНЕСА' : 'МОИ ОТКЛИКИ' }}</span><h1>{{ isBusiness ? 'Сравнение предложений.' : 'Ваши предложения.' }}</h1><p>{{ isBusiness ? 'Сравните подходы и вручную выберите одну, несколько команд или никого.' : 'Следите за решениями бизнеса и прогрессом команды.' }}</p></div></div><div class="inbox-layout"><aside class="task-selector"><span class="eyebrow">ЗАДАЧИ</span><button v-for="task in inboxTasks" :key="task.id" :class="{ selected: inboxTaskId === task.id }" @click="inboxTaskId = task.id"><span>{{ task.title }}</span><b>{{ proposalCount(task) }}</b></button></aside><div class="inbox-main"><div class="inbox-head"><div><span class="eyebrow">ОТКЛИКИ НА ЗАДАЧУ</span><h2>{{ inboxTask?.title || 'Выберите задачу' }}</h2><p>{{ inboxProposals.length }} {{ isBusiness ? 'предложений · решение принимает представитель бизнеса' : 'ваших предложений' }}</p></div><button v-if="isBusiness && inboxProposals.some((item) => item.status === 'pending')" class="button button-ghost" @click="rejectAll">Пока никого не выбирать</button></div>
          <div v-if="isBusiness && inboxProposals.length > 1" class="comparison-table"><div class="comparison-head"><span>КОМАНДА</span><span>СРОК</span><span>НАВЫКИ</span><span>СТАТУС</span></div><div v-for="item in inboxProposals" :key="item.id"><strong>{{ teamFor(item)?.name }}</strong><span>{{ item.deadline }}</span><span>{{ teamFor(item)?.skills.join(', ') }}</span><span>{{ item.status === 'accepted' ? 'Выбрана' : item.status === 'rejected' ? 'Отклонена' : 'На рассмотрении' }}</span></div></div>
          <div v-if="inboxProposals.length" class="proposal-list"><article v-for="item in inboxProposals" :key="item.id" class="proposal-item"><div class="proposal-top"><div class="team-identity"><div class="team-avatar">{{ teamFor(item)?.initials || 'TM' }}</div><div><strong>{{ teamFor(item)?.name || 'Команда' }}</strong><span>{{ teamFor(item)?.skills.join(' · ') }}</span></div></div><span class="proposal-status" :class="item.status">{{ item.status === 'accepted' ? 'Выбрана' : item.status === 'rejected' ? 'Отклонена' : 'На рассмотрении' }}</span></div><div class="proposal-content"><div><span>ИДЕЯ</span><p>{{ item.idea }}</p></div><div><span>ПЛАН</span><p>{{ item.plan }}</p></div></div><div v-if="item.questions" class="proposal-questions"><span>ВОПРОСЫ К БИЗНЕСУ</span><p>{{ item.questions }}</p></div><div class="proposal-meta"><span>Срок: {{ item.deadline }}</span><a v-if="item.link" :href="item.link" target="_blank" rel="noopener noreferrer"><ForgeIcon name="arrow-up-right" size="13" /> Прототип</a><span>Баллы команды: {{ teamFor(item)?.points || 0 }}</span></div><div v-if="isBusiness" class="proposal-actions"><button v-if="item.status !== 'accepted'" class="button button-dark" @click="setDecision(item, 'accepted')">Выбрать команду <ForgeIcon name="check" size="14" /></button><button v-if="item.status !== 'rejected' && !item.progress_awarded" class="button button-ghost" @click="setDecision(item, 'rejected')">Отклонить</button><button v-if="item.status !== 'pending' && !item.progress_awarded" class="button button-ghost" @click="setDecision(item, 'pending')">На рассмотрении</button><template v-if="item.status === 'accepted'"><span v-if="item.progress_awarded" class="stage-confirmed"><ForgeIcon name="check" size="13" /> Этап подтверждён · +20 баллов</span><button v-else class="button button-orange" @click="confirmProgress(item)">Подтвердить этап · +20 баллов</button></template></div><div v-else-if="item.progress_awarded" class="proposal-actions stage-confirmed">✓ Этап подтверждён · +20 баллов</div></article></div><div v-else class="empty-state">{{ isBusiness ? 'Пока нет откликов. Задача доступна командам в каталоге.' : 'Вы ещё не отправили предложений. Откройте каталог и выберите задачу.' }}</div></div></div></div>
    </main>
    <div v-if="toast" role="status" class="toast"><ForgeIcon name="check" size="15" />{{ toast }}<button aria-label="Закрыть уведомление" @click="toast = ''"><ForgeIcon name="close" size="15" /></button></div>
  </div>
</template>
