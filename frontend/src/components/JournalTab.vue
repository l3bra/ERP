<script setup>
import {
  month, monthList, journalQuery, pickMonth, divider,
  selectionCount, selectionBarVisible, mergeLabel, mergeDisabled, unmergeDisabled,
  editOrMergeSelectedNotes, unmergeSelectedNoteGroup,
} from '../state.js'
import { monthLabel } from '../format.js'
import JournalTable from './JournalTable.vue'
</script>

<template>
  <div class="bar">
    <button @click="divider('day')">Новый день</button>
    <button @click="divider('inventory')">Инвентаризация</button>
    <input id="journal-filter" class="m" type="search" placeholder="Поиск в журнале…"
      aria-label="Поиск в журнале" v-model="journalQuery">
    <span class="hint">Правка строк журнала меняет только запись, остатки в Базе не затрагиваются.</span>
  </div>
  <div class="sub" id="months">
    <button v-for="m in monthList" :key="m" :class="{active: m === month}"
      @click="pickMonth(m)">{{ monthLabel(m) }}</button>
  </div>
  <div id="journal-selection-bar" class="journal-selection-bar no-print" :class="{visible: selectionBarVisible}"
    role="group" aria-label="Действия с выбранными строками журнала">
    <span id="journal-selection-count">Выбрано: {{ selectionCount }}</span>
    <button id="journal-merge-button" type="button" @click="editOrMergeSelectedNotes()"
      :disabled="mergeDisabled">{{ mergeLabel }}</button>
    <button id="journal-unmerge-button" type="button" @click="unmergeSelectedNoteGroup()"
      :disabled="unmergeDisabled">Разъединить примечание</button>
  </div>
  <div id="logs-table" class="table-wrap">
    <JournalTable />
  </div>
</template>
