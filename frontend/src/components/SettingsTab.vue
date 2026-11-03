<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { api } from '../api.js'
import { lines, productColors, loadBase, reload } from '../state.js'
import { apiInput } from '../ui.js'
import { COLORS, colorCss } from '../format.js'

// ================= Линейки =================
const newLineName = ref('')
const newLineColor = ref('0')

async function addLine() {
  const name = newLineName.value.trim()
  if (!name) return
  try {
    await api('/lines', 'POST', {name, color: Number(newLineColor.value)})
    newLineName.value = ''
    await loadBase()
    colorLineTarget.value = name
  } catch {}
}

async function updateLineColor(name, color) {
  try {
    await api('/lines', 'PUT', {name, color: Number(color)})
    lines.value = lines.value.map(line => line.name === name ? {...line, color: Number(color)} : line)
  } catch {}
}

async function deleteLine(name) {
  try {
    await api('/lines/' + encodeURIComponent(name), 'DELETE')
    await loadBase()
  } catch {}
}

// ================= Цвета =================
const newColorName = ref('')
const newColorRgb = ref('#ff6384')
const newColorOpacity = ref('0.36')

const newColorPreview = computed(() =>
  colorCss({rgb: newColorRgb.value, opacity: Number(newColorOpacity.value)}))

async function addProductColor() {
  const name = newColorName.value.trim()
  if (!name) return
  try {
    await api('/product-colors', 'POST', {
      name, rgb: newColorRgb.value,
      opacity: Number(newColorOpacity.value),
    })
    newColorName.value = ''
    await loadBase()
  } catch {}
}

async function saveProductColor(color) {
  const preview = previewOf(color)
  try {
    const r = await api('/product-colors/' + encodeURIComponent(color.name), 'PUT', {
      rgb: preview.rgb, opacity: Number(preview.opacity),
    })
    productColors.value = productColors.value.map(c =>
      c.name === color.name ? {...c, rgb: r.rgb, opacity: r.opacity} : c)
  } catch {}
}

// Локальные превью редактируемых цветов: при вводе меняется только предпросмотр
// в редакторе (как в прежнем интерфейсе), общее состояние — только после
// успешного сохранения. При перезагрузке справочника превью сбрасываются.
const colorPreviews = reactive({})

function previewOf(color) {
  return colorPreviews[color.name] || {
    rgb: color.rgb || '#ff6384',
    opacity: Number(color.opacity ?? 0.36),
  }
}

function onColorInput(color, field, event) {
  if (!colorPreviews[color.name]) {
    colorPreviews[color.name] = {rgb: color.rgb || '#ff6384', opacity: Number(color.opacity ?? 0.36)}
  }
  colorPreviews[color.name][field] = event.target.value
}

watch(productColors, () => {
  for (const key of Object.keys(colorPreviews)) delete colorPreviews[key]
})

async function deleteProductColor(name) {
  try {
    await api('/product-colors/' + encodeURIComponent(name), 'DELETE')
    await loadBase()
  } catch {}
}

// ================= Разрешённые цвета линейки =================
const colorLineTarget = ref('')
const assignmentChecks = reactive(new Set())

const selectedLineForColors = computed(() =>
  lines.value.find(line => line.name === colorLineTarget.value))

// Если выбранная линейка пропала — берём первую (как select без selected-атрибута)
watch(lines, (list) => {
  if (colorLineTarget.value && !list.some(line => line.name === colorLineTarget.value)) {
    colorLineTarget.value = list[0]?.name || ''
  } else if (!colorLineTarget.value && list.length) {
    colorLineTarget.value = list[0].name
  }
})

// При перезагрузке данных набор галочек восстанавливается из сохранённых цветов линейки
watch(selectedLineForColors, (line) => {
  assignmentChecks.clear()
  for (const name of (line?.product_colors || [])) assignmentChecks.add(name.toLowerCase())
}, {immediate: true})

function checkedColor(color) {
  return assignmentChecks.has(color.name.toLowerCase())
}

function toggleAssignment(color, event) {
  const key = color.name.toLowerCase()
  if (event.target.checked) assignmentChecks.add(key)
  else assignmentChecks.delete(key)
}

async function removeProductColorFromLine(lineName, colorName) {
  const line = lines.value.find(entry => entry.name === lineName)
  if (!line) return
  try {
    await api('/lines/' + encodeURIComponent(lineName) + '/product-colors', 'PUT', {
      colors: line.product_colors.filter(name => name.toLowerCase() !== colorName.toLowerCase()),
    })
    await loadBase()
  } catch {}
}

async function saveLineProductColors() {
  const lineName = colorLineTarget.value
  if (!lineName) return
  const selected = productColors.value
    .filter(color => assignmentChecks.has(color.name.toLowerCase()))
    .map(color => color.name)
  try {
    await api('/lines/' + encodeURIComponent(lineName) + '/product-colors', 'PUT', {
      colors: selected,
    })
    await loadBase()
  } catch {}
}
</script>

