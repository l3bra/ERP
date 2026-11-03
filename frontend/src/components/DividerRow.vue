<script setup>
import { updLog, delLog } from '../state.js'

defineProps({
  log: { type: Object, required: true },
  visible: { type: Boolean, default: true },
})
</script>

<template>
  <tr :data-style-row="log.id" data-log-row
    :class="['row-div', log.type === 'inventory' ? 'inv' : '', {hidden: !visible}]">
    <td colspan="9">
      <input :value="log.note" @change="updLog(log.id, {note: $event.target.value}, $event.target)">
    </td>
    <td><button @click="delLog(log.id)">✕</button></td>
    <td></td>
  </tr>
</template>
