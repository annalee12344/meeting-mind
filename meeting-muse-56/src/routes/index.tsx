import { createFileRoute } from '@tanstack/react-router';
import { useEffect, useRef, useState } from 'react';
import {
  LoaderCircle,
  Upload,
  X,
  FileText,
  ChevronDown,
  ChevronRight,
  Check,
  ArrowRight,
  AlertTriangle,
  RefreshCw,
  Sun,
  Moon,
  Sparkles,
} from 'lucide-react';
import { Workspace } from '@/components/meeting/workspace';
import sampleTranscript from '@/data/sprint-planning.txt?raw';
import {
  isMeetingResult,
  isExportPackage,
  isLegacyMeetingFormat,
  type MeetingResult,
} from '@/lib/meeting';
import type {
  JobStage,
  MeetingOutput,
  MeetingOverlay,
} from '@/lib/types.generated';
import {
  cancelAnalysisJob,
  fetchSample,
  fetchSampleResult,
  fetchSamples,
  getAnalysisJob,
  startAnalysisJob,
  upgradeLegacyResult,
} from '@/lib/api';
import { getDefaultPersistenceAdapter } from '@/lib/storage';

export const Route = createFileRoute('/')({
  head: () => ({
    meta: [
      { title: 'Meeting Mind — Trích xuất thông tin cuộc họp' },
      {
        name: 'description',
        content:
          'Trích xuất quyết định, việc cần làm, điểm chưa chốt và rào cản từ biên bản cuộc họp tiếng Việt.',
      },
    ],
  }),
  component: Index,
});

interface SampleItem {
  id: string;
  title: string;
  name: string;
  desc: string;
  filename: string;
}

const BENCHMARK_SAMPLES: SampleItem[] = [
  {
    id: 'test_01_happy_path',
    title: 'Họp sprint planning',
    name: 'Sprint 24 · Planning',
    desc: 'Phạm vi tính năng thanh toán, giao việc Dev/QA, rào cản staging.',
    filename: 'test_01_happy_path.txt',
  },
  {
    id: 'test_02_decision_change',
    title: 'Thay đổi ngày ra mắt',
    name: 'Product Launch Timing',
    desc: 'Dời ngày ra mắt từ 15/6 sang 15/7, chuyển sang cổng PayOS.',
    filename: 'test_02_decision_change.txt',
  },
  {
    id: 'test_03_chaotic',
    title: 'Thảo luận chen ngang',
    name: 'Chaotic Team Sync',
    desc: 'Bất đồng về lỗi staging, tranh luận WebSocket hay SSE.',
    filename: 'test_03_chaotic.txt',
  },
  {
    id: 'test_04_implicit',
    title: 'Đồng thuận ngầm',
    name: 'Implicit Consensus Discussion',
    desc: 'Đồng thuận không biểu quyết, không ghi rõ hạn chót phát biểu.',
    filename: 'test_04_implicit.txt',
  },
  {
    id: 'test_05_sarcasm_fail',
    title: 'Bất đồng quan điểm',
    name: 'Adversarial Discussion',
    desc: 'Châm biếm, đề xuất đùa cợt và xung đột quan điểm gay gắt.',
    filename: 'test_05_sarcasm_fail.txt',
  },
];

const ANALYSIS_STEPS: Array<{ key: string; label: string; stages: JobStage[] }> = [
  { key: 'prep', label: 'Chuẩn bị', stages: ['queued', 'preprocessing'] },
  { key: 'extract', label: 'Trích xuất', stages: ['extracting'] },
  { key: 'resolve', label: 'Đối chiếu', stages: ['resolving'] },
  { key: 'validate', label: 'Kiểm chứng', stages: ['validating', 'mapping', 'done'] },
];

const STAGE_ORDER: Record<string, number> = {
  queued: 0,
  preprocessing: 1,
  extracting: 2,
  resolving: 3,
  validating: 4,
  mapping: 5,
  done: 6,
  failed: -1,
  cancelled: -1,
};

