<script setup>
import { ref, onMounted, onUpdated } from 'vue'
import { printData, savedStyles } from '../state.js'
import { fmtTs, fmtDate } from '../format.js'
import { enhanceTables } from '../table-enhance.js'

const printEl = ref(null)

function enhance() {
  if (!printEl.value) return
  printEl.value.querySelectorAll('table').forEach(table => enhanceTables(table, savedStyles.value))
}
onMounted(enhance)
onUpdated(enhance)

function doPrint() { window.print() }
</script>

<template>
  <div class="bar"><button @click="doPrint">Печать (А4)</button></div>
  <div id="print-head">{{ printData ? 'Остатки на ' + fmtTs(printData.generated) : '' }}</div>
  <div class="cols" id="print" ref="printEl">
    <div v-if="printData">
      <table v-for="g in printData.left" :key="'l' + g.product" data-style-table="print"
        :data-resize-id="'print-left-' + encodeURIComponent(g.product)">
        <tr :data-style-row="'group:' + encodeURIComponent(g.product)"><th colspan="5">{{ g.product }}</th></tr>
        <tr v-for="r in g.rows" :key="g.product + '|' + r.color + '|' + r.batch"
          :data-style-row="'entry:' + encodeURIComponent([g.product, r.color, r.batch].join('|'))">
          <td>{{ r.color }}</td><td>{{ r.batch }}</td><td>{{ fmtDate(r.date) }}</td>
          <td class="num">{{ r.qty }}</td>
          <td class="fact-cell"><div class="fact-entry"></div></td>
        </tr>
      </table>
    </div>
    <div v-if="printData">
      <table v-for="g in printData.right" :key="'r' + g.product" data-style-table="print"
        :data-resize-id="'print-right-' + encodeURIComponent(g.product)">
        <tr :data-style-row="'group:' + encodeURIComponent(g.product)"><th colspan="5">{{ g.product }}</th></tr>
        <tr v-for="r in g.rows" :key="g.product + '|' + r.color + '|' + r.batch"
          :data-style-row="'entry:' + encodeURIComponent([g.product, r.color, r.batch].join('|'))">
          <td>{{ r.color }}</td><td>{{ r.batch }}</td><td>{{ fmtDate(r.date) }}</td>
          <td class="num">{{ r.qty }}</td>
          <td class="fact-cell"><div class="fact-entry"></div></td>
        </tr>
      </table>
    </div>
  </div>
</template>
