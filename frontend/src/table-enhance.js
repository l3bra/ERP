import { colorValue } from './format.js'

// Заливки строк/колонок/ячеек (сохранены на сервере) + изменение размеров таблиц.
// Порт прежней логики enhanceTables() из старого index.html. Ключи строк/колонок
// и ключи localStorage обязаны совпадать со старыми.

export function getStyle(savedStyles, table, kind, row, column) {
  return savedStyles.find(s => s.table === table && s.kind === kind &&
    s.row === row && s.column === column)
}

export function cellColor(savedStyles, table, row, column) {
  const styles = [
    getStyle(savedStyles, table, 'column', '*', column),
    getStyle(savedStyles, table, 'row', row, '*'),
    getStyle(savedStyles, table, 'cell', row, column),
  ].filter(Boolean)
  return styles.length ? colorValue(styles[styles.length - 1].color) : ''
}

export function applyTableStyles(table, savedStyles) {
  const tableName = table.dataset.styleTable
  const occupiedUntil = new Map()
  table.querySelectorAll('tr').forEach((tr, rowIndex) => {
    if (!tr.dataset.styleRow) tr.dataset.styleRow = `row-${rowIndex}`
    let columnIndex = 0
    ;[...tr.cells].forEach(cell => {
      while ((occupiedUntil.get(columnIndex) ?? -1) >= rowIndex) columnIndex++
      cell.dataset.styleCol = String(columnIndex)
      cell.style.backgroundColor = cellColor(savedStyles, tableName, tr.dataset.styleRow, String(columnIndex))
      const lastRow = rowIndex + cell.rowSpan - 1
      for (let span = 0; span < cell.colSpan; span++) {
        occupiedUntil.set(columnIndex + span, lastRow)
      }
      columnIndex += cell.colSpan
    })
  })
}

export function resizeStorageKey(tableId, kind, key) {
  return `warehouse-size:${tableId}:${kind}:${key}`
}

export function setupResizableTables(table) {
  const tableId = table.dataset.resizeId
  if (!tableId) return
  table.dataset.resizable = 'true'
  table.querySelectorAll('.resize-col, .resize-row').forEach(handle => handle.remove())
  const rows = [...table.rows]
  if (!rows.length) return
  const columnCount = Math.max(...rows.map(row => row.cells.length))
  let colgroup = table.querySelector('colgroup')
  if (!colgroup) {
    colgroup = document.createElement('colgroup')
    table.insertBefore(colgroup, table.firstChild)
  }
  while (colgroup.children.length < columnCount) colgroup.appendChild(document.createElement('col'))
  ;[...colgroup.children].forEach((col, index) => {
    const saved = localStorage.getItem(resizeStorageKey(tableId, 'column', index))
    if (saved) col.style.width = `${Number(saved)}px`
  })

  rows.forEach((row, rowIndex) => {
    const rowKey = row.dataset.styleRow || String(rowIndex)
    const savedHeight = localStorage.getItem(resizeStorageKey(tableId, 'row', rowKey))
    if (savedHeight) row.style.height = `${Number(savedHeight)}px`
    const lastCell = row.cells[row.cells.length - 1]
    if (lastCell) {
      const rowHandle = document.createElement('span')
      rowHandle.className = 'resize-row'
      rowHandle.title = 'Изменить высоту строки'
      rowHandle.addEventListener('pointerdown', event => {
        event.preventDefault()
        event.stopPropagation()
        const startY = event.clientY, startHeight = row.getBoundingClientRect().height
        const move = e => {
          const height = Math.max(24, startHeight + e.clientY - startY)
          row.style.height = `${height}px`
        }
        const end = () => {
          document.removeEventListener('pointermove', move)
          document.removeEventListener('pointerup', end)
          localStorage.setItem(resizeStorageKey(tableId, 'row', rowKey), row.offsetHeight)
        }
        document.addEventListener('pointermove', move)
        document.addEventListener('pointerup', end)
      })
      lastCell.appendChild(rowHandle)
    }
  })

  Array.from(rows[0].cells).forEach((cell, index) => {
    const handle = document.createElement('span')
    handle.className = 'resize-col'
    handle.title = 'Изменить ширину столбца'
    handle.addEventListener('pointerdown', event => {
      event.preventDefault()
      event.stopPropagation()
      const startX = event.clientX
      const startWidth = colgroup.children[index].getBoundingClientRect().width
      const move = e => {
        const width = Math.max(40, startWidth + e.clientX - startX)
        colgroup.children[index].style.width = `${width}px`
      }
      const end = () => {
        document.removeEventListener('pointermove', move)
        document.removeEventListener('pointerup', end)
        localStorage.setItem(resizeStorageKey(tableId, 'column', index),
          Math.round(colgroup.children[index].getBoundingClientRect().width))
      }
      document.addEventListener('pointermove', move)
      document.addEventListener('pointerup', end)
    })
    cell.appendChild(handle)
  })
}

// root — элемент таблицы (или контейнер: тогда обрабатываются все таблицы внутри)
export function enhanceTables(root, savedStyles) {
  if (!root) return
  const tables = root.matches('table') ? [root] : [...root.querySelectorAll('table')]
  for (const table of tables) {
    if (table.dataset.styleTable) applyTableStyles(table, savedStyles)
    if (table.dataset.resizeId) setupResizableTables(table)
  }
}
