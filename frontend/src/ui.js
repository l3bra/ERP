import { ref } from 'vue'
import { THEMES } from './format.js'

export const err = ref('')
export const undoStatus = ref('')
export const tab = ref('base')
export const apiInput = ref('')
export const activeTheme = ref('clean-light')

export function setTheme(theme, persist = true) {
  if (!THEMES.includes(theme)) return
  document.body.dataset.theme = theme
  activeTheme.value = theme
  if (persist) {
    try { localStorage.setItem('warehouse-theme', theme) }
    catch (error) { console.warn('Не удалось сохранить выбранный дизайн.', error) }
  }
}

export function initTheme() {
  let theme = 'clean-light'
  try {
    const stored = localStorage.getItem('warehouse-theme')
    if (THEMES.includes(stored)) theme = stored
  } catch (error) {
    console.warn('Не удалось прочитать сохранённый дизайн.', error)
  }
  setTheme(theme, false)
}
