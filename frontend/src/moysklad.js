import { ref, computed, watch } from 'vue'
import { api } from './api.js'

export const tokenInput = ref('')
export const moyskladConfigured = ref(false)
export const moyskladStoreHref = ref('')
export const selectedStoreHref = ref('')
export const moyskladStores = ref([])
export const moyskladStatus = ref('')
export const moyskladTokenStatus = ref('')
export const moyskladStockItems = ref([])
export const moyskladComparison = ref(null)
export const moyskladLoaded = ref(false)
export const moyskladLastUpdatedAt = ref(null)

export const mappingLocalName = ref('')
export const mappingExternalHref = ref('')

export async function loadMoysklad() {
  moyskladStatus.value = 'Обновляю данные «Базы» и МойСклад…'
  try {
    const localData = await api('/moysklad/local-groups')
    localData.stock_items = []
    moyskladComparison.value = localData
    moyskladStockItems.value = localData.stock_items
    moyskladLastUpdatedAt.value = new Date()

    const config = await api('/moysklad/config')
    moyskladConfigured.value = config.configured
    moyskladTokenStatus.value = config.configured
      ? 'Токен сохранён на сервере; само значение не отображается.'
      : 'Токен ещё не настроен.'
    if (!config.configured) {
      moyskladStores.value = []
      selectedStoreHref.value = ''
      moyskladStatus.value =
        'Остатки из «Базы» уже загружены. Добавьте токен позже, чтобы сравнить с МойСклад.'
      return
    }
    await loadMoyskladStores(config.store_href)
  } catch (error) {
    moyskladStatus.value =
      `Не удалось загрузить настройки МойСклад: ${error.message || 'неизвестная ошибка'}`
  }
}

export async function saveMoyskladToken() {
  const token = tokenInput.value.trim()
  if (!token) {
    moyskladStatus.value = 'Введите API-токен.'
    return
  }
  try {
    await api('/moysklad/token', 'PUT', {token})
    tokenInput.value = ''
    moyskladStatus.value = 'Токен сохранён. Загружаю список складов…'
    moyskladLoaded.value = false
    await loadMoysklad()
  } catch {}
}

export async function deleteMoyskladToken() {
  try {
    await api('/moysklad/token', 'DELETE')
    tokenInput.value = ''
    moyskladStatus.value = 'Токен удалён.'
    moyskladLoaded.value = false
    await loadMoysklad()
  } catch {}
}

export async function loadMoyskladStores(selectedHref = selectedStoreHref.value) {
  try {
    const stores = await api('/moysklad/stores')
    moyskladStores.value = stores
    if (stores.some(store => store.href === selectedHref)) {
      selectedStoreHref.value = selectedHref
      await loadMoyskladComparison()
    } else {
      selectedStoreHref.value = ''
      moyskladStatus.value = stores.length
        ? 'Остатки из «Базы» загружены. Выберите склад МойСклад, чтобы продолжить сравнение.'
        : 'В аккаунте МойСклад не найдено складов.'
      moyskladLoaded.value = false
    }
  } catch (error) {
    moyskladStores.value = []
    moyskladStatus.value =
      `Остатки из «Базы» показаны. Не удалось загрузить склады МойСклад: ${error.message || 'неизвестная ошибка'}`
  }
}

export async function selectMoyskladStore() {
  const href = selectedStoreHref.value
  if (!href) {
    if (moyskladComparison.value) {
      moyskladComparison.value = {...moyskladComparison.value, stock_items: []}
      moyskladStockItems.value = []
    }
    moyskladStatus.value =
      'Остатки из «Базы» остаются на экране. Выберите склад МойСклад для сравнения.'
    return
  }
  try {
    await api('/moysklad/store', 'PUT', {href})
    await loadMoyskladComparison()
  } catch {}
}

export async function loadMoyskladComparison() {
  if (!selectedStoreHref.value) {
    moyskladStatus.value = 'Сначала выберите склад МойСклад.'
    return
  }
  moyskladStatus.value = 'Загружаю остатки и сравниваю…'
  try {
    const comparison = await api('/moysklad/compare')
    moyskladComparison.value = comparison
    moyskladStockItems.value = comparison.stock_items
    moyskladLoaded.value = true
    moyskladLastUpdatedAt.value = new Date()
    moyskladStatus.value =
      `Загружено товаров МойСклад: ${comparison.stock_items.length}. Разница считается как «База − МойСклад».`
  } catch (error) {
    moyskladStatus.value =
      `Не удалось загрузить остатки МойСклад: ${error.message || 'неизвестная ошибка'}`
  }
}

