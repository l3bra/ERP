<script setup>
import { ref, onMounted } from 'vue'
import { tab, err, undoStatus, activeTheme, apiInput, setTheme, initTheme } from '../ui.js'
import { defaultApi, api } from '../api.js'
import {
  month, reload, undoLastChange, undoInProgress, savedStyles,
  linkLabel, linkUrl, linkError, saveLink, closeLinkDialog,
} from '../state.js'
import { currentMonth } from '../format.js'
import BaseTab from './BaseTab.vue'
import JournalTab from './JournalTab.vue'
import PrintTab from './PrintTab.vue'
import MoyskladTab from './MoyskladTab.vue'
import SettingsTab from './SettingsTab.vue'
import NoteGroupDialog from './NoteGroupDialog.vue'

const themeChoices = [
  {id: 'clean-light', title: 'Светлый минимализм', preview: ''},
  {id: 'dark-lab', title: 'Тёмная лаборатория', preview: 'dark'},
  {id: 'resin-glass', title: 'Стекло и градиент', preview: 'glass'},
  {id: 'swiss-technical', title: 'Швейцарская техническая сетка', preview: 'swiss'},
]
const tabs = [
  {id: 'base', label: 'База'},
  {id: 'journal', label: 'Журнал'},
  {id: 'print', label: 'Печать'},
  {id: 'moysklad', label: 'МойСклад'},
  {id: 'settings', label: 'Настройка'},
]

const settingsPopover = ref(null)
const settingsTrigger = ref(null)
const showScrollTop = ref(false)

function setOpen(open) {
  settingsPopover.value.hidden = !open
  settingsTrigger.value.setAttribute('aria-expanded', String(open))
}

function onTriggerClick() { setOpen(settingsPopover.value.hidden) }

function onDocumentClick(event) {
  const popover = settingsPopover.value
  if (!popover.hidden && !popover.contains(event.target) && !settingsTrigger.value.contains(event.target)) {
    setOpen(false)
  }
}

function onPopoverKeydown(event) {
  if (event.key === 'Escape' && !settingsPopover.value.hidden) {
    setOpen(false)
    settingsTrigger.value.focus()
  }
}

function switchTab(t) {
  tab.value = t
  if (t === 'journal') month.value = currentMonth()
  reload()
}

function syncHeaderHeight() {
  const header = document.querySelector('.app-header')
  const update = () => document.documentElement.style.setProperty(
    '--app-header-height', `${Math.ceil(header.getBoundingClientRect().height)}px`)
  update()
  new ResizeObserver(update).observe(header)
}

function initScrollTop() {
  const update = () => { showScrollTop.value = window.scrollY >= 400 }
  window.addEventListener('scroll', update, {passive: true})
  update()
}

function scrollToTop() {
  window.scrollTo({
    top: 0,
    behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
  })
}

function onUndoKeydown(event) {
  if (!(event.ctrlKey || event.metaKey) || event.shiftKey || event.altKey ||
      event.key.toLowerCase() !== 'z') return
  const target = event.target
  if (target?.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName)) return
  event.preventDefault()
  undoLastChange()
}

onMounted(async () => {
  apiInput.value = defaultApi()
  syncHeaderHeight()
  initScrollTop()
  document.addEventListener('keydown', onUndoKeydown)
  document.addEventListener('keydown', onPopoverKeydown)
  document.addEventListener('click', onDocumentClick)
  initTheme()
  try { savedStyles.value = await api('/styles') }
  catch {}
  await reload()
})
</script>

<template>
  <header class="app-header no-print">
    <div class="app-title-row">
      <h2>Склад</h2>
      <button id="undo-trigger" class="undo-trigger" type="button" @click="undoLastChange()"
        :disabled="undoInProgress"
        aria-label="Отменить последнее действие" title="Отменить последнее действие (Ctrl+Z)">↶</button>
      <button id="settings-trigger" class="settings-trigger" type="button" ref="settingsTrigger"
        @click="onTriggerClick"
        aria-label="Настройки оформления" aria-expanded="false" aria-controls="settings-popover"
        title="Оформление">⌄</button>
      <div id="settings-popover" class="settings-popover" ref="settingsPopover" hidden>
        <div class="theme-switcher" role="group" aria-label="Выбор оформления">
          <button v-for="choice in themeChoices" :key="choice.id" type="button" class="theme-option"
            :data-theme-choice="choice.id" :aria-label="choice.title"
            :aria-pressed="String(activeTheme === choice.id)" :title="choice.title"
            @click="setTheme(choice.id)">
            <span class="theme-preview" :class="choice.preview" aria-hidden="true"></span>
          </button>
        </div>
      </div>
    </div>
    <nav>
      <button v-for="t in tabs" :key="t.id" :data-tab="t.id" :class="{active: tab === t.id}"
        @click="switchTab(t.id)">{{ t.label }}</button>
    </nav>
  </header>
  <div id="undo-status" class="no-print" role="status" aria-live="polite">{{ undoStatus }}</div>
  <button id="scroll-top" class="scroll-top no-print" type="button" aria-label="Наверх" title="Наверх"
    :hidden="!showScrollTop" @click="scrollToTop">↑</button>
  <div id="err" class="err">{{ err }}</div>

  <!-- ===== БАЗА ===== -->
  <section id="tab-base" :class="{hidden: tab !== 'base'}"><BaseTab /></section>

  <!-- ===== ЖУРНАЛ ===== -->
  <section id="tab-journal" :class="{hidden: tab !== 'journal'}"><JournalTab /></section>

  <!-- ===== ПЕЧАТЬ ===== -->
  <section id="tab-print" :class="{hidden: tab !== 'print'}"><PrintTab /></section>

  <!-- ===== МОЙСКЛАД ===== -->
  <section id="tab-moysklad" :class="{hidden: tab !== 'moysklad'}"><MoyskladTab /></section>

  <!-- ===== НАСТРОЙКА ===== -->
  <section id="tab-settings" :class="{hidden: tab !== 'settings'}"><SettingsTab /></section>

  <dialog id="link-dialog">
    <form id="link-form" class="link-form" @submit.prevent="saveLink">
      <strong>Добавить ссылку</strong>
      <label>Текст ссылки<input id="link-label" required maxlength="200" placeholder="Например, карточка товара" v-model="linkLabel"></label>
      <label>Адрес<input id="link-url" type="text" inputmode="url" autocomplete="url" required placeholder="https://example.com" v-model="linkUrl"></label>
      <div id="link-error" class="link-error" role="alert">{{ linkError }}</div>
      <div class="bar">
        <button type="submit">Сохранить</button>
        <button type="button" @click="closeLinkDialog()">Отмена</button>
      </div>
    </form>
  </dialog>
  <NoteGroupDialog />
</template>
