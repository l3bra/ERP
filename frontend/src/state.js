import { ref, nextTick } from 'vue'
import { api } from './api.js'
import { err, undoStatus, tab } from './ui.js'
import { DEFAULT_TYPES, currentMonth, flash, parseLinkNote, LINK_NOTE_PREFIX } from './format.js'
import { loadMoysklad } from './moysklad.js'

// Каталог: линейки, цвета, серверные заливки таблиц
export const lines = ref([])
export const productColors = ref([])
export const savedStyles = ref([])

// База
export const currentItems = ref([])
export const filterQuery = ref('')

// Журнал
export const logTypes = ref([...DEFAULT_TYPES])
export const month = ref(null)
export const monthList = ref([])
export const currentLogs = ref([])
export const journalQuery = ref('')

// Печать
export const printData = ref(null)

// Отмена
export const undoInProgress = ref(false)

// Выбор строк журнала
export const selectionCount = ref(0)
export const selectionBarVisible = ref(false)
export const mergeLabel = ref('Объединить примечание')
export const mergeDisabled = ref(true)
export const unmergeDisabled = ref(true)

// Диалог ссылки
export const editingLinkLogId = ref(null)
export const linkLabel = ref('')
export const linkUrl = ref('')
export const linkError = ref('')

// Диалог общего примечания
export const editingNoteGroupId = ref(null)
export const selectedNoteGroupLogIds = ref([])
export const noteGroupVisible = ref(false)
export const noteGroupCode = ref('')
export const noteGroupUrl = ref('')
export const noteGroupText = ref('')
export const noteGroupError = ref('')
export const noteGroupTitle = ref('Общее примечание')
export const noteGroupDescription = ref('')
export const noteGroupSaveLabel = ref('Объединить')
export const noteGroupSaving = ref(false)

// после неудачной правки: вернуть таблицу к данным сервера, но оставить текст ошибки
export async function revert(reloadFn) {
  const msg = err.value
  await reloadFn()
  err.value = msg
}

export async function loadBase() {
  const [items, lineList, colorList] = await Promise.all([
    api('/items'), api('/lines'), api('/product-colors'),
  ])
  currentItems.value = items
  lines.value = lineList
  productColors.value = colorList
}

export async function loadJournal(scrollDown) {
  try {
    const meta = await api('/meta'); logTypes.value = meta.log_types
    const months = await api('/logs/months')
    if (!month.value || !months.includes(month.value)) {
      month.value = months.includes(currentMonth()) ? currentMonth() : months[months.length - 1]
    }
    monthList.value = months
    currentLogs.value = await api('/logs?month=' + month.value)
    if (scrollDown) window.scrollTo(0, document.body.scrollHeight)
  } catch {}
}

export function pickMonth(m) { month.value = m; loadJournal(true) }

export async function loadPrint() {
  printData.value = await api('/print')
}

export async function reload() {
  if (tab.value === 'base') return loadBase()
  if (tab.value === 'journal') return loadJournal(true)
  if (tab.value === 'print') return loadPrint()
  if (tab.value === 'moysklad') return loadMoysklad()
  if (tab.value === 'settings') return loadBase()
}

// ================= Отмена =================
export async function undoLastChange() {
  if (undoInProgress.value) return
  undoInProgress.value = true
  try {
    const result = await api('/undo', 'POST')
    if (!result.undone) {
      undoStatus.value = 'Нет действий для отмены.'
      return
    }
    undoStatus.value = `Отменено: ${result.action}.`
    await Promise.all([loadBase(), loadJournal(false)])
  } catch (error) {
    undoStatus.value = `Не удалось отменить действие: ${error.message || 'неизвестная ошибка'}`
  } finally {
    undoInProgress.value = false
  }
}

// ================= База: операции =================
export async function upd(id, field, el) {
  const val = field === 'qty' ? (el.value === '' ? null : Number(el.value)) : el.value
  if (val === null) return revert(loadBase)
  try {
    const it = await api('/items/' + id, 'PUT', {[field]: val})
    const local = currentItems.value.find(x => x.id === id)
    if (local) {
      local.qty = it.qty
      if (field !== 'qty') local[field] = it[field]
    }
    if (field === 'product') await loadBase()
    else flash(el)
  } catch { revert(loadBase) }
}

