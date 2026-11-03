// Экспорт таблицы сравнения МойСклад в Excel (.xls, XML Spreadsheet).
// Порт saveMoyskladSnapshot() из старого index.html без изменений формата.

export async function saveMoyskladSnapshot(rows, lastUpdatedAt, setStatus) {
  const downloadedAt = new Date()
  const formatDateTime = value => value
    ? new Intl.DateTimeFormat('ru-RU', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).format(value)
    : 'Данные ещё не обновлялись'
  const xmlEscape = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;',
  }[character]))
  const stringCell = (value, style = '') =>
    `<Cell${style ? ` ss:StyleID="${style}"` : ''}><Data ss:Type="String">${xmlEscape(value)}</Data></Cell>`
  const numberCell = (value, style = '') => Number.isFinite(Number(value))
    ? `<Cell${style ? ` ss:StyleID="${style}"` : ''}><Data ss:Type="Number">${Number(value)}</Data></Cell>`
    : '<Cell/>'
  const contentRows = [
    `<Row>${stringCell('Дата и время скачивания', 'MetaLabel')}${stringCell(formatDateTime(downloadedAt), 'MetaValue')}</Row>`,
    `<Row>${stringCell('Дата и время последнего обновления', 'MetaLabel')}${stringCell(formatDateTime(lastUpdatedAt), 'MetaValue')}</Row>`,
    `<Row/>`,
    `<Row>${[
      'Название из базы', 'Количество в базе', 'Название из МойСклад',
      'Количество в МойСклад', 'Разница (база − МойСклад)',
    ].map(value => stringCell(value, 'Header')).join('')}</Row>`,
    ...rows.map((row, index) => {
      const style = index % 2 === 0 ? 'Stripe' : ''
      return `<Row>${stringCell(row.local_name, style)}${numberCell(row.local_quantity, style)}${stringCell(row.moysklad_name, style)}${numberCell(row.moysklad_quantity, style)}${numberCell(row.difference, style)}</Row>`
    }),
  ]
  const content = `<?xml version="1.0" encoding="UTF-8"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
  xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
  <Styles>
    <Style ss:ID="Default" ss:Name="Normal"><Alignment ss:Vertical="Center"/></Style>
    <Style ss:ID="MetaLabel"><Font ss:Bold="1"/></Style>
    <Style ss:ID="MetaValue"><NumberFormat ss:Format="@" /></Style>
    <Style ss:ID="Header"><Font ss:Bold="1"/><Interior ss:Color="#D9D9D9" ss:Pattern="Solid"/><Alignment ss:WrapText="1" ss:Vertical="Center"/></Style>
    <Style ss:ID="Stripe"><Interior ss:Color="#E6E6E6" ss:Pattern="Solid"/></Style>
  </Styles>
  <Worksheet ss:Name="Сравнение">
    <Table>
      <Column ss:Width="180"/><Column ss:Width="110"/><Column ss:Width="220"/><Column ss:Width="150"/><Column ss:Width="180"/>
      ${contentRows.join('\n      ')}
    </Table>
  </Worksheet>
</Workbook>`
  const filename = `moysklad-comparison-${downloadedAt.toISOString().replace(/[:.]/g, '-')}.xls`
  const downloadFile = () => {
    const url = URL.createObjectURL(new Blob([content], {
      type: 'application/vnd.ms-excel;charset=utf-8',
    }))
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.style.position = 'fixed'
    link.style.left = '-10000px'
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 30000)
  }
  try {
    if (typeof window.showSaveFilePicker !== 'function') {
      downloadFile()
      setStatus(
        'Файл скачивается. Чтобы каждый раз выбирать папку, включите в настройках браузера запрос места сохранения.')
      return
    }
    const handle = await window.showSaveFilePicker({
      suggestedName: filename,
      types: [{description: 'Таблица Excel', accept: {'application/vnd.ms-excel': ['.xls']}}],
    })
    const file = await handle.createWritable()
    await file.write(content)
    await file.close()
    setStatus('Таблица сохранена в файл Excel.')
  } catch (error) {
    if (error.name === 'AbortError') return
    try {
      downloadFile()
      setStatus(
        'Файл скачивается. Диалог выбора места недоступен; папка определяется настройками загрузок браузера.')
    } catch (downloadError) {
      setStatus(
        `Не удалось сохранить файл: ${downloadError.message || error.message || 'неизвестная ошибка'}`)
    }
  }
}
