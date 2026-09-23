export default defineNuxtConfig({
  compatibilityDate: '2026-09-23',
  devtools: { enabled: false },
  ssr: false,
  css: ['~/assets/main.css', '~/assets/rebrand.css', '~/assets/polish.css', '~/assets/landing.css'],
  app: {
    head: {
      title: 'FORGE — практические задачи AI Sana',
      htmlAttrs: { lang: 'ru' },
      meta: [
        { name: 'description', content: 'FORGE помогает бизнесу превращать реальные проблемы в понятные и измеримые задачи для студенческих команд.' },
        { name: 'theme-color', content: '#0d0e11' },
      ],
      link: [{ rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }],
    },
  },
  runtimeConfig: {
    public: { apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000' },
  },
})
