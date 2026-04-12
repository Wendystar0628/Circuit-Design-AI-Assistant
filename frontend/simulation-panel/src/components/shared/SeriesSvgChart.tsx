import { useMemo } from 'react'

import { useElementSize } from '../../hooks/useElementSize'
import { buildSeriesSvgChartModel, type SeriesSvgChartDatum } from './seriesSvgChartModel'

interface SeriesSvgChartProps {
  title?: string
  series: SeriesSvgChartDatum[]
  xLabel: string
  yLabel: string
  secondaryYLabel?: string
  logX?: boolean
  logY?: boolean
  emptyMessage: string
}

const AXIS_TICK_LENGTH = 5
const LEFT_TICK_LABEL_OFFSET = 9
const RIGHT_TICK_LABEL_OFFSET = 9
const X_TICK_LABEL_OFFSET = 19
const X_AXIS_TITLE_OFFSET = 34
const SIDE_AXIS_TITLE_OFFSET = 32

export function SeriesSvgChart({
  title,
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

  const normalizedTitle = title?.trim() ?? ''

  if (!chartModel) {
    return (
      <div className="svg-chart-shell">
        {normalizedTitle ? (
          <div className="svg-chart-header">
            <div className="svg-chart-title">{normalizedTitle}</div>
          </div>
        ) : null}
        <div className="svg-chart-empty muted-text">{emptyMessage}</div>
      </div>
    )
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
  const xAxisTitleY = Math.min(svgHeight - 10, plotBottom + X_AXIS_TITLE_OFFSET)
  const leftAxisTitleX = SIDE_AXIS_TITLE_OFFSET
  const rightAxisTitleX = svgWidth - SIDE_AXIS_TITLE_OFFSET

  return (
    <div className="svg-chart-shell">
      {normalizedTitle ? (
        <div className="svg-chart-header">
          <div className="svg-chart-title">{normalizedTitle}</div>
        </div>
      ) : null}
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
              <text x={plotLeft - LEFT_TICK_LABEL_OFFSET} y={tick.position + 4} textAnchor="end" className="svg-chart__tick-label">{tick.label}</text>
            </g>
          ))}
          {rightTicks.map((tick) => (
            <g key={`right-tick-${tick.value}`}>
              <line x1={plotRight} x2={plotRight + AXIS_TICK_LENGTH} y1={tick.position} y2={tick.position} className="svg-chart__tick" />
              <text x={plotRight + RIGHT_TICK_LABEL_OFFSET} y={tick.position + 4} textAnchor="start" className="svg-chart__tick-label">{tick.label}</text>
            </g>
          ))}
          {xTicks.map((tick) => (
            <g key={`bottom-tick-${tick.value}`}>
              <line x1={tick.position} x2={tick.position} y1={plotBottom} y2={plotBottom + AXIS_TICK_LENGTH} className="svg-chart__tick" />
              <text x={tick.position} y={plotBottom + X_TICK_LABEL_OFFSET} textAnchor="middle" className="svg-chart__tick-label">{tick.label}</text>
            </g>
          ))}
          <text x={xAxisCenter} y={xAxisTitleY} textAnchor="middle" className="svg-chart__axis-title">{chartModel.xLabel}</text>
          <text x={leftAxisTitleX} y={yAxisCenter} textAnchor="middle" transform={`rotate(-90 ${leftAxisTitleX} ${yAxisCenter})`} className="svg-chart__axis-title">{leftAxisLabel}</text>
          {hasRightAxis ? (
            <text x={rightAxisTitleX} y={yAxisCenter} textAnchor="middle" transform={`rotate(90 ${rightAxisTitleX} ${yAxisCenter})`} className="svg-chart__axis-title">{rightAxisLabel}</text>
          ) : null}
        </svg>
      </div>
    </div>
  )
}
