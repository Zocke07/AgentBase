import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * The one class component in the tree, since React catches render errors no
 * other way. Shows what threw and offers to try again; `key`ing the subtree
 * on `attempt` makes that a real remount. One per section and one around the
 * app, so nothing is ever a blank page.
 */

export interface ErrorBoundaryProps {
  /** Names the region in the fallback: "the run view", "AgentSpace". */
  label: string;
  /** When this changes, a boundary showing its fallback tries again; a healthy subtree keeps its DOM. */
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
    // The stack goes to the console, where a bug report can find it; the
    // message goes on screen, where a person can.
    console.error(`agentspace: ${this.props.label} failed to render`, error, info.componentStack);
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
