/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

declare module 'element-plus/es/locale/lang/zh-cn' {
  const zhCn: Record<string, unknown>
  export default zhCn
}
