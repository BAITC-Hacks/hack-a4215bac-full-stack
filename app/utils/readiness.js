export const fields = [
  { key: 'context', label: 'Контекст', points: 10, min: 15, group: 'Контекст и потребность', hint: 'Что происходит сейчас и почему это создаёт проблему?' },
  { key: 'need', label: 'Потребность', points: 10, min: 12, group: 'Контекст и потребность', hint: 'Что именно нужно изменить?' },
  { key: 'data', label: 'Данные и материалы', points: 20, min: 12, group: 'Данные и материалы', hint: 'Какие файлы, примеры или источники вы передадите?' },
  { key: 'outcome', label: 'Ожидаемый результат', points: 15, min: 12, group: 'Ожидаемый результат', hint: 'Какой результат должна показать команда?' },
  { key: 'success', label: 'Критерии успеха', points: 15, min: 12, group: 'Критерии успеха', hint: 'По каким измеримым признакам вы примете результат?' },
  { key: 'constraints', label: 'Ограничения', points: 10, min: 10, group: 'Ограничения', hint: 'Сроки, технологии, доступы и другие границы' },
  { key: 'users', label: 'Пользователи', points: 10, min: 8, group: 'Пользователи', hint: 'Кто будет пользоваться решением?' },
  { key: 'contact', label: 'Контакт бизнеса', points: 5, min: 8, group: 'Связь с бизнесом', hint: 'Имя и способ связи с представителем бизнеса' },
  { key: 'collaboration', label: 'Формат взаимодействия', points: 5, min: 12, group: 'Связь с бизнесом', hint: 'Как часто возможны консультации и обратная связь?' },
]

export const groups = [
  ['Контекст и потребность', 20],
  ['Данные и материалы', 20],
  ['Ожидаемый результат', 15],
  ['Критерии успеха', 15],
  ['Ограничения', 10],
  ['Пользователи', 10],
  ['Связь с бизнесом', 10],
]

export function validField(field, value) {
  const clean = String(value || '').trim().replace(/\s+/g, ' ')
  return clean.length >= field.min && !['нет', 'не знаю', 'н/д', 'n/a', 'позже', 'пока нет', 'не указано', '—', '-', '...'].includes(clean.toLowerCase())
}

export function scoreTask(task) {
  if (!task) return { score: 0, level: 'Черновик', groups: groups.map(([name, possible]) => ({ name, possible, earned: 0 })), items: [], missing: [] }
  const items = fields.map((field) => ({ ...field, earned: task.confirmed?.[field.key] && validField(field, task.fields?.[field.key]) ? field.points : 0 }))
  const score = items.reduce((sum, item) => sum + item.earned, 0)
  return {
    score,
    level: score >= 90 ? 'Приоритетная' : score >= 70 ? 'Готовая' : score >= 40 ? 'Рабочая' : 'Черновик',
    items,
    groups: groups.map(([name, possible]) => ({ name, possible, earned: items.filter((item) => item.group === name).reduce((sum, item) => sum + item.earned, 0) })),
    missing: items.filter((item) => item.earned === 0),
  }
}

export function studentChecks(task) {
  const score = scoreTask(task)
  const has = (group) => score.groups.find((item) => item.name === group)?.earned > 0
  return [
    { ok: has('Контекст и потребность'), text: 'Понятно, какую проблему нужно решить' },
    { ok: has('Пользователи'), text: 'Ясно, кто будет пользоваться результатом' },
    { ok: has('Данные и материалы'), text: 'Есть данные для проверки идеи' },
    { ok: has('Ожидаемый результат'), text: 'Понятно, что нужно передать бизнесу' },
    { ok: has('Критерии успеха'), text: 'Ясно, как будет оценён результат' },
    { ok: has('Связь с бизнесом'), text: 'Есть способ получить обратную связь' },
  ]
}
