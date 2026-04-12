import { useMemo } from 'react'

import { useElementSize } from '../../hooks/useElementSize'
import { buildSeriesSvgChartModel, type SeriesSvgChartDatum } from './seriesSvgChartModel'

interface SeriesSvgChartProps {
  series: SeriesSvgChartDatum[]
  xLabel: string
  yLabel: string
  secondaryYLabel?: string
  logX?: boolean
  logY?: boolean
  emptyMessage: string
}

const AXIS_TICK_LENGTH = 5

export function SeriesSvgChart({
  series,
  xLabel,
  yLabel,
  secondaryYLabel,
  logX = false,
  logY = false,
  emptyMessage,
}: SeriesSvgChartProps) {
  const { ref: chartFrameRef, width: chartWidth, height: chartHeight } = useElementSize<HTMLDivElement>()
  const chartModel = useMemo(() => buildSeriesSvgChartModel({
    series,
    xLabel,
    yLabel,
    secondaryYLabel,
    logX,
    logY,
    width: chartWidth,
    height: chartHeight,
  }), [chartHeight, chartWidth, logX, logY, secondaryYLabel, series, xLabel, yLabel])

  if (!chartModel) {
    return <div className="svg-chart-empty muted-text">{emptyMessage}</div>
  }

  const {
    viewport,
    xTicks,
    leftTicks,
    rightTicks,
    renderedSeries,
    hasRightAxis,
    leftAxisLabel,
    rightAxisLabel,
  } = chartModel
  const { plotLeft, plotRight, plotTop, plotBottom, svgHeight, svgWidth } = viewport
  const yAxisCenter = (plotTop + plotBottom) / 2
  const xAxisCenter = (plotLeft + plotRight) / 2

  return (
    <div className="svg-chart-shell">
      <div ref={chartFrameRef} className="svg-chart-frame">
        <svg viewBox={`0 0 ${svgWidth} ${svgHeight}`} className="svg-chart" aria-label="Simulation series chart">
          <rect x={plotLeft} y={plotTop} width={plotRight - plotLeft} height={plotBottom - plotTop} className="svg-chart__plot-bg" />
          {leftTicks.map((tick) => (
            <line key={`grid-y-${tick.value}`} x1={plotLeft} x2={plotRight} y1={tick.position} y2={tick.position} className="svg-chart__grid" />
          ))}
          {xTicks.map((tick) => (
            <line key={`grid-x-${tick.value}`} x1={tick.position} x2={tick.position} y1={plotTop} y2={plotBottom} className="svg-chart__grid" />
          ))}
          <line x1={plotLeft} x2={plotRight} y1={plotBottom} y2={plotBottom} className="svg-chart__axis" />
          <line x1={plotLeft} x2={plotLeft} y1={plotTop} y2={plotBottom} className="svg-chart__axis" />
          {hasRightAxis ? <line x1={plotRight} x2={plotRight} y1={plotTop} y2={plotBottom} className="svg-chart__axis" /> : null}
          {renderedSeries.map((item) => (
            <polyline
              key={item.name}
              fill="none"
              stroke={item.color}
              strokeWidth={item.lineStyle === 'dash' ? '1.7' : '2'}
              strokeDasharray={item.strokeDasharray}
              strokeLinecap="round"
              strokeLinejoin="round"
              points={item.polylinePoints}
              className="svg-chart__series"
            />
          ))}
          {leftTicks.map((tick) => (
            <g key={`left-tick-${tick.value}`}>
              <line x1={plotLeft} x2={plotLeft - AXIS_TICK_LENGTH} y1={tick.position} y2={tick.position} className="svg-chart__tick" />
              <text x={plotLeft - 10} y={tick.position + 4} textAnchor="end" className="svg-chart__tick-label">{tick.label}</text>
            </g>
          ))}
          {rightTicks.map((tick) => (
            <g key={`right-tick-${tick.value}`}>
              <line x1={plotRight} x2={plotRight + AXIS_TICK_LENGTH} y1={tick.position} y2={tick.position} className="svg-chart__tick" />
              <text x={plotRight + 10} y={tick.position + 4} textAnchor="start" className="svg-chart__tick-label">{tick.label}</text>
            </g>
          ))}
          {xTicks.map((tick) => (
            <g key={`bottom-tick-${tick.value}`}>
              <line x1={tick.position} x2={tick.position} y1={plotBottom} y2={plotBottom + AXIS_TICK_LENGTH} className="svg-chart__tick" />
              <text x={tick.position} y={plotBottom + 18} textAnchor="middle" className="svg-chart__tick-label">{tick.label}</text>
            </g>
          ))}
          <text x={xAxisCenter} y={svgHeight - 14} textAnchor="middle" className="svg-chart__axis-title">{chartModel.xLabel}</text>
          <text x={18} y={yAxisCenter} textAnchor="middle" transform={`rotate(-90 18 ${yAxisCenter})`} className="svg-chart__axis-title">{leftAxisLabel}</text>
          {hasRightAxis ? (
            <text x={svgWidth - 18} y={yAxisCenter} textAnchor="middle" transform={`rotate(90 ${svgWidth - 18} ${yAxisCenter})`} className="svg-chart__axis-title">{rightAxisLabel}</text>
          ) : null}
        </svg>
      </div>
    </div>
  )
}
