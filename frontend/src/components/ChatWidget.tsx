import { ArrowUpRight, BookOpen, Check, Copy, Database, MessageCircle, RotateCcw, Send, Square, UserRound, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { planChat, studyOnPage, type ChatLink } from '../chatRouting'
import type { AiResponse } from '../contracts/ai'
import { AiHttpError, buildAiQuery, queryAi } from '../services/ai'
import { getStudy, studies, studyIds, type StudyId } from '../studies'
import { spanishCitationSummary } from '../studyQuestions'
import './chatWidget.css'
import pyrogravityMark from '../assets/pyrogravity-mark.png'

type Message = { id: string; role: 'user' | 'assistant'; text: string; links?: ChatLink[]; answer?: AiResponse }
const key = 'pyrogravity-chat-v1'
const initial: Message = {
  id: 'bienvenida', role: 'assistant',
  text: 'Hola, soy el asistente de Pyrogravity. Pregúntame por el fuego en microgravedad, elige un estudio o dime qué datos quieres encontrar.',
}
const suggestions = ['¿Qué estudios hay?', 'Explícame la combustión en microgravedad', 'Resultados de BASS-II']
const studySuggestions = ['¿Qué investigaron?', '¿Cómo hicieron el experimento?', 'Fuentes']

function savedChat(): { messages: Message[]; study?: StudyId } {
  try {
    const raw = sessionStorage.getItem(key)
    if (raw) {
      const value = JSON.parse(raw)
      return { messages: Array.isArray(value.messages) ? value.messages.slice(-24) : [initial],
        study: typeof value.study === 'string' && getStudy(value.study) ? value.study as StudyId : undefined }
    }
  } catch { /* The chat can run without session storage. */ }
  return { messages: [initial] }
}

function safeLink(value: string) {
  try {
    const link = new URL(value, window.location.origin)
    return link.origin === window.location.origin || link.protocol === 'https:' ? link.href : undefined
  } catch { return undefined }
}

function chatbotAnswer(answer: AiResponse) {
  if (answer.status === 'insufficient_evidence') {
    return 'No encontré una fuente que respalde ese detalle. Puedes decirme qué estudio te interesa, pedir el método o indicarme el ensayo y la variable que quieres localizar.'
  }
  const summaries = [...new Set(answer.citations.map(spanishCitationSummary).filter(Boolean))]
  return summaries.length ? summaries.join('\n\n') : answer.answer.replace(/^1\.\s*/, '')
}

export function ChatWidget({ autoOpen = false, trigger }: { autoOpen?: boolean; trigger?: HTMLElement }) {
  const [boot] = useState(savedChat)
  const [messages, setMessages] = useState(boot.messages)
  const [study, setStudy] = useState<StudyId | undefined>(() => studyOnPage() ?? boot.study)
  const [draft, setDraft] = useState('')
  const [opened, setOpened] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [copied, setCopied] = useState<string>()
  const [copyError, setCopyError] = useState('')
  const dialog = useRef<HTMLDialogElement>(null)
  const launch = useRef<HTMLButtonElement>(null)
  const title = useRef<HTMLHeadingElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const log = useRef<HTMLDivElement>(null)
  const origin = useRef<HTMLElement | null>(null)
  const pending = useRef<AbortController | null>(null)

  const openChat = useCallback((source?: HTMLElement) => {
    const panel = dialog.current
    if (!panel || panel.open) return
    origin.current = source ?? launch.current
    panel.showModal()
    setOpened(true)
    if (window.matchMedia('(pointer: fine)').matches) input.current?.focus()
    else title.current?.focus()
  }, [])

  useEffect(() => {
    const handle = (event: MouseEvent) => {
      const node = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-open-pyrogravity-chat]') : null
      if (!node) return
      event.preventDefault()
      openChat(node)
    }
    document.addEventListener('click', handle)
    if (autoOpen) openChat(trigger)
    return () => document.removeEventListener('click', handle)
  }, [autoOpen, openChat, trigger])
  useEffect(() => () => pending.current?.abort(), [])
  useEffect(() => {
    try { sessionStorage.setItem(key, JSON.stringify({ messages: messages.slice(-24), study })) } catch { /* optional */ }
  }, [messages, study])
  useEffect(() => {
    if (opened && log.current) log.current.scrollTop = messages.length === 1 && messages[0].id === initial.id ? 0 : log.current.scrollHeight
  }, [messages, opened, waiting])

  function add(message: Omit<Message, 'id'>) {
    setMessages(current => [...current.filter(item => item.id !== initial.id), { ...message, id: crypto.randomUUID?.() ?? `chat-${Date.now()}-${Math.random()}` }].slice(-24))
  }

  async function send(value: string) {
    const clean = value.trim()
    if (!clean || pending.current || clean.length > 430) return
    add({ role: 'user', text: clean })
    setDraft('')
    const plan = planChat(clean, study)
    if (plan.study) setStudy(plan.study)
    if ('text' in plan) {
      add({ role: 'assistant', text: plan.text, links: plan.links })
      return
    }
    const controller = new AbortController()
    pending.current = controller
    setWaiting(true)
    try {
      const answer = await queryAi(buildAiQuery(plan.question), controller.signal)
      if (controller.signal.aborted) return
      if (plan.source && answer.status !== 'insufficient_evidence' &&
        (!answer.citations.length || answer.citations.some(citation => citation.source !== plan.source))) {
        add({ role: 'assistant', text: 'La búsqueda encontró evidencia de otro estudio. Puedes cambiar la investigación arriba o decirme qué detalle quieres buscar en la selección actual.' })
      } else {
        const links = answer.status === 'insufficient_evidence' && plan.study
          ? [{ title: 'Ver las mediciones del estudio', href: `/estudios/${plan.study}#datos` }] : undefined
        add({ role: 'assistant', text: chatbotAnswer(answer), answer, links })
      }
    } catch (cause) {
      if (!controller.signal.aborted) add({
        role: 'assistant',
        text: cause instanceof AiHttpError && cause.status >= 500
          ? 'La biblioteca tarda en responder. Puedes volver a enviar la pregunta en unos segundos o abrir la ficha para consultar sus datos.'
          : 'No pude completar la consulta. Intenta otra vez o escoge un estudio para acotar la búsqueda.',
      })
    } finally {
      if (pending.current === controller) pending.current = null
      if (!controller.signal.aborted) setWaiting(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    void send(draft)
  }

  async function copyAnswer(message: Message) {
    try {
      const sources = message.answer?.citations.map(c => `${c.title}${c.page ? ` · p. ${c.page}` : ''}\n${c.url}`).join('\n\n')
      await navigator.clipboard.writeText([message.text, sources, 'Respuesta de IA: puede contener errores. Verifica las fuentes.'].filter(Boolean).join('\n\n'))
      setCopied(message.id)
      setCopyError('')
    } catch { setCopyError('No se pudo copiar. Puedes seleccionar el texto de la respuesta.') }
  }

  function cancelQuery() {
    pending.current?.abort()
    pending.current = null
    setWaiting(false)
    add({ role: 'assistant', text: 'Consulta detenida. Puedes reformular la pregunta o explorar las fuentes del estudio.' })
  }

  const welcoming = messages.length === 1 && messages[0].id === initial.id

  return <div className="pyro-chat">
    <button className="pyro-chat-launch" type="button" ref={launch} onClick={() => openChat(launch.current ?? undefined)}
      aria-label="Abrir chat científico" aria-haspopup="dialog" aria-controls="pyro-chat-dialog" aria-expanded={opened}>
      <img src={pyrogravityMark} alt="" /><span>Pregunta a Pyrogravity</span>
    </button>
    <dialog ref={dialog} id="pyro-chat-dialog" className="pyro-chat-dialog" aria-labelledby="pyro-chat-title"
      onClose={() => {
        setOpened(false)
        const previous = origin.current
        if (previous?.getClientRects().length) previous.focus()
        else launch.current?.focus()
      }}>
      <header className="pyro-chat-header">
        <div className="pyro-chat-icon" aria-hidden="true"><img src={pyrogravityMark} alt="" /></div>
        <div><h2 ref={title} tabIndex={-1} id="pyro-chat-title">Pyrogravity</h2><p>Asistente científico</p></div>
        <button type="button" aria-label="Nueva conversación" title="Nueva conversación" disabled={waiting}
          onClick={() => { setMessages([initial]); setStudy(studyOnPage()); setDraft(''); setCopied(undefined); setCopyError(''); input.current?.focus() }}><RotateCcw aria-hidden="true" /></button>
        <button type="button" aria-label="Cerrar chat" onClick={() => dialog.current?.close()}><X aria-hidden="true" /></button>
      </header>
      <label className="pyro-chat-context"><span>Estudio</span>
        <select aria-label="Estudio del chat" value={study ?? ''} onChange={event => setStudy((event.target.value || undefined) as StudyId | undefined)} disabled={waiting}>
          <option value="">Todos los estudios</option>
          {studyIds.map(id => <option key={id} value={id}>{studies[id].name}</option>)}
        </select>
      </label>
      <div className="pyro-chat-log" ref={log} role="log" aria-label="Conversación" aria-relevant="additions">
        {welcoming && <div className="pyro-chat-welcome">
          <img src={pyrogravityMark} alt="" width="54" height="54" />
          <h3>Una pregunta abre<br />otra perspectiva.</h3>
          <p>Explora el fuego en microgravedad, sigue la pista de un ensayo y descubre qué respalda cada resultado.</p>
          <div className="pyro-chat-paths">
            <button type="button" onClick={() => void send('Ayúdame a explorar los datos')}><Database aria-hidden="true" /><span>Explorar los datos<small>Encuentra un estudio y sus mediciones</small></span><ArrowUpRight aria-hidden="true" /></button>
            <button type="button" onClick={() => void send('¿Cómo verifico una respuesta?')}><BookOpen aria-hidden="true" /><span>Seguir la evidencia<small>Aprende a leer las fuentes y los límites</small></span><ArrowUpRight aria-hidden="true" /></button>
          </div>
        </div>}
        {!welcoming && messages.map(message => <article key={message.id} className={`pyro-chat-message pyro-chat-message--${message.role}`}>
          <span className="pyro-chat-speaker">{message.role === 'user' ? <UserRound aria-hidden="true" /> : <img src={pyrogravityMark} alt="" />}{message.role === 'user' ? 'Tú' : 'Pyrogravity'}</span>
          <p>{message.text}</p>
          {message.links?.length ? <div className="pyro-chat-links">{message.links.map(item => {
            const href = safeLink(item.href)
            return href && <a key={href} href={href}>{item.title} <ArrowUpRight aria-hidden="true" /></a>
          })}</div> : null}
          {!!message.answer?.citations.length && <details className="pyro-chat-citations">
            <summary><BookOpen aria-hidden="true" /> {message.answer.citations.length === 1 ? '1 cita verificable' : `${message.answer.citations.length} citas verificables`}</summary>
            {message.answer.citations.map(citation => {
              const url = safeLink(citation.url)
              return <section key={citation.id}><strong>{citation.title}{citation.page ? ` · p. ${citation.page}` : ''}</strong>
                <blockquote>{citation.snippet}</blockquote>
                {url && <a href={url} target="_blank" rel="noreferrer">Abrir fuente original <ArrowUpRight aria-hidden="true" /></a>}
              </section>
            })}
          </details>}
          {!!message.answer?.limitations.length && <details className="pyro-chat-limitations"><summary>Alcance y limitaciones</summary><ul>{message.answer.limitations.map((limit, i) => <li key={i}>{limit}</li>)}</ul></details>}
          {message.role === 'assistant' && message.id !== initial.id && <div className="pyro-chat-message-actions"><button type="button" onClick={() => void copyAnswer(message)} aria-label={copied === message.id ? 'Respuesta copiada' : 'Copiar respuesta'}>{copied === message.id ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}{copied === message.id ? 'Copiado' : 'Copiar'}</button></div>}
        </article>)}
        {waiting && <p className="pyro-chat-wait" role="status"><span /> Buscando evidencia…</p>}
      </div>
      <div className="pyro-chat-bottom">
        <div className="pyro-chat-suggestions" aria-label="Preguntas sugeridas">
          {(study ? studySuggestions : suggestions).map(item =>
            <button key={item} type="button" disabled={waiting} onClick={() => void send(item)}>{item}</button>)}
        </div>
        <p className="pyro-chat-action-status" role="status">{copyError}</p>
        <form className="pyro-chat-form" onSubmit={submit}>
          <textarea ref={input} rows={1} maxLength={430} value={draft} onChange={event => setDraft(event.target.value)}
            aria-label="Escribe tu pregunta" aria-describedby="pyro-chat-disclaimer" placeholder="Escribe tu pregunta…" onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                void send(draft)
              }
            }} />
          {waiting ? <button type="button" aria-label="Detener consulta" onClick={cancelQuery}><Square aria-hidden="true" /></button> : <button type="submit" aria-label="Enviar mensaje" disabled={!draft.trim()}><Send aria-hidden="true" /></button>}
        </form>
        <p id="pyro-chat-disclaimer" className="pyro-chat-disclaimer"><MessageCircle aria-hidden="true" /> Estás hablando con una IA. Puede cometer errores. Verifica los datos y las fuentes antes de usar sus respuestas.</p>
      </div>
    </dialog>
  </div>
}
