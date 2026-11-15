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

export function LineChart({ series, color, label, secondary }: LineChartProps) {
  const width = 640
  const height = 210
  return (
    <div className="line-chart">
      <div className="line-chart__legend">
        <span><i style={{ background: color }} />{label}</span>
        {secondary && <span><i style={{ background: secondary.color }} />{secondary.label}</span>}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Evolución temporal de ${label}${secondary ? ` y ${secondary.label}` : ''}`}>
        <defs>
          <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity="0.28" />
            <stop offset="1" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 1, 2, 3, 4].map((row) => <line key={row} x1="18" y1={18 + row * 43.5} x2="622" y2={18 + row * 43.5} className="chart-grid" />)}
        <path d={`${pathFor(series, width, height)} L 622 ${height - 18} L 18 ${height - 18} Z`} fill="url(#chartFill)" />
        <path d={pathFor(series, width, height)} fill="none" stroke={color} strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
        {secondary && <path d={pathFor(secondary.series, width, height)} fill="none" stroke={secondary.color} strokeWidth="2.4" strokeDasharray="6 6" strokeLinecap="round" />}
      </svg>
      <div className="line-chart__axis"><span>Inicio del ensayo</span><span>Tiempo (s)</span></div>
    </div>
  )
}
