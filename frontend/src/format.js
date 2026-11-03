export const MONTHS = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь']
export const DEFAULT_TYPES = ['ПРИХОД','РАСХОД','НОВАЯ ПАРТИЯ','КОРРЕКЦИЯ','ПРАВКА','УДАЛЕНИЕ']
export const COLORS = [
  {name:'Коралловый', css:'var(--c0)'}, {name:'Оранжевый', css:'var(--c1)'},
  {name:'Жёлтый', css:'var(--c2)'}, {name:'Зелёный', css:'var(--c3)'},
  {name:'Голубой', css:'var(--c4)'}, {name:'Фиолетовый', css:'var(--c5)'},
  {name:'Розовый', css:'var(--c6)'}, {name:'Бирюзовый', css:'var(--c7)'},
  {name:'Салатовый', css:'var(--c8)'}, {name:'Серый', css:'var(--c9)'},
]
export const THEMES = ['clean-light', 'dark-lab', 'resin-glass', 'swiss-technical']
export const LINK_NOTE_PREFIX = '[[ERP_LINK_V1]]'

export const fmtDate = d => d ? d.split('-').reverse().join('.') : ''
export const fmtTs = ts => { const [d, t] = ts.split('T'); return fmtDate(d) + ' ' + t }
export const monthLabel = m => { const [y, mm] = m.split('-'); return MONTHS[+mm - 1] + ' ' + y }
export const currentMonth = () => { const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') }

export function flash(el) {
  if (!el) return
  el.classList.add('saved')
  setTimeout(() => el.classList.remove('saved'), 700)
}

export function colorValue(index) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--c${index}`).trim()
}

export function colorCss(color) {
  const rgb = /^#([0-9a-f]{6})$/i.exec(color.rgb || '')
  if (!rgb) return (COLORS[color.palette_index] || COLORS[0]).css
  const channels = rgb[1].match(/.{2}/g).map(channel => parseInt(channel, 16))
  const opacity = Math.max(0, Math.min(1, Number(color.opacity)))
  return `rgba(${channels.join(', ')}, ${Number.isFinite(opacity) ? opacity : 0.36})`
}

export function productColorCss(name, productColors) {
  const color = productColors.find(entry => entry.name.toLowerCase() === name.toLowerCase())
  return color ? colorCss(color) : ''
}

export function allowedColorsFor(lines, productColors, product) {
  const line = lines.find(entry => entry.name === product)
  return line
    ? productColors.filter(color => line.product_colors.some(name => name.toLowerCase() === color.name.toLowerCase()))
    : productColors
}

export function parseLinkNote(note) {
  if (!note || !note.startsWith(LINK_NOTE_PREFIX)) return null
  try {
    const data = JSON.parse(note.slice(LINK_NOTE_PREFIX.length))
    const url = new URL(data.url)
    if (!data.label || !['http:', 'https:'].includes(url.protocol)) return null
    return {label: data.label, url: url.href}
  } catch {
    return null
  }
}

export function formatMoyskladQuantity(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return Number.isInteger(number)
    ? String(number)
    : number.toLocaleString('ru-RU', {maximumFractionDigits: 3})
}
