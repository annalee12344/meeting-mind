import React, { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertCircle, RotateCcw } from 'lucide-react';

interface SectionErrorBoundaryProps {
  children: ReactNode;
  fallbackTitle?: string;
  fallbackMessage?: string;
  onReset?: () => void;
}

interface SectionErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

export class SectionErrorBoundary extends Component<
  SectionErrorBoundaryProps,
  SectionErrorBoundaryState
> {
  constructor(props: SectionErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): SectionErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('[SectionErrorBoundary] Error caught in section:', error, errorInfo);
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: undefined });
    this.props.onReset?.();
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          className="p-4 rounded-xl border border-rose-200 dark:border-rose-900/60 bg-rose-50/60 dark:bg-rose-950/20 text-rose-800 dark:text-rose-200 space-y-2.5 my-2"
        >
          <div className="flex items-center gap-2 font-medium text-xs sm:text-sm">
            <AlertCircle className="h-4 w-4 text-rose-500 shrink-0" />
            <span>{this.props.fallbackTitle || 'Không thể hiển thị mục này'}</span>
          </div>
          <p className="text-xs text-rose-600 dark:text-rose-300 leading-relaxed">
            {this.props.fallbackMessage ||
              'Đã xảy ra sự cố khi xử lý dữ liệu cho phần này. Bạn có thể bấm Thử lại để tải lại nội dung.'}
          </p>
          <div className="pt-1">
            <button
              type="button"
              onClick={this.handleReset}
              className="inline-flex items-center gap-1.5 px-3 py-1 bg-white dark:bg-zinc-800 border border-rose-300 dark:border-rose-800 rounded-lg text-xs font-medium text-rose-700 dark:text-rose-200 hover:bg-rose-100 dark:hover:bg-zinc-700 transition-colors cursor-pointer shadow-2xs"
            >
              <RotateCcw className="h-3 w-3" />
              <span>Thử lại</span>
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