function matchData(data) {
  const stockByHref = new Map(moyskladStockItems.value.map(item => [item.href, item]))
  const assignedHrefs = new Set(Object.values(data.mappings).filter(Boolean))
  const exactMatches = new Map()
  for (const group of data.groups) {
    const localKey = group.name.toLocaleLowerCase()
    if (Object.prototype.hasOwnProperty.call(data.mappings, localKey)) continue
    const matches = moyskladStockItems.value.filter(item =>
      item.name.toLocaleLowerCase() === group.name.toLocaleLowerCase() &&
      !assignedHrefs.has(item.href))
    if (matches.length === 1) {
      exactMatches.set(localKey, matches[0].href)
      assignedHrefs.add(matches[0].href)
    }
  }
  return {stockByHref, exactMatches}
}

export const comparisonRows = computed(() => {
  const data = moyskladComparison.value
  if (!data) return []
  const {stockByHref, exactMatches} = matchData(data)
  const rows = []
  for (const group of data.groups) {
    const localKey = group.name.toLocaleLowerCase()
    const hasMapping = Object.prototype.hasOwnProperty.call(data.mappings, localKey)
    const selectedHref = hasMapping
      ? data.mappings[localKey]
      : (exactMatches.get(localKey) || '')
    const remote = selectedHref ? stockByHref.get(selectedHref) : null
    const diff = remote
      ? Math.round((Number(group.quantity) - Number(remote.quantity)) * 1000) / 1000
      : null
    rows.push({group, remote, diff})
  }
  return rows
})

export const snapshotRows = computed(() => comparisonRows.value.map(row => ({
  local_name: row.group.name,
  local_quantity: Number(row.group.quantity),
  moysklad_name: row.remote ? row.remote.name : null,
  moysklad_quantity: row.remote ? Number(row.remote.quantity) : null,
  difference: row.diff,
})))

// Выбор названия из базы: при смене набора групп сохраняем прежнее, иначе первое
watch(
  () => moyskladComparison.value ? moyskladComparison.value.groups : [],
  (groups) => {
    if (!groups.length) { mappingLocalName.value = ''; return }
    if (!groups.some(group => group.name === mappingLocalName.value)) {
      mappingLocalName.value = groups[0].name
    }
  },
)

// Значение по умолчанию для выбора товара МойСклад (сохранённое сопоставление
// или точное совпадение названия); при его смене синхронизируем select
export const mappingDefaultHref = computed(() => {
  const data = moyskladComparison.value
  if (!data || !mappingLocalName.value) return ''
  const key = mappingLocalName.value.toLocaleLowerCase()
  if (Object.prototype.hasOwnProperty.call(data.mappings, key)) {
    return data.mappings[key] || ''
  }
  return matchData(data).exactMatches.get(key) || ''
})

watch(mappingDefaultHref, (href) => { mappingExternalHref.value = href })

export const mappingAssignedElsewhere = computed(() => {
  const data = moyskladComparison.value
  const key = mappingLocalName.value.toLocaleLowerCase()
  if (!data) return new Set()
  return new Set(Object.entries(data.mappings)
    .filter(([name, href]) => name !== key && href)
    .map(([, href]) => href))
})

export const mappingExternalOptions = computed(() => {
  const assignedElsewhere = mappingAssignedElsewhere.value
  return moyskladStockItems.value.map(item => {
    const label = `${item.name}${item.article ? ` — ${item.article}` : ''}${item.code ? ` (${item.code})` : ''}`
    return {href: item.href, label, disabled: assignedElsewhere.has(item.href)}
  })
})

export const mappingExternalMissing = computed(() =>
  Boolean(mappingExternalHref.value) &&
  !moyskladStockItems.value.some(item => item.href === mappingExternalHref.value))

export async function saveSelectedMoyskladMapping() {
  const localName = mappingLocalName.value
  if (!localName || !moyskladComparison.value) return
  const assortmentHref = mappingExternalHref.value || null
  try {
    await api('/moysklad/mappings', 'PUT', {
      local_name: localName,
      assortment_href: assortmentHref,
    })
    const data = moyskladComparison.value
    const mappings = {...data.mappings, [localName.toLocaleLowerCase()]: assortmentHref}
    moyskladComparison.value = {...data, mappings}
  } catch {}
}

export async function clearSelectedMoyskladMapping() {
  const localName = mappingLocalName.value
  if (!localName) return
  mappingExternalHref.value = ''
  await saveSelectedMoyskladMapping()
}