export async function quick(id, n, button) {
  button.disabled = true
  try {
    const r = await api(`/items/${id}/quick/${n}`, 'POST')
    const local = currentItems.value.find(x => x.id === id)
    if (local) local.qty = r.new_qty
    flash(document.getElementById('q' + id))
    await loadBase()
  } catch (error) {
    err.value = 'Ошибка быстрого расхода: ' + error.message
  } finally {
    if (button.isConnected) button.disabled = false
  }
}

export async function consume(id) {
  const input = document.getElementById('c' + id)
  const v = Number(input.value); if (!(v > 0)) return
  try {
    const r = await api(`/items/${id}/consume`, 'POST', {amount: v})
    const local = currentItems.value.find(x => x.id === id)
    if (local) local.qty = r.new_qty
    input.value = ''
    flash(document.getElementById('q' + id))
  } catch {}
}

export async function receive(id) {
  const input = document.getElementById('r' + id)
  const v = Number(input.value); if (!(v > 0)) return
  try {
    const r = await api(`/items/${id}/receive`, 'POST', {amount: v})
    const local = currentItems.value.find(x => x.id === id)
    if (local) local.qty = r.new_qty
    input.value = ''
    flash(document.getElementById('q' + id))
  } catch {}
}

export async function del(id) { try { await api('/items/' + id, 'DELETE'); loadBase() } catch {} }

// ================= Журнал: операции =================
export async function updLog(id, patch, el) {
  try {
    const r = await api('/logs/' + id, 'PUT', patch)
    const idx = currentLogs.value.findIndex(log => log.id === id)
    if (idx >= 0) currentLogs.value[idx] = {...currentLogs.value[idx], ...r}
    flash(el)
  } catch { revert(() => loadJournal(false)) }
}

export async function delLog(id) { try { await api('/logs/' + id, 'DELETE'); loadJournal(false) } catch {} }

export async function divider(kind) {
  try { await api('/logs/divider', 'POST', {kind}); month.value = currentMonth(); loadJournal(true) } catch {}
}

// ================= Журнал: выбор строк =================
export function selectedJournalLogs() {
  const selectedIds = new Set([...document.querySelectorAll('[data-log-select]:checked')]
    .map(input => Number(input.value)))
  return currentLogs.value.filter(log => selectedIds.has(log.id))
}

export function updateSelection() {
  const selected = selectedJournalLogs()
  const groupIds = new Set(selected.map(log => log.shared_note_group_id).filter(Boolean))
  const canEditGroup = selected.length > 0 && selected.every(log =>
    log.shared_note_group_id && log.shared_note_group_id === selected[0].shared_note_group_id)
  selectionCount.value = selected.length
  selectionBarVisible.value = selected.length > 0
  mergeLabel.value = canEditGroup
    ? 'Изменить общее примечание'
    : 'Объединить примечание'
  mergeDisabled.value = selected.length < 2 && !canEditGroup
  unmergeDisabled.value = groupIds.size !== 1
  const visibleChecks = [...document.querySelectorAll('#logs-table tr[data-log-row]:not(.hidden) [data-log-select]')]
  const selectAll = document.getElementById('journal-select-all')
  if (selectAll) {
    selectAll.checked = visibleChecks.length > 0 && visibleChecks.every(input => input.checked)
    selectAll.indeterminate = visibleChecks.some(input => input.checked) && !selectAll.checked
  }
}

// ================= Журнал: общие примечания =================
export function editOrMergeSelectedNotes() {
  const selected = selectedJournalLogs()
  if (!selected.length) return
  const groupIds = new Set(selected.map(log => log.shared_note_group_id).filter(Boolean))
  if (groupIds.size === 1 && selected.every(log => log.shared_note_group_id)) {
    openNoteGroupDialog([...groupIds][0])
    return
  }
  if (selected.length >= 2) openNoteGroupDialog()
}

