import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Only class component because React requires it for render-error catches.
 * Show failure and retry through `attempt`-keyed remount; boundaries wrap each
 * section and app root to avoid blank pages.
 */

export interface ErrorBoundaryProps {
  /** Fallback region name, such as "the run view". */
  label: string;
  /** Change retries fallback; healthy subtree retains DOM. */
  resetKey?: string | null;
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
  attempt: number;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null, attempt: 0 };

  static getDerivedStateFromError(error: unknown): Partial<ErrorBoundaryState> {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Log stack for reports; display message for users.
    console.error(`agentbase: ${this.props.label} failed to render`, error, info.componentStack);
  }

  override componentDidUpdate(previous: ErrorBoundaryProps): void {
    if (this.state.error !== null && previous.resetKey !== this.props.resetKey) {
      this.reset();
    }
  }

  private readonly reset = () => {
    this.setState((current) => ({ error: null, attempt: current.attempt + 1 }));
  };

  override render(): ReactNode {
    if (this.state.error !== null) {
      return (
        <div className="boundary" role="alert" data-testid="error-boundary">
          <p className="boundary__title">Something in {this.props.label} could not be drawn.</p>
          <pre className="boundary__message">{this.state.error.message}</pre>
          <p className="boundary__hint">
            The event log on the sidecar is untouched: this is the window failing to render it.
          </p>
          <button type="button" className="button" onClick={this.reset}>
            Try again
          </button>
        </div>
      );
    }

    return <div key={this.state.attempt} className="boundary__inner">{this.props.children}</div>;
  }
}
