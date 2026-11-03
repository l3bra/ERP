<script setup>
import { ref, computed, onMounted, onUpdated } from 'vue'
import {
  tokenInput, moyskladConfigured, selectedStoreHref, moyskladStores, moyskladStatus,
  moyskladTokenStatus, moyskladStockItems, moyskladComparison, moyskladLastUpdatedAt,
  mappingLocalName, mappingExternalHref, mappingExternalOptions, mappingExternalMissing,
  loadMoysklad, saveMoyskladToken, deleteMoyskladToken, selectMoyskladStore,
  comparisonRows, snapshotRows, saveSelectedMoyskladMapping, clearSelectedMoyskladMapping,
} from '../moysklad.js'
import { savedStyles } from '../state.js'
import { formatMoyskladQuantity } from '../format.js'
import { enhanceTables } from '../table-enhance.js'
import { saveMoyskladSnapshot } from '../excel.js'

const tableEl = ref(null)

function enhance() { if (tableEl.value) enhanceTables(tableEl.value, savedStyles.value) }
onMounted(enhance)
onUpdated(enhance)

const storeSelectDisabled = computed(() =>
  !moyskladConfigured.value || moyskladStores.value.length === 0)

const storePlaceholder = computed(() => {
  if (!moyskladConfigured.value) return 'Подключите токен, чтобы выбрать склад'
  return '— выберите склад —'
})

const groups = computed(() => moyskladComparison.value ? moyskladComparison.value.groups : [])

const localSelectDisabled = computed(() => groups.value.length === 0)
const externalSelectDisabled = computed(() =>
  moyskladStockItems.value.length === 0 || !mappingLocalName.value)
const saveMappingDisabled = computed(() =>
  groups.value.length === 0 || moyskladStockItems.value.length === 0)
const clearMappingDisabled = computed(() => groups.value.length === 0)

function diffClass(diff) {
  return diff > 0 ? 'positive-difference' : diff < 0 ? 'negative-difference' : ''
}

function diffText(diff) {
  return diff == null ? '—' : `${diff > 0 ? '+' : ''}${formatMoyskladQuantity(diff)}`
}

function onStoreChange(event) {
  selectedStoreHref.value = event.target.value
  selectMoyskladStore()
}

async function doSaveSnapshot() {
  await saveMoyskladSnapshot(snapshotRows.value, moyskladLastUpdatedAt.value, message => {
    moyskladStatus.value = message
  })
}
</script>

<template>
  <div class="moysklad-setup no-print">
    <div class="bar">
      <label for="moysklad-token"><b>API-токен МойСклад:</b></label>
      <input id="moysklad-token" type="password" class="l" autocomplete="new-password"
        placeholder="Введите токен для сохранения" v-model="tokenInput">
      <button type="button" class="btn-accent" @click="saveMoyskladToken()">Сохранить токен</button>
      <button id="moysklad-remove-token" type="button" @click="deleteMoyskladToken()"
        :hidden="!moyskladConfigured">Удалить токен</button>
    </div>
    <div id="moysklad-token-status" class="moysklad-status">{{ moyskladTokenStatus }}</div>
    <div class="bar">
      <label for="moysklad-store"><b>Склад МойСклад:</b></label>
      <select id="moysklad-store" :disabled="storeSelectDisabled" :value="selectedStoreHref"
        @change="onStoreChange">
        <option value="">{{ storePlaceholder }}</option>
        <option v-for="store in moyskladStores" :key="store.href" :value="store.href">{{ store.name }}</option>
      </select>
      <button type="button" @click="loadMoysklad()">Обновить данные «Базы» и МойСклад</button>
    </div>
    <div class="hint">Токен и сопоставления хранятся локально. МойСклад используется только для чтения; его данные не изменяются.</div>
    <div id="moysklad-status" class="moysklad-status" role="status">{{ moyskladStatus }}</div>
  </div>
  <div class="moysklad-mapping no-print">
    <label>Название из базы
      <select id="moysklad-local-name" :disabled="localSelectDisabled" :value="mappingLocalName"
        @change="mappingLocalName = $event.target.value">
        <option v-if="!groups.length" value="">Загрузите остатки</option>
        <option v-for="g in groups" :key="g.name" :value="g.name">{{ g.name }}</option>
      </select>
    </label>
    <label>Товар из МойСклад
      <select id="moysklad-external-item" :disabled="externalSelectDisabled" :value="mappingExternalHref"
        @change="mappingExternalHref = $event.target.value">
        <option value="">— не сопоставлен —</option>
        <option v-for="item in mappingExternalOptions" :key="item.href" :value="item.href"
          :disabled="item.disabled">{{ item.label }}</option>
        <option v-if="mappingExternalMissing" :value="mappingExternalHref">Сопоставленный товар не загружен</option>
      </select>
    </label>
    <button id="moysklad-save-mapping" type="button" class="btn-accent"
      @click="saveSelectedMoyskladMapping()" :disabled="saveMappingDisabled">Сохранить сопоставление</button>
    <button id="moysklad-clear-mapping" type="button" @click="clearSelectedMoyskladMapping()"
      :disabled="clearMappingDisabled">Снять сопоставление</button>
  </div>
  <div class="hint no-print">Точные совпадения названий подставляются как подсказки. Связь сохраняется после нажатия «Сохранить сопоставление».</div>
  <div class="moysklad-table-actions no-print">
    <button id="moysklad-save-snapshot" class="moysklad-save-button btn-accent" type="button"
      @click="doSaveSnapshot" aria-label="Сохранить таблицу в файл"
      title="Сохранить таблицу в файл" :disabled="!moyskladComparison">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
        stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 3v12m0 0 4-4m-4 4-4-4"></path>
        <path d="M5 16v4h14v-4"></path>
      </svg>
    </button>
  </div>
  <div id="moysklad-table" class="table-wrap">
    <table v-if="moyskladComparison" data-style-table="moysklad" data-resize-id="moysklad" ref="tableEl">
      <tr data-style-row="header"><th>Название из базы</th><th>Количество в базе</th>
        <th>Название из МойСклад</th><th>Количество в МойСклад</th>
        <th>Разница (база − МойСклад)</th></tr>
      <tr v-for="row in comparisonRows" :key="row.group.name" :data-style-row="row.group.name">
        <td>{{ row.group.name }}</td>
        <td class="num">{{ formatMoyskladQuantity(row.group.quantity) }}</td>
        <td>{{ row.remote ? row.remote.name : '—' }}</td>
        <td class="num">{{ row.remote ? formatMoyskladQuantity(row.remote.quantity) : '—' }}</td>
        <td class="num" :class="diffClass(row.diff)">{{ diffText(row.diff) }}</td>
      </tr>
      <tr v-if="!comparisonRows.length" data-style-row="empty">
        <td colspan="5" class="hint">В «Базе» нет позиций для сравнения.</td></tr>
    </table>
  </div>
</template>
