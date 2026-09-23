<script setup>
import { ref, computed, watch } from 'vue'
import {
  NConfigProvider, NMessageProvider, NDialogProvider, NGlobalStyle,
  darkTheme, zhCN, dateZhCN,
} from 'naive-ui'
import AppShell from './components/AppShell.vue'

// 暗色模式：?dark=1 或上次的选择
const dark = ref(
  new URLSearchParams(location.search).has('dark') ||
    localStorage.getItem('mm_dark') === '1',
)
watch(dark, (v) => localStorage.setItem('mm_dark', v ? '1' : '0'))
const theme = computed(() => (dark.value ? darkTheme : null))
</script>

<template>
  <n-config-provider :theme="theme" :locale="zhCN" :date-locale="dateZhCN">
    <n-global-style />
    <n-message-provider>
      <n-dialog-provider>
        <app-shell v-model:dark="dark" />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
