import { reactive } from 'vue'

export const chatRunState = reactive({
  busy: false,
})

export function setChatBusy(busy: boolean) {
  chatRunState.busy = busy
}
