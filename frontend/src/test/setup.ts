import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'
import '@testing-library/jest-dom/vitest'

// jsdom exposes HTMLDialogElement but does not implement its modal methods.
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
}

if (!HTMLDialogElement.prototype.close) {
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
    this.dispatchEvent(new Event('close'))
  }
}

// jsdom does not implement matchMedia at all. The theme layer degrades safely
// when it is missing, but stubbing it keeps tests on the same code path as the
// browser (subscribe/unsubscribe included). Tests that care about the OS
// preference override `matches` on the object this returns.
if (!window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList => {
    const listeners = new Set<EventListenerOrEventListenerObject>()
    return {
      matches: false,
      media: query,
      onchange: null,
      addEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
        listeners.add(listener)
      },
      removeEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
        listeners.delete(listener)
      },
      dispatchEvent: () => true,
      addListener: () => {},
      removeListener: () => {},
    } as unknown as MediaQueryList
  }
}

// testing-library's auto-cleanup only self-registers when vitest's `globals`
// option is enabled; this project imports `afterEach` explicitly instead
// (see vite.config.ts), so cleanup is wired up here to run after every test
// and prevent DOM from one test leaking into the next.
afterEach(() => {
  cleanup()
})
