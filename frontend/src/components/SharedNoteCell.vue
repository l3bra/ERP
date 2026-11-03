<script setup>
import { computed } from 'vue'
import { openNoteGroupDialog, unmergeNoteGroup } from '../state.js'

const props = defineProps({
  log: { type: Object, required: true },
  count: { type: Number, required: true },
})

const totalCount = computed(() => props.log.shared_note_count || props.count)
</script>

<template>
  <td class="shared-note-cell" :rowspan="count">
    <div class="shared-note-box"><span class="shared-note-badge">Общее примечание · для {{ totalCount }} операций</span>
      <b v-if="log.shared_note_code">{{ log.shared_note_code }}</b>
      <span v-if="log.shared_note_text">{{ log.shared_note_text }}</span>
      <a v-if="log.shared_note_url" class="note-link" :href="log.shared_note_url" target="_blank"
        rel="noopener noreferrer">Открыть ссылку ↗</a>
      <div class="shared-note-actions">
        <button type="button" @click="openNoteGroupDialog(log.shared_note_group_id)">Изменить</button>
        <button type="button" @click="unmergeNoteGroup(log.shared_note_group_id)">Разъединить</button>
      </div>
    </div>
  </td>
</template>
