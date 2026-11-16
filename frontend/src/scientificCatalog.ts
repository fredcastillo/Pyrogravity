export function scientificCatalogUrl(section = '', parameters?: Record<string, string>): string {
  const path = document.querySelector<HTMLMetaElement>('meta[name="pyrogravity-science"]')?.content
    ?? '/assets/science/index.html'
  const search = parameters ? `?${new URLSearchParams(parameters)}` : ''
  return `${path}${search}${section ? `#${section}` : ''}`
}
