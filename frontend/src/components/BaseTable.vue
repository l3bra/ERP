<script setup>
import { ref, onMounted, onUpdated } from 'vue'
import { api } from '../api.js'
import {
  currentItems, lines, productColors, savedStyles, filterQuery,
  upd, quick, consume, receive, del, loadBase, revert,
} from '../state.js'
import { COLORS, colorCss, productColorCss, allowedColorsFor } from '../format.js'
import { enhanceTables } from '../table-enhance.js'

const tableEl = ref(null)

function enhance() { if (tableEl.value) enhanceTables(tableEl.value, savedStyles.value) }
onMounted(enhance)
onUpdated(enhance)

function visible(it) {
  const q = filterQuery.value.toLowerCase()
  if (!q) return true
  const text = [it.product, it.color, it.batch, it.date ?? '', it.qty].join(' ').toLowerCase()
  return text.includes(q)
}

function lineCss(it) {
  const line = lines.value.find(entry => entry.name === it.product)
  return line ? COLORS[line.color].css : ''
}

function colorBg(it) { return productColorCss(it.color, productColors.value) }

function colorAllowed(it) {
  return allowedColorsFor(lines.value, productColors.value, it.product)
    .some(color => color.name.toLowerCase() === (it.color || '').toLowerCase())
}

function isListed(product) { return lines.value.some(line => line.name === product) }

function onColorChange(it, event) {
  event.target.style.backgroundColor = productColorCss(event.target.value, productColors.value)
  upd(it.id, 'color', event.target)
}

// ================= Drag & drop (только внутри своей линейки) =================
let dragState = null

function clearDragState() {
  document.removeEventListener('pointermove', moveDraggedRow)
  document.removeEventListener('pointerup', finishDraggedRow)
  document.removeEventListener('pointercancel', cancelDraggedRow)
  document.querySelectorAll('#items-table .dragging, #items-table .drop-target-before, #items-table .drop-target-after')
    .forEach(row => row.classList.remove('dragging', 'drop-target-before', 'drop-target-after'))
  dragState = null
}

function moveDraggedRow(event) {
  if (!dragState || event.pointerId !== dragState.pointerId) return
  const target = document.elementFromPoint(event.clientX, event.clientY)
    ?.closest('#items-table tr[data-row]')
  document.querySelectorAll('#items-table .drop-target-before, #items-table .drop-target-after')
    .forEach(row => row.classList.remove('drop-target-before', 'drop-target-after'))
  if (!target || target === dragState.row ||
      target.dataset.product !== dragState.row.dataset.product) {
    dragState.target = null
    return
  }
  dragState.target = target
  const rect = target.getBoundingClientRect()
  dragState.insertAfter = event.clientY >= rect.top + rect.height / 2
  target.classList.add(dragState.insertAfter ? 'drop-target-after' : 'drop-target-before')
}

async function finishDraggedRow(event) {
  if (!dragState || event.pointerId !== dragState.pointerId) return
  const state = dragState
  clearDragState()
  if (!state.target) return

  const reordered = [...currentItems.value]
  const from = reordered.findIndex(item => item.id === state.itemId)
  const [moved] = reordered.splice(from, 1)
  let to = reordered.findIndex(item => item.id === Number(state.target.dataset.row))
  if (state.insertAfter) to += 1
  reordered.splice(to, 0, moved)
  if (reordered.every((item, index) => item.id === currentItems.value[index].id)) return

  try {
    await api('/items/order', 'PUT', {ids: reordered.map(item => item.id)})
    currentItems.value = reordered
  } catch { await revert(loadBase) }
}

function cancelDraggedRow(event) {
  if (dragState && event.pointerId === dragState.pointerId) clearDragState()
}

function onPointerDown(event) {
  const handle = event.target.closest('.drag-handle')
  const row = handle && handle.closest('#items-table tr[data-row]')
  if (!row || event.button !== 0) return
  event.preventDefault()
  dragState = {
    itemId: Number(row.dataset.row),
    row,
    pointerId: event.pointerId,
    target: null,
    insertAfter: false,
  }
  row.classList.add('dragging')
  document.addEventListener('pointermove', moveDraggedRow)
  document.addEventListener('pointerup', finishDraggedRow)
  document.addEventListener('pointercancel', cancelDraggedRow)
}

onMounted(() => document.addEventListener('pointerdown', onPointerDown))
</script>

<template>
  <table data-style-table="items" data-resize-id="items" ref="tableEl">
    <tr data-style-row="header"><th>Линейка</th><th>Название</th><th>Партия</th><th>Дата</th><th>Кол-во</th>
      <th>Быстрый расход</th><th>Расход</th><th>Приход</th><th></th></tr>
    <tr v-for="(it, i) in currentItems" :key="it.id" :data-row="it.id" :data-style-row="it.id"
      :data-product="it.product"
      :class="{'line-start': i > 0 && currentItems[i - 1].product !== it.product, hidden: !visible(it)}">
      <td><button type="button" class="drag-handle" title="Перетащить в пределах линейки" aria-label="Переместить строку">↕</button>
      <select data-f="product" class="m" :style="{background: lineCss(it)}" :value="it.product"
        @change="upd(it.id, 'product', $event.target)">
        <option value="">— без линейки —</option>
        <option v-if="it.product && !isListed(it.product)" :value="it.product">{{ it.product }} (вне списка)</option>
        <option v-for="line in lines" :key="line.name" :value="line.name"
          :style="{background: COLORS[line.color].css}">{{ line.name }}</option>
      </select></td>
      <td><select data-f="color" class="m" :style="{backgroundColor: colorBg(it)}" :value="it.color"
        @change="onColorChange(it, $event)">
        <option value="">— выберите цвет —</option>
        <option v-if="it.color && !colorAllowed(it)" :value="it.color">{{ it.color }} (вне списка)</option>
        <option v-for="color in allowedColorsFor(lines, productColors, it.product)" :key="color.name"
          :value="color.name" :style="{background: colorCss(color)}">{{ color.name }}</option>
      </select></td>
      <td><input data-f="batch" class="m" type="text" :value="it.batch" @change="upd(it.id, 'batch', $event.target)"></td>
      <td><input data-f="date" type="date" :value="it.date" @change="upd(it.id, 'date', $event.target)"></td>
      <td><input data-f="qty" :id="'q' + it.id" class="s" type="number" min="0" :value="it.qty"
        @change="upd(it.id, 'qty', $event.target)"></td>
      <td><button v-for="n in [1, 6, 9, 12]" :key="n" :class="'quick q' + n"
        @click="quick(it.id, n, $event.currentTarget)">-{{ n }}</button></td>
      <td><input class="s" :id="'c' + it.id" type="number" min="1"> <button @click="consume(it.id)">−</button></td>
      <td><input class="s" :id="'r' + it.id" type="number" min="1"> <button @click="receive(it.id)">+</button></td>
      <td><button @click="del(it.id)" title="Удалить позицию">✕</button></td>
    </tr>
  </table>
</template>
