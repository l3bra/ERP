<script setup>
import { ref, computed, watch, onMounted, onUpdated, nextTick } from 'vue'
import { currentLogs, journalQuery, savedStyles, updateSelection } from '../state.js'
import { parseLinkNote } from '../format.js'
import { enhanceTables } from '../table-enhance.js'
import LogRow from './LogRow.vue'
import DividerRow from './DividerRow.vue'

const tableEl = ref(null)

function enhance() { if (tableEl.value) enhanceTables(tableEl.value, savedStyles.value) }
onMounted(enhance)
onUpdated(enhance)

// ================= Фильтр =================
function matchesQuery(log, q) {
  const link = parseLinkNote(log.note)
  const searchableText = [
    log.ts, log.product, log.color, log.batch, log.old_qty, log.new_qty,
    log.diff, log.type, log.note, link?.label, link?.url,
    log.shared_note_code, log.shared_note_text, log.shared_note_url,
  ].filter(value => value != null).join(' ').toLocaleLowerCase()
  return !q || searchableText.includes(q)
}

const queryLower = computed(() => journalQuery.value.trim().toLocaleLowerCase())
const groupMatches = computed(() => {
  const map = new Map()
  const q = queryLower.value
  if (!q) return map
  for (const log of currentLogs.value) {
    if (log.shared_note_group_id && matchesQuery(log, q)) {
      map.set(log.shared_note_group_id, true)
    }
  }
  return map
})

function rowVisible(log) {
  const q = queryLower.value
  if (!q) return true
  if (log.shared_note_group_id) return groupMatches.value.has(log.shared_note_group_id)
  return matchesQuery(log, q)
}

// ================= Строки таблицы (порт renderLogs) =================
const displayRows = computed(() => {
  const groupedLogs = new Map()
  for (const log of currentLogs.value) {
    if (!log.shared_note_group_id) continue
    if (!groupedLogs.has(log.shared_note_group_id)) groupedLogs.set(log.shared_note_group_id, [])
    groupedLogs.get(log.shared_note_group_id).push(log)
  }
  const renderedGroups = new Set()
  const rows = []
  for (const log of currentLogs.value) {
    if (log.kind === 'divider') {
      rows.push({type: 'divider', log, visible: rowVisible(log), key: 'd' + log.id})
      continue
    }
    if (log.shared_note_group_id) {
      const groupId = log.shared_note_group_id
      if (renderedGroups.has(groupId)) continue
      renderedGroups.add(groupId)
      const members = groupedLogs.get(groupId) || [log]
      rows.push({type: 'shared', members, visible: rowVisible(log), key: 'g' + groupId})
      continue
    }
    rows.push({type: 'normal', log, visible: rowVisible(log), key: 'n' + log.id})
  }
  return rows
})

const visibleCount = computed(() => {
  let count = 0
  for (const entry of displayRows.value) {
    if (!entry.visible) continue
    if (entry.type === 'shared') count += entry.members.length
    else count++
  }
  return count
})

const emptyText = computed(() => currentLogs.value.length
  ? 'По запросу ничего не найдено'
  : 'В этом месяце записей нет')

// ================= Выбор строк =================
// Прежний интерфейс перерисовывал таблицу при каждой перезагрузке журнала,
// сбрасывая выбор строк. Повторяем это поведение.
watch(currentLogs, async () => {
  await nextTick()
  document.querySelectorAll('#logs-table [data-log-select]').forEach(input => { input.checked = false })
  updateSelection()
})

watch(journalQuery, async () => {
  await nextTick()
  updateSelection()
})

function onCheckboxChange() { updateSelection() }

function onSelectAll(event) {
  document.querySelectorAll('#logs-table tr[data-log-row]:not(.hidden) [data-log-select]')
    .forEach(input => { input.checked = event.target.checked })
  updateSelection()
}
</script>

<template>
  <table data-style-table="logs" data-resize-id="logs" ref="tableEl">
    <tr data-style-row="header"><th>Время</th><th>Линейка</th><th>Название</th><th>Партия</th><th>Было</th><th>Стало</th>
      <th>Разница</th><th>Тип</th><th>Примечание</th><th></th>
      <th><input id="journal-select-all" type="checkbox" aria-label="Выбрать все видимые операции"
        @change="onSelectAll"></th></tr>
    <template v-for="entry in displayRows" :key="entry.key">
      <DividerRow v-if="entry.type === 'divider'" :log="entry.log" :visible="entry.visible" />
      <template v-else-if="entry.type === 'shared'">
        <LogRow v-for="(member, i) in entry.members" :key="member.id" :log="member"
          :visible="entry.visible" :shared="i === 0 ? {count: entry.members.length} : null" />
      </template>
      <LogRow v-else :log="entry.log" :visible="entry.visible" :shared="null" />
    </template>
    <tr data-style-row="empty" data-journal-empty :class="{hidden: visibleCount > 0}">
      <td colspan="11" class="hint">{{ emptyText }}</td></tr>
  </table>
</template>
