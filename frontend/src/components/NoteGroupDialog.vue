<script setup>
import { onMounted, onBeforeUnmount } from 'vue'
import {
  noteGroupVisible, noteGroupTitle, noteGroupDescription,
  noteGroupCode, noteGroupUrl, noteGroupText, noteGroupError,
  noteGroupSaveLabel, noteGroupSaving,
  closeNoteGroupDialog, saveNoteGroup,
} from '../state.js'

function onKeydown(event) {
  if (event.key === 'Escape' && noteGroupVisible.value) {
    closeNoteGroupDialog()
  }
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div id="note-group-overlay" class="note-group-overlay" :class="{hidden: !noteGroupVisible}"
    @click.self="closeNoteGroupDialog()">
    <div class="note-group-panel" role="dialog" aria-modal="true" aria-labelledby="note-group-title">
      <h3 id="note-group-title">{{ noteGroupTitle }}</h3>
      <p id="note-group-description" class="hint">{{ noteGroupDescription }}</p>
      <label>Код документа
        <input id="note-group-code" maxlength="120" placeholder="Например, РН-004281" v-model="noteGroupCode">
      </label>
      <label>Ссылка на документ
        <input id="note-group-url" type="url" maxlength="2000" placeholder="https://..." v-model="noteGroupUrl">
      </label>
      <label>Текст примечания
        <textarea id="note-group-text" maxlength="1000" placeholder="Краткое примечание" v-model="noteGroupText"></textarea>
      </label>
      <div id="note-group-error" class="note-group-error" role="alert">{{ noteGroupError }}</div>
      <div class="note-group-actions">
        <button type="button" @click="closeNoteGroupDialog()">Отмена</button>
        <button id="note-group-save" type="button" class="btn-accent" :disabled="noteGroupSaving"
          @click="saveNoteGroup()">{{ noteGroupSaveLabel }}</button>
      </div>
    </div>
  </div>
</template>
