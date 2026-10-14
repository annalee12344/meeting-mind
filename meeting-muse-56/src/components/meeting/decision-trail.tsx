import React from 'react';
import { Check, History, MessageSquareQuote } from 'lucide-react';
import type { HistoryEntry, Evidence } from '@/lib/types.generated';

interface DecisionTrailProps {
  history: HistoryEntry[];
  topic?: string;
  onViewEvidence?: (evidence: Evidence, title: string) => void;
}

export function DecisionTrail({ history, topic, onViewEvidence }: DecisionTrailProps) {
  if (!history || history.length === 0) {
    return (
      <div className="p-3.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50 text-xs text-zinc-500 dark:text-zinc-400 flex items-center gap-2">
        <History size={13} className="text-zinc-400 shrink-0" />
        <span>Chưa có lịch sử thay đổi thảo luận nào được ghi nhận cho quyết định này.</span>
      </div>
    );
  }

  return (
    <div className="space-y-2.5 mt-3 pt-3 border-t border-zinc-100 dark:border-zinc-800" aria-label="Tiến trình thảo luận quyết định">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-800 dark:text-zinc-200">
          <History size={13} className="text-indigo-600 dark:text-indigo-400" />
          <span>Tiến trình quyết định (Decision Trail)</span>
        </div>
        <span className="text-[11px] text-zinc-400 font-medium">
          {history.length} mốc thảo luận
        </span>
      </div>

      <div className="relative pl-5 space-y-3 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-px before:bg-zinc-200 dark:before:bg-zinc-800">
        {history.map((entry, index) => {
          const isLatest = index === history.length - 1;
          const statusLower = (entry.status || '').toLowerCase();
          const isSuperseded =
            statusLower.includes('supersede') ||
            statusLower.includes('thay thế') ||
            statusLower.includes('hủy');
          const isConfirmed =
            statusLower.includes('confirm') ||
            statusLower.includes('chốt') ||
            isLatest;
          const isProposed =
            statusLower.includes('propose') ||
            statusLower.includes('đề xuất') ||
            index === 0;

          const stageLabel = isSuperseded
            ? 'Đã thay thế'
            : isConfirmed
            ? 'Đã chốt'
            : isProposed
            ? 'Đề xuất'
            : 'Điều chỉnh';

          const primaryEvidence = entry.evidence?.[0];

          return (
            <div key={index} className="relative group">
              {/* Dot marker */}
              <div
                className={`absolute -left-5 top-1 w-4 h-4 rounded-full flex items-center justify-center ring-4 ring-white dark:ring-zinc-950 ${
                  isConfirmed
                    ? 'bg-indigo-600 dark:bg-indigo-500 text-white'
                    : isSuperseded
                    ? 'bg-zinc-200 dark:bg-zinc-700 text-zinc-500'
                    : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 border border-zinc-300 dark:border-zinc-700'
                }`}
              >
                {isConfirmed ? (
                  <Check size={9} className="stroke-[3]" />
                ) : isSuperseded ? (
                  <span className="text-[9px] font-bold">×</span>
                ) : (
                  <span className="w-1 h-1 rounded-full bg-zinc-500" />
                )}
              </div>

              {/* Card content */}
              <div
                className={`p-2.5 rounded-lg border text-xs transition-colors ${
                  isConfirmed
                    ? 'bg-indigo-50/30 dark:bg-indigo-950/20 border-indigo-200 dark:border-indigo-900/50'
                    : isSuperseded
                    ? 'bg-zinc-50/60 dark:bg-zinc-900/40 border-zinc-200/80 dark:border-zinc-800'
                    : 'bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800'
                }`}
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span
                    className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                      isConfirmed
                        ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/60 dark:text-indigo-300'
                        : isSuperseded
                        ? 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400 line-through'
                        : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300'
                    }`}
                  >
                    {stageLabel}
                  </span>

                  {entry.speaker && (
                    <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
                      {entry.speaker}
                    </span>
                  )}
                </div>

                <p
                  className={`text-xs sm:text-[13px] leading-relaxed ${
                    isSuperseded
                      ? 'line-through text-zinc-400 dark:text-zinc-500'
                      : 'text-zinc-800 dark:text-zinc-200 font-medium'
                  }`}
                >
                  {entry.value}
                </p>

                {primaryEvidence && onViewEvidence && (
                  <div className="mt-2 pt-1.5 border-t border-zinc-100 dark:border-zinc-800/80 flex items-center justify-between text-[11px]">
                    <span className="text-zinc-500 dark:text-zinc-400 italic truncate max-w-[240px]">
                      "{primaryEvidence.quote}"
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        onViewEvidence(
                          primaryEvidence,
                          `Quyết định: ${topic || entry.value}`
                        )
                      }
                      className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 font-medium flex items-center gap-1 cursor-pointer shrink-0 ml-2"
                    >
                      <MessageSquareQuote size={11} />
                      <span>Xem bằng chứng</span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}