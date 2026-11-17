/**
 * Keeps one broken chart from blanking the whole app: React unmounts everything when a render
 * throws, so each chart is wrapped and replaced by a short note if it fails.
 */
import { Component, type ReactNode } from "react";

interface Props {
  name: string;
  children: ReactNode;
}

interface State {
  failed: boolean;
}

export default class ChartBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: unknown): void {
    console.error(`Chart "${this.props.name}" could not be drawn`, error);
  }

  render() {
    if (this.state.failed) {
      return (
        <p className="chart-error" role="note">
          The {this.props.name} could not be shown. The answer and its sources are still above.
        </p>
      );
    }
    return this.props.children;
  }
}
