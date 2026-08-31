import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'
import '@testing-library/jest-dom/vitest'

// testing-library's auto-cleanup only self-registers when vitest's `globals`
// option is enabled; this project imports `afterEach` explicitly instead
// (see vite.config.ts), so cleanup is wired up here to run after every test
// and prevent DOM from one test leaking into the next.
afterEach(() => {
  cleanup()
})
