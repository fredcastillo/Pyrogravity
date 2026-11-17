import { createRoot } from 'react-dom/client'
import { ChatWidget } from '../components/ChatWidget'

export function mountAtlasChat(container: HTMLElement, trigger: HTMLElement) {
  createRoot(container).render(<ChatWidget autoOpen trigger={trigger} />)
}