function Index() {
  const [transcript, setTranscript] = useState('');
  const [name, setName] = useState('');
  const [meetingDate, setMeetingDate] = useState('');
  const [result, setResult] = useState<MeetingResult | MeetingOutput | null>(null);
  const [initialOverlay, setInitialOverlay] = useState<MeetingOverlay | null>(null);
  const [isSample, setIsSample] = useState(false);
  const [selectedSampleId, setSelectedSampleId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [loadingSampleId, setLoadingSampleId] = useState<string | null>(null);
  const [showExtraInfo, setShowExtraInfo] = useState(false);
  const [theme, setTheme] = useState<'light' | 'dark'>('light');

  // Helper to validate and read .txt file with size (<5MB) and UTF-8 verification
  const readTxtFile = async (file: File): Promise<string> => {
    if (!file.name.toLowerCase().endsWith('.txt')) {
      throw new Error('Vui lòng chọn tệp văn bản có định dạng .txt');
    }
    const MAX_SIZE = 5 * 1024 * 1024; // 5MB limit
    if (file.size > MAX_SIZE) {
      throw new Error('Kích thước tệp vượt quá giới hạn 5MB.');
    }
    const buffer = await file.arrayBuffer();
    try {
      const decoder = new TextDecoder('utf-8', { fatal: true });
      return decoder.decode(buffer);
    } catch {
      throw new Error('Tệp không đúng định dạng mã hóa UTF-8. Vui lòng lưu tệp với bảng mã UTF-8.');
    }
  };

  // Real asynchronous analysis job state
  const [analyzing, setAnalyzing] = useState(false);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [jobStage, setJobStage] = useState<JobStage>('queued');
  const [jobProgress, setJobProgress] = useState<number>(0);
  const [jobStageLabel, setJobStageLabel] = useState<string>('Đang chuẩn bị phân tích...');

  const [fileName, setFileName] = useState('');
  const [isDragging, setIsDragging] = useState(false);

  const editor = useRef<HTMLTextAreaElement>(null);
  const upload = useRef<HTMLInputElement>(null);
  const outputUpload = useRef<HTMLInputElement>(null);
  const cancelledRef = useRef(false);

  // Initialize theme
  useEffect(() => {
    const saved = localStorage.getItem('meeting_mind_theme');
    if (saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      setTheme('dark');
      document.documentElement.classList.add('dark');
    } else {
      setTheme('light');
      document.documentElement.classList.remove('dark');
    }
  }, []);

  const toggleTheme = () => {
    const next = theme === 'light' ? 'dark' : 'light';
    setTheme(next);
    localStorage.setItem('meeting_mind_theme', next);
    if (next === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  };

  // Whole-page drag and drop handler
  useEffect(() => {
    let dragCounter = 0;

    const handleDragEnter = (e: DragEvent) => {
      e.preventDefault();
      dragCounter++;
      if (e.dataTransfer?.types?.includes('Files')) {
        setIsDragging(true);
      }
    };

    const handleDragOver = (e: DragEvent) => {
      e.preventDefault();
    };

    const handleDragLeave = (e: DragEvent) => {
      e.preventDefault();
      dragCounter--;
      if (dragCounter <= 0) {
        setIsDragging(false);
      }
    };

    const handleDrop = async (e: DragEvent) => {
      e.preventDefault();
      dragCounter = 0;
      setIsDragging(false);
      const file = e.dataTransfer?.files?.[0];
      if (!file) return;
      try {
        const text = await readTxtFile(file);
        setTranscript(text);
        setFileName(file.name);
        setIsSample(false);
        setSelectedSampleId(null);
        setError('');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Không thể đọc tệp tin.');
      }
    };

    window.addEventListener('dragenter', handleDragEnter);
    window.addEventListener('dragover', handleDragOver);
    window.addEventListener('dragleave', handleDragLeave);
    window.addEventListener('drop', handleDrop);

    return () => {
      window.removeEventListener('dragenter', handleDragEnter);
      window.removeEventListener('dragover', handleDragOver);
      window.removeEventListener('dragleave', handleDragLeave);
      window.removeEventListener('drop', handleDrop);
    };
  }, []);

  // Sync available samples from backend
  useEffect(() => {
    fetchSamples().catch(() => {});
  }, []);

  // Direct sample click: immediately fetch sample and result, transition directly to Workspace
  const handleSelectSampleDirect = async (sample: SampleItem) => {
    setLoadingSampleId(sample.id);
    setError('');
    setSelectedSampleId(sample.id);

    try {
      // 1. Fetch transcript content
      let textContent = '';
      try {
        const detail = await fetchSample(sample.id);
        textContent = detail.transcript;
      } catch {
        if (sample.id === 'test_01_happy_path') {
          textContent = sampleTranscript;
        } else {
          throw new Error(`Không thể kết nối đến máy chủ để tải biên bản mẫu "${sample.title}".`);
        }
      }

      setTranscript(textContent);
      setName(sample.name);
      setFileName(sample.filename);
      setIsSample(true);

      // 2. Fetch pre-computed verified result
      const fastResult = await fetchSampleResult(sample.id);
      setResult(fastResult);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : `Không thể nạp dữ liệu mẫu "${sample.title}". Vui lòng thử lại.`
      );
    } finally {
      setLoadingSampleId(null);
    }
  };

  const handleCancelJob = async () => {
    cancelledRef.current = true;
    if (currentJobId) {
      try {
        await cancelAnalysisJob(currentJobId);
      } catch {
        // ignore cancellation transport errors
      }
    }
    setAnalyzing(false);
    setCurrentJobId(null);
    setJobStage('cancelled');
    setJobStageLabel('Đã hủy phân tích.');
  };

  const handleAnalyze = async () => {
    if (!transcript.trim()) {
      editor.current?.focus();
      return;
    }

    setAnalyzing(true);
    setError('');
    cancelledRef.current = false;
    setJobStage('queued');
    setJobProgress(5);
    setJobStageLabel('Đang chuẩn bị phân tích...');

    try {
      // Fast-path: if user selected a pre-validated benchmark sample, fetch instant verified result
      if (isSample && selectedSampleId) {
        try {
          const fastData = await fetchSampleResult(selectedSampleId);
          setResult(fastData);
          setAnalyzing(false);
          return;
        } catch {
          // If sample result API fails, fall back to job pipeline below
        }
      }

      // Step 1: Start async job on backend
      const jobResponse = await startAnalysisJob({
        transcript,
        meeting_name: name.trim() || undefined,
        meeting_date: meetingDate || undefined,
        sample_id: selectedSampleId || undefined,
        use_sample_cache: true,
      });

      const jobId = jobResponse.job_id;
      setCurrentJobId(jobId);
      setJobStage(jobResponse.stage || 'queued');
      setJobProgress(jobResponse.progress_percent || 10);
      setJobStageLabel(jobResponse.stage_label || 'Đang xử lý...');

      // Step 2: Poll status every 500ms (with 150s client timeout)
      const pollInterval = 500;
      const pollStartTime = Date.now();
      const MAX_POLL_TIME_MS = 150000;

      while (!cancelledRef.current) {
        if (Date.now() - pollStartTime > MAX_POLL_TIME_MS) {
          throw new Error('Quá thời gian chờ phân tích từ máy chủ (Timeout sau 150s). Vui lòng thử lại.');
        }

        await new Promise((r) => setTimeout(r, pollInterval));
        if (cancelledRef.current) break;

        try {
          const status = await getAnalysisJob(jobId);
          if (cancelledRef.current) break;

          setJobStage(status.stage);
          const percent = status.progress_percent ?? Math.round((status.progress || 0) * 100);
          setJobProgress(Math.max(5, Math.min(100, percent)));

          const displayLabel = status.stage_label || status.stage_message;
          if (displayLabel) {
            setJobStageLabel(displayLabel);
          }

          // Terminal states
          if (status.status === 'completed' || status.status === 'done') {
            if (status.result) {
              setResult(status.result);
            } else {
              throw new Error('Máy chủ hoàn thành tác vụ nhưng không trả về kết quả.');
            }
            setAnalyzing(false);
            break;
          } else if (status.status === 'failed') {
            const errDetail =
              status.friendly_error || status.error || 'Quá trình phân tích thất bại trên máy chủ.';
            throw new Error(errDetail);
          } else if (status.status === 'cancelled') {
            setAnalyzing(false);
            break;
          }
        } catch (pollErr) {
          if (cancelledRef.current) break;
          if (pollErr instanceof Error) {
            if (
              pollErr.message.includes('JOB_NOT_FOUND') ||
              pollErr.message.includes('thất bại') ||
              pollErr.message.includes('Timeout') ||
              pollErr.message.includes('Lỗi') ||
              pollErr.message.includes('hợp lệ') ||
              pollErr.message.includes('Gemini')
            ) {
              throw pollErr;
            }
          }
          console.warn('[Job Poller] Poll attempt transient blip, retrying:', pollErr);
        }
      }
    } catch (err) {
      if (!cancelledRef.current) {
        const errorMsg =
          err instanceof Error ? err.message : 'Không thể hoàn thành phân tích. Vui lòng thử lại.';
        setError(errorMsg);
      }
    } finally {
      if (!cancelledRef.current) {
        setAnalyzing(false);
      }
    }
  };

  const lineCount = transcript.trim() ? transcript.trim().split(/\n/).length : 0;
  const charCount = transcript.length;

  return (
    <div className="min-h-screen bg-[#FAFAF9] dark:bg-[#0B0B0F] text-zinc-900 dark:text-zinc-100 font-sans flex flex-col justify-between selection:bg-indigo-100 dark:selection:bg-indigo-950">
      {result ? (
        <Workspace
          result={result}
          transcript={transcript}
          name={name}
          meetingDate={meetingDate}
          sample={isSample}
          initialOverlay={initialOverlay}
          onBack={() => {
            setResult(null);
            setInitialOverlay(null);
          }}
        />
      ) : (
        <>
          {/* Top minimal bar */}
          <header className="w-full max-w-4xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
            <a href="/" className="font-bold text-sm tracking-tight text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5 hover:opacity-80 transition-opacity">
              <span>Meeting Mind</span>
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-600 dark:bg-indigo-400"></span>
            </a>

            <div className="flex items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400 font-medium">
              <button
                type="button"
                onClick={() => outputUpload.current?.click()}
                className="hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors flex items-center gap-1 cursor-pointer"
                title="Nhập kết quả JSON đã xuất"
              >
                <Upload size={13} />
                <span>Nhập JSON</span>
              </button>

              <button
                type="button"
                onClick={toggleTheme}
                className="p-1.5 rounded-md hover:bg-zinc-200/60 dark:hover:bg-zinc-800 text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors cursor-pointer"
                title={theme === 'dark' ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối'}
              >
                {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
              </button>
            </div>
          </header>

          {/* Main content centered */}
          <main className="flex-1 max-w-2xl w-full mx-auto px-4 py-8 sm:py-12 flex flex-col justify-center">
            {/* Title & one-line value description */}
            <div className="text-center mb-6">
              <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100 mb-1.5">
                Meeting Mind
              </h1>
              <p className="text-sm text-zinc-500 dark:text-zinc-400 max-w-md mx-auto leading-relaxed">
                Trích xuất quyết định, việc cần làm, điểm chưa chốt và rào cản từ biên bản tiếng Việt.
              </p>
            </div>

            {/* Single Centered Input Card */}
            <div
              className={`bg-white dark:bg-[#121217] border rounded-xl p-4 sm:p-5 shadow-xs transition-all duration-200 relative ${
                isDragging
                  ? 'border-indigo-600 ring-2 ring-indigo-500/20 bg-indigo-50/20 dark:bg-indigo-950/20'
                  : 'border-zinc-200 dark:border-zinc-800'
              }`}
            >
              {/* Dragging scrim overlay notice */}
              {isDragging && (
                <div className="absolute inset-0 bg-white/90 dark:bg-zinc-900/90 rounded-xl z-20 flex flex-col items-center justify-center pointer-events-none text-indigo-600 dark:text-indigo-400">
                  <Upload size={32} className="animate-bounce" />
                  <p className="text-xs font-semibold mt-2">Thả tệp .txt vào đây để tải biên bản</p>
                </div>
              )}

              {/* Textarea with inline 'chọn file' */}
              <div className="relative">
                <textarea
                  ref={editor}
                  rows={transcript ? 8 : 6}
                  spellCheck={false}
                  value={transcript}
                  disabled={analyzing}
                  onKeyDown={(e) => {
                    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                      e.preventDefault();
                      handleAnalyze();
                    }
                  }}
                  onChange={(e) => {
                    setTranscript(e.target.value);
                    setIsSample(false);
                    setSelectedSampleId(null);
                    setFileName('');
                    setError('');
                  }}
                  placeholder="Dán biên bản cuộc họp vào đây hoặc kéo thả tệp .txt..."
                  className="w-full text-xs sm:text-[13px] leading-relaxed font-sans text-zinc-800 dark:text-zinc-200 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 outline-none resize-none bg-transparent"
                />

                {/* Inline clear button */}
                {transcript && !analyzing && (
                  <button
                    type="button"
                    onClick={() => {
                      setTranscript('');
                      setFileName('');
                      setIsSample(false);
                      setSelectedSampleId(null);
                    }}
                    title="Xóa nội dung"
                    className="absolute top-0 right-0 p-1 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 cursor-pointer rounded"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>

              {/* Collapsible 'Thêm thông tin' */}
              <div className="mt-2 pt-2 border-t border-zinc-100 dark:border-zinc-800/80">
                <button
                  type="button"
                  onClick={() => setShowExtraInfo(!showExtraInfo)}
                  className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 cursor-pointer font-medium transition-colors"
                >
                  <ChevronRight
                    size={12}
                    className={`transition-transform duration-150 ${showExtraInfo ? 'rotate-90' : ''}`}
                  />
                  <span>Thêm thông tin cuộc họp (không bắt buộc)</span>
                </button>

                {showExtraInfo && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mt-2.5 pt-2 border-t border-zinc-50 dark:border-zinc-900">
                    <div>
                      <input
                        aria-label="Tên cuộc họp"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="Tên cuộc họp (VD: Sprint 24)"
                        className="w-full px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-800 dark:text-zinc-200 placeholder:text-zinc-400 outline-none focus:border-zinc-400 bg-white dark:bg-zinc-900"
                      />
                    </div>
                    <div>
                      <input
                        type="date"
                        aria-label="Ngày cuộc họp"
                        value={meetingDate}
                        onChange={(e) => setMeetingDate(e.target.value)}
                        className="w-full px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-800 dark:text-zinc-200 placeholder:text-zinc-400 outline-none focus:border-zinc-400 bg-white dark:bg-zinc-900"
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Inline 4-Step Analysis Progress (when analyzing) */}
              {analyzing && (
                <div className="mt-3 pt-3 border-t border-zinc-100 dark:border-zinc-800 space-y-3">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium text-zinc-800 dark:text-zinc-200">
                      {jobStageLabel}
                    </span>
                    <button
                      type="button"
                      onClick={handleCancelJob}
                      className="text-xs text-zinc-400 hover:text-red-600 dark:hover:text-red-400 cursor-pointer"
                    >
                      Hủy
                    </button>
                  </div>

                  {/* 4-step inline indicator */}
                  <div className="grid grid-cols-4 gap-1.5">
                    {ANALYSIS_STEPS.map((step) => {
                      const currentIdx = STAGE_ORDER[jobStage] ?? 0;
                      const stepStagesIndices = step.stages.map((s) => STAGE_ORDER[s] ?? 0);
                      const minStageIdx = Math.min(...stepStagesIndices);
                      const maxStageIdx = Math.max(...stepStagesIndices);

                      const isDone = currentIdx > maxStageIdx || jobStage === 'done';
                      const isActive =
                        step.stages.includes(jobStage) && jobStage !== 'done';

                      return (
                        <div
                          key={step.key}
                          className={`p-2 rounded-lg border text-center transition-colors ${
                            isActive
                              ? 'border-indigo-600 dark:border-indigo-500 bg-indigo-50/50 dark:bg-indigo-950/30'
                              : isDone
                              ? 'border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900'
                              : 'border-zinc-100 dark:border-zinc-900 bg-transparent text-zinc-400 dark:text-zinc-600'
                          }`}
                        >
                          <div className="flex items-center justify-center gap-1 text-[11px] font-medium">
                            {isDone ? (
                              <Check size={11} className="text-emerald-600 dark:text-emerald-400" />
                            ) : isActive ? (
                              <LoaderCircle size={11} className="animate-spin text-indigo-600 dark:text-indigo-400" />
                            ) : null}
                            <span
                              className={
                                isActive
                                  ? 'text-indigo-600 dark:text-indigo-400 font-semibold'
                                  : isDone
                                  ? 'text-zinc-700 dark:text-zinc-300'
                                  : 'text-zinc-400 dark:text-zinc-600'
                              }
                            >
                              {step.label}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Subtle Progress bar */}
                  <div className="w-full bg-zinc-100 dark:bg-zinc-800 h-1 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-600 dark:bg-indigo-500 rounded-full transition-all duration-300 ease-out"
                      style={{ width: `${jobProgress}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Inline Error Notice with Retry */}
              {error && (
                <div className="mt-3 p-3 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 text-xs text-red-700 dark:text-red-400 flex items-start gap-2">
                  <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <div>{error}</div>
                    <div className="mt-2 flex items-center gap-3">
                      <button
                        type="button"
                        onClick={handleAnalyze}
                        className="px-2 py-0.5 rounded bg-red-600 hover:bg-red-700 text-white font-medium text-[11px] cursor-pointer flex items-center gap-1"
                      >
                        <RefreshCw size={10} />
                        <span>Thử lại</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setError('')}
                        className="text-[11px] text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 cursor-pointer"
                      >
                        Bỏ qua
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Bottom Card Controls */}
              <div className="mt-3 pt-3 border-t border-zinc-100 dark:border-zinc-800/80 flex items-center justify-between">
                <div className="text-xs text-zinc-400 dark:text-zinc-500 flex items-center gap-2">
                  {transcript ? (
                    <>
                      <span>{lineCount} dòng</span>
                      <span>·</span>
                      <span>{charCount.toLocaleString()} ký tự</span>
                      {fileName && (
                        <>
                          <span>·</span>
                          <span className="text-zinc-700 dark:text-zinc-300 font-medium">
                            {fileName}
                          </span>
                        </>
                      )}
                    </>
                  ) : (
                    <span>
                      Dán văn bản hoặc{' '}
                      <button
                        type="button"
                        onClick={() => upload.current?.click()}
                        className="text-zinc-700 dark:text-zinc-300 hover:underline cursor-pointer font-medium"
                      >
                        chọn tệp .txt
                      </button>
                    </span>
                  )}
                </div>

                <button
                  type="button"
                  disabled={!transcript.trim() || analyzing || loadingSampleId !== null}
                  onClick={handleAnalyze}
                  className={`font-medium text-xs px-4 py-2 rounded-lg transition-colors flex items-center gap-1.5 ${
                    !transcript.trim() || analyzing || loadingSampleId !== null
                      ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-600 cursor-not-allowed'
                      : 'bg-zinc-900 hover:bg-zinc-800 dark:bg-zinc-100 dark:hover:bg-zinc-200 text-white dark:text-zinc-900 cursor-pointer'
                  }`}
                  title="Phím tắt: Ctrl + Enter"
                >
                  {analyzing ? (
                    <>
                      <LoaderCircle className="animate-spin" size={13} />
                      <span>Đang phân tích...</span>
                    </>
                  ) : (
                    <>
                      <span>Phân tích</span>
                      <ArrowRight size={13} />
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Horizontal Benchmark Sample Chips Below Card */}
            <div className="mt-5">
              <div className="text-[11px] font-medium text-zinc-400 dark:text-zinc-500 mb-2">
                Hoặc thử ngay với biên bản mẫu:
              </div>
              <div className="flex flex-wrap gap-1.5">
                {BENCHMARK_SAMPLES.map((s) => {
                  const isLoading = loadingSampleId === s.id;
                  return (
                    <button
                      key={s.id}
                      type="button"
                      disabled={analyzing || loadingSampleId !== null}
                      onClick={() => handleSelectSampleDirect(s)}
                      className="px-2.5 py-1 rounded-full text-xs border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:border-zinc-400 dark:hover:border-zinc-600 hover:bg-zinc-50 dark:hover:bg-zinc-800/80 transition-colors cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
                    >
                      {isLoading && <LoaderCircle size={10} className="animate-spin text-zinc-500" />}
                      <span>{s.title}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </main>

          {/* Minimal footer */}
          <footer className="w-full max-w-4xl mx-auto px-4 sm:px-6 py-4 text-center text-xs text-zinc-400 dark:text-zinc-600">
            <span>Meeting Mind · Đối soát bằng chứng từ phát biểu gốc</span>
          </footer>
        </>
      )}

      {/* Hidden File Upload Inputs */}
      <input
        ref={upload}
        type="file"
        accept=".txt,text/plain"
        className="hidden"
        aria-label="Tải tệp biên bản"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          try {
            const text = await readTxtFile(file);
            setTranscript(text);
            setFileName(file.name);
            setIsSample(false);
            setSelectedSampleId(null);
            setError('');
          } catch (err) {
            setError(err instanceof Error ? err.message : 'Không thể đọc tệp tin.');
          } finally {
            e.target.value = '';
          }
        }}
      />

      <input
        ref={outputUpload}
        type="file"
        accept=".json,application/json"
        className="hidden"
        aria-label="Nhập tệp JSON kết quả"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          try {
            const raw = await file.text();
            const data: unknown = JSON.parse(raw);

            // Case A: ExportPackage with AI result + User Overlay
            if (isExportPackage(data)) {
              setResult(data.result);
              setTranscript(data.result.summary || '');
              setName(data.metadata?.meeting_name || '');
              setIsSample(false);

              if (data.overlay) {
                setInitialOverlay(data.overlay);
                const adapter = getDefaultPersistenceAdapter();
                adapter.saveOverlay(data.result.meta.meeting_id, data.overlay);
              }
              setError('');
              return;
            }

            // Case B: Public MeetingOutput format
            if (isMeetingResult(data)) {
              setResult(data);
              setTranscript(data.summary || '');
              setIsSample(false);
              setInitialOverlay(null);
              setError('');
              return;
            }

            // Case C: Legacy MeetingResult format
            if (isLegacyMeetingFormat(data)) {
              try {
                const upgraded = await upgradeLegacyResult(data);
                setResult(upgraded);
                setTranscript(upgraded.summary || '');
                setIsSample(false);
                setInitialOverlay(null);
                setError('');
                return;
              } catch {
                setResult(data);
                setTranscript(data.summary || '');
                setIsSample(false);
                setInitialOverlay(null);
                setError('');
                return;
              }
            }

            throw new Error('Định dạng tệp JSON không hợp lệ.');
          } catch (err) {
            setError(err instanceof Error ? err.message : 'Không thể nhập tệp JSON.');
          } finally {
            e.target.value = '';
          }
        }}
      />
    </div>
  );
}
