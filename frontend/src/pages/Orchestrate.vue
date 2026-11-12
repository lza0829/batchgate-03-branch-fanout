<script setup>
import { onMounted, ref } from 'vue'
import { getJSON, postJSON } from '../api'
const history = ref([])
const last = ref(null)
const busy = ref(false)
const err = ref('')
async function refresh() { history.value = await getJSON('/api/orchestrations') }
async function runOnce() {
  err.value = ''; busy.value = true
  try {
    last.value = await postJSON('/api/orchestrations')
    await refresh()
  } catch (e) { err.value = String(e.message || e) }
  finally { busy.value = false }
}
onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>编排台</h1>
    <p class="muted">
      触发一次全图编排：依赖边先做就绪闸，再按上游产出评估分支条件；
      条件未命中走 <span class="tag warn">skipped_branch</span> 旁路（不跑夹具），
      互斥组内只允许一个下游执行，其余 <span class="tag warn">skipped_mutex</span>；
      依赖未就绪为 <span class="tag warn">skipped_dep</span>。水位只推进实际成功的作业。
    </p>
    <div class="panel">
      <button :disabled="busy" @click="runOnce">{{ busy ? '编排中…' : '执行编排' }}</button>
    </div>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" v-if="last">
      <h3>最近一次报告 #{{ last.id }} · <span class="tag" :class="last.status==='ok'?'ok':'danger'">{{ last.status }}</span></h3>
      <p class="report-buckets">
        <span class="tag ok">成功 {{ last.report?.succeeded }}</span>
        <span class="tag danger">失败 {{ last.report?.failed }}</span>
        <span class="tag warn">旁路 {{ last.report?.skipped_branch }}</span>
        <span class="tag warn">互斥 {{ last.report?.skipped_mutex }}</span>
        <span class="tag warn">依赖跳过 {{ last.report?.skipped_dep }}</span>
        <span class="tag">合计尝试 {{ last.report?.attempt_count }} / {{ last.report?.job_total }}</span>
      </p>
      <table v-if="last.report?.job_statuses?.length">
        <thead><tr><th>作业</th><th>状态</th><th>原因</th></tr></thead>
        <tbody>
          <tr v-for="js in last.report.job_statuses" :key="js.job_name">
            <td class="mono">{{ js.job_name }}</td>
            <td>
              <span class="tag" :class="js.status==='success'?'ok':(js.status==='failed'?'danger':'warn')">{{ js.status }}</span>
            </td>
            <td class="mono muted">{{ js.reason || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p class="mono muted">watermarked_jobs={{ last.report?.watermarked_jobs }} layers={{ last.report?.layer_count }}</p>
      <p>
        <router-link :to="{ path: '/attempts', query: { orchestration_id: last.id } }">查看本次尝试 →</router-link>
        ·
        <router-link to="/watermarks">产出水位 →</router-link>
        ·
        <router-link to="/jobs">分支配置 →</router-link>
      </p>
    </div>
    <div class="panel">
      <h3>历史编排</h3>
      <table>
        <thead><tr><th>ID</th><th>状态</th><th>成功</th><th>失败</th><th>旁路</th><th>互斥</th><th>依赖跳过</th><th>开始</th></tr></thead>
        <tbody>
          <tr v-for="o in history" :key="o.id">
            <td>{{ o.id }}</td>
            <td>{{ o.status }}</td>
            <td>{{ o.report?.succeeded }}</td>
            <td>{{ o.report?.failed }}</td>
            <td>{{ o.report?.skipped_branch ?? 0 }}</td>
            <td>{{ o.report?.skipped_mutex ?? 0 }}</td>
            <td>{{ o.report?.skipped_dep ?? (o.report?.skipped ?? 0) }}</td>
            <td class="mono">{{ o.started_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
<style scoped>
.report-buckets { display: flex; flex-wrap: wrap; gap: 0.45rem; }
</style>
