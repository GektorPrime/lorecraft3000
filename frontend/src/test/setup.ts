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

// testing-library's auto-cleanup only self-registers when vitest's `globals`
// option is enabled; this project imports `afterEach` explicitly instead
// (see vite.config.ts), so cleanup is wired up here to run after every test
// and prevent DOM from one test leaking into the next.
afterEach(() => {
  cleanup()
})
