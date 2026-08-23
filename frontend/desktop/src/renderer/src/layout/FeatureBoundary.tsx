import { Component, type ErrorInfo, type ReactNode } from 'react'

interface FeatureBoundaryProps {
  name: string
  children: ReactNode
}

interface FeatureBoundaryState {
  failed: boolean
}

export class FeatureBoundary extends Component<
  FeatureBoundaryProps,
  FeatureBoundaryState
> {
  state: FeatureBoundaryState = { failed: false }

  static getDerivedStateFromError(): FeatureBoundaryState {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`${this.props.name} feature failed`, error, info)
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="feature-failure" role="alert">
          <strong>{this.props.name} unavailable</strong>
          <span>This view encountered an error. Reload the application to recover.</span>
        </div>
      )
    }
    return this.props.children
  }
}