export function openNoteGroupDialog(groupId = null) {
  editingNoteGroupId.value = groupId
  selectedNoteGroupLogIds.value = selectedJournalLogs().map(log => log.id)
  const existing = groupId
    ? currentLogs.value.find(log => log.shared_note_group_id === groupId)
    : null
  noteGroupCode.value = existing?.shared_note_code || ''
  noteGroupUrl.value = existing?.shared_note_url || ''
  noteGroupText.value = existing?.shared_note_text || ''
  noteGroupTitle.value = groupId ? 'Изменить общее примечание' : 'Общее примечание'
  noteGroupDescription.value = groupId
    ? 'Изменения применятся ко всем строкам этой группы.'
    : `Одно примечание будет показано для ${selectedNoteGroupLogIds.value.length} выбранных операций.`
  noteGroupSaveLabel.value = groupId ? 'Сохранить' : 'Объединить'
  noteGroupError.value = ''
  noteGroupVisible.value = true
}

export function closeNoteGroupDialog() {
  noteGroupVisible.value = false
}

export async function saveNoteGroup() {
  const code = noteGroupCode.value.trim() || null
  let url = noteGroupUrl.value.trim()
  const text = noteGroupText.value.trim() || null
  if (!code && !url && !text) {
    noteGroupError.value = 'Заполните код, ссылку или текст примечания.'
    return
  }
  if (url) {
    if (!/^[a-z][a-z\d+.-]*:/i.test(url)) url = 'https://' + url
    try {
      const parsed = new URL(url)
      if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error()
      url = parsed.href
    } catch {
      noteGroupError.value = 'Введите корректную ссылку (http или https).'
      return
    }
  }
  noteGroupSaving.value = true
  try {
    const data = {code, url: url || null, text}
    if (editingNoteGroupId.value) {
      await api('/logs/note-groups/' + editingNoteGroupId.value, 'PUT', data)
    } else {
      if (selectedNoteGroupLogIds.value.length < 2) {
        noteGroupError.value = 'Выберите не менее двух строк журнала.'
        return
      }
      await api('/logs/note-groups', 'POST', {ids: selectedNoteGroupLogIds.value, ...data})
    }
    closeNoteGroupDialog()
    await loadJournal(false)
  } catch (error) {
    noteGroupError.value = error.message || 'Не удалось сохранить примечание.'
  } finally {
    noteGroupSaving.value = false
  }
}

export async function unmergeNoteGroup(groupId) {
  try {
    await api('/logs/note-groups/' + groupId, 'DELETE')
    await loadJournal(false)
  } catch {}
}

export async function unmergeSelectedNoteGroup() {
  const selected = selectedJournalLogs()
  const groupIds = new Set(selected.map(log => log.shared_note_group_id).filter(Boolean))
  if (groupIds.size === 1) await unmergeNoteGroup([...groupIds][0])
}

// ================= Журнал: ссылка в примечании =================
export function openLinkEditor(logId) {
  const row = currentLogs.value.find(log => log.id === logId)
  if (!row) return
  const link = parseLinkNote(row.note)
  editingLinkLogId.value = logId
  linkLabel.value = link ? link.label : (row.note || '')
  linkUrl.value = link ? link.url : ''
  linkError.value = ''
  document.getElementById('link-dialog').showModal()
  nextTick(() => document.getElementById('link-label')?.focus())
}

export async function saveLink() {
  const label = linkLabel.value.trim()
  let rawUrl = linkUrl.value.trim()
  if (!label || !rawUrl) {
    linkError.value = 'Заполните текст ссылки и адрес.'
    return
  }
  if (!/^[a-z][a-z\d+.-]*:/i.test(rawUrl)) rawUrl = 'https://' + rawUrl
  let url
  try {
    url = new URL(rawUrl)
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Unsupported protocol')
  } catch {
    linkError.value = 'Введите корректный адрес сайта (http или https).'
    return
  }
  try {
    await api('/logs/' + editingLinkLogId.value, 'PUT', {
      note: LINK_NOTE_PREFIX + JSON.stringify({label, url: url.href}),
    })
    document.getElementById('link-dialog').close()
    await loadJournal(false)
  } catch (error) {
    linkError.value = error.message
  }
}

export function closeLinkDialog() {
  document.getElementById('link-dialog')?.close()
}
