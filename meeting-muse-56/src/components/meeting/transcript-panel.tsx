import React, { useEffect, useRef, useState, useMemo } from 'react';
import {
  Copy,
  Check,
  ShieldCheck,
  AlertTriangle,
  FileText,
  Search,
  ChevronLeft,
  ChevronRight,
  HelpCircle,
} from 'lucide-react';
import type { Evidence } from '@/lib/types.generated';
import { parseUtterances } from '@/lib/meeting';

export interface ActiveEvidence {
  evidence: Evidence;
  evidenceList?: Evidence[];
  activeEvidenceIndex?: number;
  onSelectEvidenceIndex?: (idx: number) => void;
  itemTitle: string;
  itemTypeLabel: string;
  itemType: 'decision' | 'task' | 'unresolved' | 'issue';
}

interface TranscriptPanelProps {
  isOpen: boolean;
  onClose: () => void;
  transcript: string;
  activeEvidence?: ActiveEvidence | null;
}

function renderHighlightedText(text: string, quote?: string, isTarget: boolean = false) {
  if (!isTarget || !quote || !quote.trim()) {
    return <span>{text}</span>;
  }

  const cleanQuote = quote.trim();
  const lowerText = text.toLowerCase();
  const lowerQuote = cleanQuote.toLowerCase();
  const matchIndex = lowerText.indexOf(lowerQuote);

  if (matchIndex !== -1) {
    const before = text.substring(0, matchIndex);
    const matched = text.substring(matchIndex, matchIndex + cleanQuote.length);
    const after = text.substring(matchIndex + cleanQuote.length);

    return (
      <span>
        {before}
        <mark className="bg-amber-200/90 dark:bg-amber-400/40 text-zinc-950 dark:text-zinc-50 font-semibold px-1 py-0.5 rounded shadow-2xs">
          {matched}
        </mark>
        {after}
      </span>
    );
  }

  // Fallback if quote has slight punctuation difference: highlight matching keywords
  const quoteWords = cleanQuote
    .split(/\s+/)
    .map((w) => w.replace(/[.,/#!$%^&*;:{}=\-_`~()]/g, '').toLowerCase())
    .filter((w) => w.length > 2);

  if (quoteWords.length >= 3) {
    const words = text.split(/(\s+)/);
    return (
      <span>
        {words.map((word, wIdx) => {
          const cleanW = word.replace(/[.,/#!$%^&*;:{}=\-_`~()]/g, '').toLowerCase();
          const isHit = quoteWords.includes(cleanW);
          return isHit ? (
            <mark
              key={wIdx}
              className="bg-amber-200/90 dark:bg-amber-400/40 text-zinc-950 dark:text-zinc-50 font-semibold px-0.5 py-0.2 rounded"
            >
              {word}
            </mark>
          ) : (
            <span key={wIdx}>{word}</span>
          );
        })}
      </span>
    );
  }

  return (
    <mark className="bg-amber-200/90 dark:bg-amber-400/40 text-zinc-950 dark:text-zinc-50 font-semibold px-1 py-0.5 rounded">
      {text}
    </mark>
  );
}

export function TranscriptPanel({
  isOpen,
  onClose,
  transcript,
  activeEvidence,
}: TranscriptPanelProps) {
  const [copied, setCopied] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [internalEvidenceIndex, setInternalEvidenceIndex] = useState(0);

  const panelRef = useRef<HTMLDivElement>(null);
  const targetLineRef = useRef<HTMLDivElement>(null);
  const lastActiveElementRef = useRef<HTMLElement | null>(null);

  const utterances = useMemo(() => parseUtterances(transcript), [transcript]);

  // Sync internal evidence index when activeEvidence changes
  useEffect(() => {
    setInternalEvidenceIndex(activeEvidence?.activeEvidenceIndex ?? 0);
  }, [activeEvidence]);

  const evidenceList = activeEvidence?.evidenceList ?? (activeEvidence?.evidence ? [activeEvidence.evidence] : []);
  const currentEvidence = evidenceList[internalEvidenceIndex] || activeEvidence?.evidence;

  // Determine target line index (0-indexed). Strictly return -1 if not located.
  const targetIndex = useMemo(() => {
    if (!currentEvidence) return -1;
    const ev = currentEvidence;

    // 1. Direct utterance_id (e.g., "U006" -> 5)
    if (ev.utterance_id) {
      const match = ev.utterance_id.match(/\d+/);
      if (match) {
        const num = parseInt(match[0], 10);
        if (num >= 1 && num <= utterances.length) {
          return num - 1;
        }
      }
    }

    // 2. Line range
    if (ev.line_range && ev.line_range[0] >= 1 && ev.line_range[0] <= utterances.length) {
      return ev.line_range[0] - 1;
    }

    // 3. Exact or normalized quote match in text
    if (ev.quote && ev.quote.trim().length > 0) {
      const q = ev.quote.toLowerCase().trim();
      // Match substring
      const idx = utterances.findIndex(
        (u) => u.text.toLowerCase().includes(q) || (q.length > 15 && q.includes(u.text.toLowerCase()))
      );
      if (idx !== -1) return idx;

      // Match significant word overlap (>= 60% words)
      const qWords = q.split(/\s+/).filter((w) => w.length > 2);
      if (qWords.length >= 3) {
        let bestIdx = -1;
        let maxOverlap = 0;
        utterances.forEach((u, i) => {
          const uText = u.text.toLowerCase();
          const matchCount = qWords.filter((w) => uText.includes(w)).length;
          const ratio = matchCount / qWords.length;
          if (ratio > 0.6 && ratio > maxOverlap) {
            maxOverlap = ratio;
            bestIdx = i;
          }
        });
        if (bestIdx !== -1) return bestIdx;
      }
    }

    // Never fake location with fallback to 0
    return -1;
  }, [currentEvidence, utterances]);

  const isLocated = targetIndex !== -1;

  // Context range: exactly 2 lines before and 2 lines after if located
  const contextRange = useMemo(() => {
    if (!isLocated) return { start: -1, end: -1 };
    return {
      start: Math.max(0, targetIndex - 2),
      end: Math.min(utterances.length - 1, targetIndex + 2),
    };
  }, [targetIndex, isLocated, utterances.length]);

  // Focus restoration & Focus trap
  useEffect(() => {
    if (isOpen) {
      lastActiveElementRef.current = document.activeElement as HTMLElement | null;
      const timer = setTimeout(() => {
        panelRef.current?.focus();
      }, 50);
      return () => clearTimeout(timer);
    } else {
      if (lastActiveElementRef.current && typeof lastActiveElementRef.current.focus === 'function') {
        lastActiveElementRef.current.focus();
      }
    }
  }, [isOpen]);

  // Smooth scroll to cited line when opened or evidence changes
  useEffect(() => {
    if (!isOpen || !isLocated) return;
    const timer = setTimeout(() => {
      targetLineRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 120);
    return () => clearTimeout(timer);
  }, [isOpen, isLocated, targetIndex, internalEvidenceIndex]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === 'Tab' && panelRef.current) {
      const focusable = panelRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) {
          last.focus();
          e.preventDefault();
        }
      } else {
        if (document.activeElement === last) {
          first.focus();
          e.preventDefault();
        }
      }
    }
  };

  const handleCopyQuote = () => {
    if (!currentEvidence?.quote) return;
    navigator.clipboard.writeText(currentEvidence.quote);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/35 backdrop-blur-[2px] flex sm:justify-end items-end sm:items-stretch transition-opacity duration-200"
      onClick={onClose}
    >
      {/* Panel container: Mobile bottom sheet (85vh) / Desktop right sheet (480px) */}
      <div
        ref={panelRef}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        className="w-full sm:w-[480px] h-[85vh] sm:h-full bg-white dark:bg-zinc-900 shadow-2xl flex flex-col border-t sm:border-t-0 sm:border-l border-zinc-200 dark:border-zinc-800 rounded-t-2xl sm:rounded-none outline-none overflow-hidden transition-transform duration-200 ease-out"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Mobile drag handle */}
        <div className="sm:hidden pt-2 pb-1 flex justify-center">
          <div className="w-10 h-1 bg-zinc-300 dark:bg-zinc-700 rounded-full" />
        </div>

        {/* Visually hidden screen reader close button */}
        <button
          type="button"
          onClick={onClose}
          className="sr-only"
          aria-label="Đóng bảng biên bản"
        >
          Đóng
        </button>

        {/* Panel Header */}
        <div className="px-4 py-3 sm:py-3.5 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/70 dark:bg-zinc-900/90 flex items-center justify-between gap-3 shrink-0">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-zinc-900 dark:text-zinc-100">
                <FileText size={12} className="text-zinc-500" />
                <span>Đối soát biên bản</span>
              </span>

              {activeEvidence?.itemTypeLabel && (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 border border-zinc-200/80 dark:border-zinc-700">
                  {activeEvidence.itemTypeLabel}
                </span>
              )}

              {/* Status Verification: accurately reflect location state */}
              {currentEvidence && (
                isLocated ? (
                  currentEvidence.verified ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
                      <ShieldCheck size={11} />
                      <span>Đã đối soát (dòng {targetIndex + 1})</span>
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800">
                      <AlertTriangle size={11} />
                      <span>Cần kiểm tra (dòng {targetIndex + 1})</span>
                    </span>
                  )
                ) : (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 border border-zinc-200 dark:border-zinc-700">
                    <HelpCircle size={11} />
                    <span>Chưa định vị trong biên bản</span>
                  </span>
                )
              )}
            </div>

            <h3 className="text-xs sm:text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
              {activeEvidence?.itemTitle || 'Toàn văn biên bản'}
            </h3>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {/* Multi-evidence pagination */}
            {evidenceList.length > 1 && (
              <div className="flex items-center gap-1 bg-zinc-100 dark:bg-zinc-800 px-2 py-1 rounded-lg text-xs font-medium text-zinc-600 dark:text-zinc-300">
                <button
                  type="button"
                  disabled={internalEvidenceIndex === 0}
                  onClick={() => {
                    const next = Math.max(0, internalEvidenceIndex - 1);
                    setInternalEvidenceIndex(next);
                    activeEvidence?.onSelectEvidenceIndex?.(next);
                  }}
                  className="p-0.5 rounded hover:bg-zinc-200 dark:hover:bg-zinc-700 disabled:opacity-30 cursor-pointer"
                  title="Bằng chứng trước"
                >
                  <ChevronLeft size={13} />
                </button>
                <span className="text-[11px] font-mono px-1">
                  {internalEvidenceIndex + 1}/{evidenceList.length}
                </span>
                <button
                  type="button"
                  disabled={internalEvidenceIndex === evidenceList.length - 1}
                  onClick={() => {
                    const next = Math.min(evidenceList.length - 1, internalEvidenceIndex + 1);
                    setInternalEvidenceIndex(next);
                    activeEvidence?.onSelectEvidenceIndex?.(next);
                  }}
                  className="p-0.5 rounded hover:bg-zinc-200 dark:hover:bg-zinc-700 disabled:opacity-30 cursor-pointer"
                  title="Bằng chứng sau"
                >
                  <ChevronRight size={13} />
                </button>
              </div>
            )}

            {currentEvidence?.quote && (
              <button
                type="button"
                onClick={handleCopyQuote}
                className="p-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 transition-colors cursor-pointer"
                title="Sao chép trích dẫn"
              >
                {copied ? <Check size={13} className="text-emerald-600" /> : <Copy size={13} />}
              </button>
            )}
          </div>
        </div>

        {/* If quote could NOT be located in transcript, show clean notice instead of fake result */}
        {currentEvidence && !isLocated && (
          <div className="px-4 py-2.5 bg-amber-50/60 dark:bg-amber-950/30 border-b border-amber-200/60 dark:border-amber-900/40 text-xs text-amber-800 dark:text-amber-300 flex items-start gap-2 shrink-0">
            <AlertTriangle size={13} className="shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
            <div className="min-w-0 flex-1 leading-relaxed">
              Trích dẫn: <span className="italic font-medium">"{currentEvidence.quote}"</span> không tìm thấy dòng phát biểu khớp chính xác trong biên bản gốc.
            </div>
          </div>
        )}

        {/* Search Input Filter */}
        <div className="px-4 py-2 border-b border-zinc-100 dark:border-zinc-800/80 bg-white dark:bg-zinc-900 shrink-0">
          <div className="relative flex items-center">
            <Search size={13} className="absolute left-2.5 text-zinc-400" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Tìm kiếm trong biên bản..."
              className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-950 text-zinc-800 dark:text-zinc-200 placeholder:text-zinc-400 outline-none focus:border-zinc-400 dark:focus:border-zinc-600 transition-colors"
            />
          </div>
        </div>

        {/* Utterance Lines List: Exactly one single source of truth for the quote in context */}
        <div className="flex-1 overflow-y-auto p-3 sm:p-4 space-y-1.5 bg-[#FAFAF9] dark:bg-zinc-950/50 text-xs font-sans">
          {utterances.map((u, idx) => {
            const isTarget = isLocated && idx === targetIndex;
            const isInContext =
              isLocated && idx >= contextRange.start && idx <= contextRange.end;
            const isDimmed = isLocated && !isInContext;

            // Search filter
            if (searchQuery.trim()) {
              const q = searchQuery.toLowerCase();
              const match =
                u.text.toLowerCase().includes(q) || u.speaker.toLowerCase().includes(q);
              if (!match) return null;
            }

            return (
              <div
                key={idx}
                ref={isTarget ? targetLineRef : undefined}
                className={`p-3 rounded-xl transition-all duration-150 flex items-start gap-2.5 ${
                  isTarget
                    ? 'bg-amber-50/90 dark:bg-amber-950/40 border-2 border-amber-500 dark:border-amber-400 shadow-md ring-4 ring-amber-400/30 dark:ring-amber-500/20 border-l-[6px] border-l-amber-500'
                    : isInContext
                    ? 'bg-white/95 dark:bg-zinc-900/95 border border-zinc-200 dark:border-zinc-800 shadow-2xs'
                    : isDimmed
                    ? 'opacity-35 hover:opacity-90 border border-transparent hover:border-zinc-200 dark:hover:border-zinc-800 transition-opacity'
                    : 'bg-white dark:bg-zinc-900 border border-zinc-200/60 dark:border-zinc-800/60'
                }`}
              >
                {/* Line index */}
                <div className="flex flex-col items-center shrink-0 w-8 select-none pt-0.5">
                  {isTarget ? (
                    <span className="px-1.5 py-0.5 rounded bg-amber-500 text-white font-mono font-bold text-[10px] shadow-xs">
                      {idx + 1}
                    </span>
                  ) : (
                    <span
                      className={`text-[11px] font-mono ${
                        isInContext
                          ? 'font-semibold text-zinc-600 dark:text-zinc-400'
                          : 'text-zinc-400 dark:text-zinc-500'
                      }`}
                    >
                      {idx + 1}
                    </span>
                  )}
                </div>

                {/* Speaker & Content */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span
                      className={`font-semibold text-xs ${
                        isTarget
                          ? 'text-amber-900 dark:text-amber-200 font-bold'
                          : 'text-zinc-800 dark:text-zinc-200'
                      }`}
                    >
                      {u.speaker || 'Phát biểu'}
                    </span>
                    {u.timestamp && (
                      <span className="text-[10px] font-mono text-zinc-400 dark:text-zinc-500">
                        [{u.timestamp}]
                      </span>
                    )}
                    {isTarget && (
                      <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500 text-white shadow-xs">
                        ⭐ DẪN CHỨNG TRỌNG TÂM
                      </span>
                    )}
                    {isInContext && !isTarget && (
                      <span className="text-[9px] font-medium px-1.5 py-0.2 rounded bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                        Ngữ cảnh
                      </span>
                    )}
                  </div>

                  <p
                    className={`text-xs sm:text-[13px] leading-relaxed ${
                      isTarget
                        ? 'font-medium text-zinc-900 dark:text-zinc-100'
                        : 'text-zinc-700 dark:text-zinc-300'
                    }`}
                  >
                    {renderHighlightedText(u.text, currentEvidence?.quote, isTarget)}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
