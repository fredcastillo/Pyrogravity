import { enableOrbitalField, reveal } from './motion'

const canvas = document.querySelector<HTMLCanvasElement>('.orbital-canvas')
if (canvas) enableOrbitalField(canvas)

const sections = document.querySelectorAll('[data-reveal]')
const observer = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue
    observer.unobserve(entry.target)
    reveal([entry.target])
  }
}, { threshold: 0.15 })
sections.forEach((section) => observer.observe(section))
