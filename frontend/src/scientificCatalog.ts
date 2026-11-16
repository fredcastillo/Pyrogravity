export function scientificCatalogUrl(section = ''): string {
  const path = document.querySelector<HTMLMetaElement>('meta[name="pyrogravity-science"]')?.content
    ?? '/assets/science/index.html'
  return `${path}${section ? `#${section}` : ''}`
}