<template>
  <div class="bar no-print">API: <input id="api" class="l" aria-label="Адрес API" v-model="apiInput">
    <button @click="reload()">Обновить</button></div>
  <div class="bar no-print">
    <b>Добавить линейку:</b>
    <input id="line-name" class="m" placeholder="Название" v-model="newLineName">
    <select id="line-color" aria-label="Цвет линейки" v-model="newLineColor">
      <option v-for="(color, index) in COLORS" :key="color.name" :value="String(index)">{{ color.name }}</option>
    </select>
    <button class="btn-accent btn-add" @click="addLine()">Добавить</button>
  </div>
  <details class="line-settings no-print" open>
    <summary>Линейки и их оформление</summary>
    <div id="line-settings">
      <label class="line-setting" v-for="line in lines" :key="line.name">
        <span class="line-chip" :style="{background: COLORS[line.color].css}">{{ line.name }}</span>
        <select :aria-label="'Цвет линейки ' + line.name" :value="String(line.color)"
          @change="updateLineColor(line.name, $event.target.value)">
          <option v-for="(color, index) in COLORS" :key="color.name" :value="String(index)">{{ color.name }}</option>
        </select>
        <button type="button" @click="deleteLine(line.name)">Удалить</button>
      </label>
    </div>
  </details>
  <div class="bar no-print">
    <b>Добавить цвет:</b>
    <input id="product-color-name" class="m" placeholder="Название цвета" maxlength="100" v-model="newColorName">
    <span class="color-picker-inputs">
      <label>RGB <input id="product-color-rgb" type="color" v-model="newColorRgb" aria-label="RGB цвета"></label>
      <label>Прозрачность <input id="product-color-opacity" type="range" min="0" max="1" step="0.01"
        v-model="newColorOpacity" aria-label="Прозрачность"></label>
      <output id="product-color-opacity-value">{{ Math.round(Number(newColorOpacity) * 100) }}%</output>
      <span id="product-color-preview" class="color-preview" aria-hidden="true" :style="{backgroundColor: newColorPreview}"></span>
    </span>
    <button class="btn-accent btn-add" @click="addProductColor()">Добавить</button>
  </div>
  <details class="product-color-settings no-print">
    <summary>Цвет и прозрачность существующих цветов</summary>
    <div id="product-color-settings">
      <div class="product-color-editor" v-for="color in productColors" :key="color.name">
        <span>{{ color.name }}</span>
        <span class="color-preview" :style="{background: colorCss(previewOf(color))}" aria-hidden="true"></span>
        <label>RGB <input type="color" :value="previewOf(color).rgb" :aria-label="'RGB цвета ' + color.name"
          @input="onColorInput(color, 'rgb', $event)" @change="saveProductColor(color)"></label>
        <label>Прозрачность <input type="range" min="0" max="1" step="0.01"
          :value="previewOf(color).opacity" :aria-label="'Прозрачность цвета ' + color.name"
          @input="onColorInput(color, 'opacity', $event)" @change="saveProductColor(color)"></label>
        <output>{{ Math.round(Number(previewOf(color).opacity) * 100) }}%</output>
        <button type="button" :aria-label="'Удалить цвет ' + color.name"
          @click="deleteProductColor(color.name)">Удалить</button>
      </div>
    </div>
  </details>
  <div class="color-assignment no-print">
    <label for="color-line-target"><b>Разрешённые цвета линейки:</b></label>
    <select id="color-line-target" aria-label="Линейка для настройки цветов" :value="colorLineTarget"
      :disabled="lines.length === 0" @change="colorLineTarget = $event.target.value">
      <option v-for="line in lines" :key="line.name" :value="line.name">{{ line.name }}</option>
    </select>
    <div id="line-product-colors">
      <template v-if="selectedLineForColors">
        <template v-if="productColors.length">
          <label class="product-color-option" v-for="color in productColors" :key="color.name">
            <input type="checkbox" :value="color.name" :checked="checkedColor(color)"
              @change="toggleAssignment(color, $event)">
            <span class="line-chip" :style="{background: colorCss(color)}">{{ color.name }}</span>
            <button v-if="checkedColor(color)" type="button"
              @click="removeProductColorFromLine(selectedLineForColors.name, color.name)">Убрать</button>
            <button type="button" @click="deleteProductColor(color.name)">Удалить насовсем</button>
          </label>
        </template>
        <span v-else class="hint">Сначала добавьте цвета в справочник.</span>
      </template>
      <span v-else class="hint">Сначала добавьте линейку.</span>
    </div>
    <button id="save-line-colors" type="button" class="btn-accent" :disabled="!selectedLineForColors"
      @click="saveLineProductColors()">Сохранить цвета линейки</button>
  </div>
</template>
