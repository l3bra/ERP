<script setup>
import { ref, computed, watch } from 'vue'
import { api } from '../api.js'
import { lines, productColors, filterQuery, loadBase } from '../state.js'
import { COLORS, colorCss, productColorCss, allowedColorsFor } from '../format.js'
import BaseTable from './BaseTable.vue'

const newProduct = ref('')
const newColor = ref('')
const newBatch = ref('')
const newDate = ref('')
const newQty = ref('')

const isListedProduct = computed(() => lines.value.some(line => line.name === newProduct.value))
const newProductLine = computed(() => lines.value.find(line => line.name === newProduct.value))
const newProductBg = computed(() => newProductLine.value ? COLORS[newProductLine.value.color].css : '')
const newColorBg = computed(() => productColorCss(newColor.value, productColors.value))
const allowedNewColors = computed(() => allowedColorsFor(lines.value, productColors.value, newProduct.value))
const newColorIsAllowed = computed(() =>
  allowedNewColors.value.some(color => color.name.toLowerCase() === newColor.value.toLowerCase()))

// Выбранный цвет сбрасывается, если он не разрешён для выбранной линейки
watch([newProduct, lines, productColors], () => {
  if (newColor.value && !newColorIsAllowed.value) newColor.value = ''
})

async function addItem() {
  try {
    await api('/items', 'POST', {
      product: newProduct.value, color: newColor.value, batch: newBatch.value,
      date: newDate.value || null, qty: Number(newQty.value) || 0 })
    newColor.value = ''
    newBatch.value = ''
    newQty.value = ''
    await loadBase()
  } catch {}
}
</script>

<template>
  <div class="bar">
    <b>Новая партия:</b>
    <select id="n-product" class="m" :value="newProduct" :style="{backgroundColor: newProductBg}"
      @change="newProduct = $event.target.value">
      <option value="">— без линейки —</option>
      <option v-if="newProduct && !isListedProduct" :value="newProduct">{{ newProduct }} (вне списка)</option>
      <option v-for="line in lines" :key="line.name" :value="line.name"
        :style="{background: COLORS[line.color].css}">{{ line.name }}</option>
    </select>
    <select id="n-color" class="m" aria-label="Название / цвет" :value="newColor"
      :style="{backgroundColor: newColorBg}" @change="newColor = $event.target.value">
      <option value="">— выберите цвет —</option>
      <option v-if="newColor && !newColorIsAllowed" :value="newColor">{{ newColor }} (вне списка)</option>
      <option v-for="color in allowedNewColors" :key="color.name" :value="color.name"
        :style="{background: colorCss(color)}">{{ color.name }}</option>
    </select>
    <input id="n-batch" class="m" placeholder="Партия" v-model="newBatch">
    <input id="n-date" type="date" v-model="newDate">
    <input id="n-qty" class="s" type="number" min="0" placeholder="Кол-во" v-model="newQty">
    <button class="btn-accent btn-add" @click="addItem()">Добавить</button>
    <input id="filter" class="m" placeholder="Поиск…" v-model="filterQuery">
  </div>
  <div class="hint">Все поля редактируются прямо в таблице. В журнал попадают создание партии и изменение количества.</div>
  <div id="items-table" class="table-wrap">
    <BaseTable />
  </div>
</template>
