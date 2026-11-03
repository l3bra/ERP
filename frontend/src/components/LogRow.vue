<script setup>
import { computed } from 'vue'
import { logTypes, updLog, delLog, openLinkEditor, updateSelection } from '../state.js'
import { fmtTs, parseLinkNote } from '../format.js'
import SharedNoteCell from './SharedNoteCell.vue'

const props = defineProps({
  log: { type: Object, required: true },
  visible: { type: Boolean, default: true },
  shared: { type: Object, default: null }, // { count } — общая ячейка примечания
})

const link = computed(() => parseLinkNote(props.log.note))

const typeOptions = computed(() => {
  const t = props.log.type
  return logTypes.value.includes(t) ? logTypes.value : [...logTypes.value, t]
})

function onTypeChange(event) {
  props.log.type = event.target.value
  updLog(props.log.id, {type: event.target.value}, event.target)
}
</script>

<template>
  <tr :data-style-row="log.id" data-log-row :class="{hidden: !visible}">
    <td>{{ fmtTs(log.ts) }}</td>
    <td><input class="m" :value="log.product"
      @change="updLog(log.id, {product: $event.target.value}, $event.target)"></td>
    <td><input class="m" :value="log.color"
      @change="updLog(log.id, {color: $event.target.value}, $event.target)"></td>
    <td><input class="m" :value="log.batch"
      @change="updLog(log.id, {batch: $event.target.value}, $event.target)"></td>
    <td><input class="s" type="number" :value="log.old_qty ?? ''"
      @change="updLog(log.id, {old_qty: Number($event.target.value)}, $event.target)"></td>
    <td><input class="s" type="number" :value="log.new_qty ?? ''"
      @change="updLog(log.id, {new_qty: Number($event.target.value)}, $event.target)"></td>
    <td class="num" :id="'d' + log.id">{{ log.diff > 0 ? '+' : '' }}{{ log.diff }}</td>
    <td><select :class="{'manager-error': log.type === 'ОШИБКА МЕНЕДЖЕРА'}" :value="log.type"
      @change="onTypeChange">
      <option v-for="t in typeOptions" :key="t" :value="t">{{ t }}</option>
    </select></td>
    <td v-if="shared"><SharedNoteCell :log="log" :count="shared.count" /></td>
    <td v-else>
      <div class="note-cell">
        <a v-if="link" class="note-link" :href="link.url" target="_blank" rel="noopener noreferrer">{{ link.label }}</a>
        <input v-else class="l" :value="log.note"
          @change="updLog(log.id, {note: $event.target.value}, $event.target)">
        <button type="button" class="edit-link" :data-link-log="log.id"
          title="Добавить или изменить ссылку" aria-label="Добавить или изменить ссылку"
          @click="openLinkEditor(log.id)">🔗</button>
      </div>
    </td>
    <td><button @click="delLog(log.id)">✕</button></td>
    <td><input class="journal-row-select" type="checkbox" data-log-select :value="log.id"
      :aria-label="'Выбрать строку ' + log.id" @change="updateSelection"></td>
  </tr>
</template>
