import { vi } from 'vitest'
import '@testing-library/jest-dom'

class MockWebSocket {
  static OPEN = 1
  readyState = MockWebSocket.OPEN
  url: string
  onopen: ((ev?: any) => any) | null = null
  onmessage: ((ev: any) => any) | null = null
  onclose: ((ev?: any) => any) | null = null
  constructor(url: string) {
    this.url = url
    setTimeout(() => this.onopen && this.onopen({}), 0)
  }
  send(_data: any) {}
  close() { this.onclose && this.onclose({}) }
  addEventListener() {}
  removeEventListener() {}
}

vi.stubGlobal('WebSocket', MockWebSocket)

// Avoid errors if navigator.mediaDevices is touched in tests
if (!('mediaDevices' in navigator)) {
  // @ts-expect-error partial mock
  navigator.mediaDevices = {}
}
// @ts-expect-error partial mock
navigator.mediaDevices.getUserMedia = vi.fn(() => Promise.reject(new Error('mock getUserMedia')))
