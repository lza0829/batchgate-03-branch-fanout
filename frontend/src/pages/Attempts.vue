<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON } from '../api'
const route = useRoute()
const orchId = ref(null)
const orchList = ref([])
const rows = ref([])
const err = ref('')
function tagClass(status) {
  if (status === 'success') return 'ok'
  if (status === 'failed') return 'danger'
  return 'warn'
}
async function load() {
  err.value = ''
  try {
    const q = orchId.value != null ? `?orchestration_id=${orchId.value}` : ''
    rows.value = await getJSON(`/api/attempts${q}`)
  } catch (e) { err.value = String(e.message || e) }
}
onMounted(async () => {
  try {
    orchList.value = await getJSON('/api/orchestrations')
    const q = Number(route.query.orchestration_id)
    if (q) orchId.value = q
    await load()
  } catch (e) { err.value = String(e.message || e) }
})
watch(orchId, load)
</script>
<template>
  <div class="page">
    <h1>尝试记录</h1>
    <p class="muted">
      状态分四类：<span class="tag ok">success</span> 实际执行成功 ·
      <span class="tag danger">failed</span> 执行失败 ·
      <span class="tag warn">skipped_branch</span> 分支条件未命中旁路（未跑夹具）·
      <span class="tag warn">skipped_mutex</span> 互斥组已被占用 ·
      <span class="tag warn">skipped_dep</span> 依赖未就绪。旁路/互斥/依赖跳过各自独立，原因见详情。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <label>
        编排
        <select v-model.number="orchId">
          <option :value="null">全部</option>
          <option v-for="o in orchList" :key="o.id" :value="o.id">#{{ o.id }} · {{ o.status }}</option>
        </select>
      </label>
      <span class="muted" style="margin-left:0.75rem">共 {{ rows.length }} 条</span>
    </div>
    <div class="panel">
      <table>
        <thead><tr><th>ID</th><th>编排</th><th>作业</th><th>次</th><th>状态</th><th>旁路/失败原因</th><th>详情</th></tr></thead>
        <tbody>
          <tr v-for="a in rows" :key="a.id">
            <td>{{ a.id }}</td>
            <td>{{ a.orchestration_id }}</td>
            <td class="mono">{{ a.job_name }}</td>
            <td>{{ a.attempt_no }}</td>
            <td><span class="tag" :class="tagClass(a.status)">{{ a.status }}</span></td>
            <td class="mono" style="max-width:24rem">
              <span v-if="a.detail?.reason" class="reason">{{ a.detail.reason }}</span>
              <span v-else class="muted">—</span>
            </td>
            <td class="mono muted detail">{{ JSON.stringify(a.detail) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
<style scoped>
.reason { color: var(--warn); }
.detail { max-width: 30rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
