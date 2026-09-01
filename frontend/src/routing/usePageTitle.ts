import { useEffect } from 'react'

export const APP_TITLE = 'LoreCraft3000'

export function formatPageTitle(title?: string | null) {
  return title ? `${title} | ${APP_TITLE}` : APP_TITLE
}

export function usePageTitle(title?: string | null) {
  useEffect(() => {
    const previousTitle = document.title
    document.title = formatPageTitle(title)
    return () => {
      document.title = previousTitle
    }
  }, [title])
}
