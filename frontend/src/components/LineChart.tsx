import { useId, type CSSProperties } from 'react'
import type { DataPoint } from '../types'

interface LineChartProps {
  series: DataPoint[]
  color: string
  label: string
  secondary?: { series: DataPoint[]; color: string; label: string }
}

function pathFor(series: DataPoint[], width: number, height: number) {
  const maxX = Math.max(...series.map((point) => point.time), 1)
  const maxY = Math.max(...series.map((point) => point.value), 1)
  return series.map((point, index) => {
    const x = 18 + (point.time / maxX) * (width - 36)
    const y = height - 18 - (point.value / maxY) * (height - 36)
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
  }).join(' ')
}

function pointsFor(series: DataPoint[], width: number, height: number) {
  const maxX = Math.max(...series.map((point) => point.time), 1)
  const maxY = Math.max(...series.map((point) => point.value), 1)
  return series.map((point) => ({
    x: 18 + (point.time / maxX) * (width - 36),
    y: height - 18 - (point.value / maxY) * (height - 36),
  }))
}

export function LineChart({ series, color, label, secondary }: LineChartProps) {
  const width = 640
  const height = 210
  const uid = useId().replace(/:/g, '')
  const gradientId = `chart-fill-${uid}`
  const glowId = `chart-glow-${uid}`
  const primaryPoints = pointsFor(series, width, height)
  const secondaryPoints = secondary ? pointsFor(secondary.series, width, height) : []
  return (
    <div className="line-chart">
      <div className="line-chart__legend">
        <span><i style={{ background: color }} />{label}</span>
        {secondary && <span><i style={{ background: secondary.color }} />{secondary.label}</span>}
      </div>
      <svg key={`${label}-${secondary?.label ?? 'single'}`} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Evolución temporal de ${label}${secondary ? ` y ${secondary.label}` : ''}`}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity="0.28" />
            <stop offset="1" stopColor={color} stopOpacity="0" />
          </linearGradient>
          <filter id={glowId} x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="3" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>
        {[0, 1, 2, 3, 4].map((row) => <line key={row} x1="18" y1={18 + row * 43.5} x2="622" y2={18 + row * 43.5} className="chart-grid" />)}
        <path className="chart-area" d={`${pathFor(series, width, height)} L 622 ${height - 18} L 18 ${height - 18} Z`} fill={`url(#${gradientId})`} />
        <path className="chart-line chart-line--primary" pathLength="1" d={pathFor(series, width, height)} fill="none" stroke={color} strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" filter={`url(#${glowId})`} />
        {primaryPoints.map((point, index) => <circle key={`${point.x}-${point.y}`} className="chart-point" cx={point.x} cy={point.y} r="3.4" fill={color} style={{ '--point-delay': `${0.55 + index * 0.12}s` } as CSSProperties} />)}
        {secondary && <path className="chart-line chart-line--secondary" pathLength="1" d={pathFor(secondary.series, width, height)} fill="none" stroke={secondary.color} strokeWidth="2.4" strokeDasharray="6 6" strokeLinecap="round" />}
        {secondary && secondaryPoints.map((point, index) => <circle key={`secondary-${point.x}-${point.y}`} className="chart-point chart-point--secondary" cx={point.x} cy={point.y} r="2.6" fill={secondary.color} style={{ '--point-delay': `${0.72 + index * 0.12}s` } as CSSProperties} />)}
        <rect className="chart-scanner" x="18" y="18" width="1.5" height={height - 36} fill={color} />
      </svg>
      <div className="line-chart__axis"><span>Inicio del ensayo</span><span>Tiempo (s)</span></div>
    </div>
  )
}
