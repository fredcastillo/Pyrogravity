import { enableOrbitalField, watchReveal } from './motion'

const canvas = document.querySelector<HTMLCanvasElement>('.orbital-canvas')
if (canvas) enableOrbitalField(canvas)

const main = document.querySelector('main')
if (main) watchReveal(main)

const slot = document.querySelector<HTMLElement>('#atlas-chat')
const launcher = document.querySelector<HTMLButtonElement>('#atlas-chat-launch')
const status = document.querySelector('#atlas-chat-status')
let loadingChat = false
function openAtlasChat(event: MouseEvent) {
  const trigger = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-open-pyrogravity-chat]') : null
  if (!trigger || !slot || !launcher || loadingChat) return
  loadingChat = true
  launcher.disabled = true
  if (status) status.textContent = 'Abriendo el chat…'
  void import('./atlasChat').then(({ mountAtlasChat }) => {
    launcher.hidden = true
    if (status) status.textContent = ''
    document.removeEventListener('click', openAtlasChat)
    mountAtlasChat(slot, trigger)
  }).catch(() => {
    if (status) status.textContent = 'El chat no pudo abrirse. Pulsa para reintentar.'
    launcher.disabled = false
  }).finally(() => { loadingChat = false })
}
document.addEventListener('click', openAtlasChat)
