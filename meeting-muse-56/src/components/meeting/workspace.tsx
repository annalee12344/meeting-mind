import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import {
  Download,
  Plus,
  Clock,
  Check,
  ChevronDown,
  Pencil,
  FileText,
  AlertTriangle,
  X,
  User,
  Calendar,
  Trash2,
  ArrowLeft,
  ShieldCheck,
  CheckSquare,
  Square,
  RotateCcw,
  MoreVertical,
  MoreHorizontal,
  Sun,
  Moon,
  MessageSquareQuote,
  Eye,
  CheckCircle2,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  exportMeeting,
  type Evidence,
  type MeetingResult,
} from '@/lib/meeting';
import type {
  MeetingOutput,
  MeetingOverlay,
  MeetingViewModel,
  ViewTask,
  ViewUnresolvedItem,
  ViewIssue,
  PublicDecision,
} from '@/lib/types.generated';
import {
  mergeMeetingView,
  createEmptyOverlay,
  applyTaskEdit,
  applyTaskStatus,
  applyTaskDelete,
  applyManualTask,
  applyConvertUnresolved,
  applyIssueStatus,
  applyIssueNote,
  applyEditIssueNote,
  applyDeleteIssueNote,
  generateUUID,
} from '@/lib/overlay';
import { getDefaultPersistenceAdapter } from '@/lib/storage';
import { getDeadlineWarning } from '@/lib/deadlines';
import {
  cleanTaskFields,
  formatDeadlineToDisplay,
  parseDateAndTime,
} from '@/lib/task-utils';
import { TranscriptPanel, type ActiveEvidence } from './transcript-panel';
import { DecisionTrail } from './decision-trail';
import { IssueNotes } from './issue-notes';
import { SectionErrorBoundary } from './section-error-boundary';

export type ViewSection = 'decisions' | 'todos' | 'unresolved' | 'issues';

// Compatibility export in case other modules reference MindyMascot
export function MindyMascot() {
  return null;
}

export interface WorkspaceProps {
  result: MeetingResult | MeetingOutput;
  transcript: string;
  name?: string;
  meetingDate?: string;
  onBack: () => void;
  sample?: boolean;
  initialOverlay?: MeetingOverlay | null;
}

export function Workspace({
  result,
  transcript,
  name: initialName,
  meetingDate,
  onBack,
  initialOverlay,
}: WorkspaceProps) {
  // Normalize AI Output
  const aiOutput: MeetingOutput = useMemo(() => {
    let rawOutput: MeetingOutput;

    if ('tasks' in result && Array.isArray((result as any).tasks)) {
      const modern = result as MeetingOutput;
      rawOutput = {
        ...modern,
        decisions: (modern.decisions || []).map((d) => ({
          ...d,
          status: d.status || 'confirmed',
        })),
      };
    } else {
      const legacy = result as any;
      rawOutput = {
        summary: legacy.meeting_summary || legacy.summary || '',
        participants: legacy.participants || [],
        decisions: (legacy.decisions || []).map((d: any) => ({
          id: d.id || d.item_id || generateUUID(),
          source_ref: d.item_id || null,
          topic: d.topic || '',
          content: d.final_value || d.content || '',
          proposed_by: d.proposed_by || null,
          confirmed_by: d.confirmed_by || null,
          status: d.status || 'confirmed',
          condition: d.condition || null,
          history: d.history || [],
          evidence: d.evidence || [],
          needs_review: Boolean(d.needs_review),
        })),
        tasks: (legacy.action_items || []).map((a: any) => ({
          id: a.id || a.item_id || generateUUID(),
          source_ref: a.item_id || null,
          title: a.task || a.title || '',
          assignee: a.assignee || null,
          assigned_by: a.assigned_by || null,
          requested_by: a.requested_by || null,
          deadline_raw: a.deadline || a.deadline_raw || null,
          deadline_iso: a.deadline_iso || null,
          source: 'ai' as const,
          evidence: a.evidence || [],
          needs_review: Boolean(a.needs_review),
        })),
        unresolved: (legacy.unresolved_items || []).map((u: any) => ({
          id: u.id || u.item_id || generateUUID(),
          source_ref: u.item_id || null,
          kind: 'open_decision' as const,
          content: u.issue || u.content || '',
          reason_unresolved: u.reason_unresolved || null,
          suggested_assignee: u.owner || null,
          suggested_deadline_raw: null,
          suggested_deadline_iso: null,
          evidence: u.evidence || [],
          needs_review: Boolean(u.needs_review),
        })),
        issues: (legacy.blockers || []).map((b: any) => ({
          id: b.id || b.item_id || generateUUID(),
          source_ref: b.item_id || null,
          content: b.issue || b.content || '',
          owner: b.owner || null,
          status: (b.status === 'resolved' ? 'resolved' : 'open') as 'open' | 'resolved',
          evidence: b.evidence || [],
          notes: [],
          needs_review: Boolean(b.needs_review),
        })),
        meta: legacy.meta || {
          schema_version: '2.0.0',
          prompt_version: '2.0.0',
          extractor_model: 'gemini-flash-lite-latest',
          resolver_model: 'gemini-flash-lite-latest',
          analyzed_at: new Date().toISOString(),
          transcript_hash: 'legacy',
          meeting_date: meetingDate || new Date().toISOString().split('T')[0],
          meeting_date_source: meetingDate ? 'user_input' : 'fallback_today',
        },
      };
    }

    // Clean each task title, separate assignee and deadline
    const cleanedTasks = (rawOutput.tasks || []).map((t) => {
      const cleaned = cleanTaskFields(
        t.title,
        t.assignee,
        t.deadline_raw,
        t.deadline_iso,
        rawOutput.meta?.meeting_date || meetingDate
      );
      return {
        ...t,
        title: cleaned.title,
        assignee: cleaned.assignee,
        deadline_raw: cleaned.deadline_raw,
        deadline_iso: cleaned.deadline_iso,
      };
    });

    return {
      ...rawOutput,
      tasks: cleanedTasks,
    };
  }, [result, meetingDate]);

  // Persistence adapter for local overlay storage
  const persistence = useMemo(() => getDefaultPersistenceAdapter(), []);
  const meetingId = useMemo(() => {
    return (
      initialOverlay?.meeting_id ||
      aiOutput.meta?.transcript_hash ||
      aiOutput.decisions?.[0]?.id ||
      'default_meeting'
    );
  }, [initialOverlay, aiOutput]);

  const [overlay, setOverlay] = useState<MeetingOverlay>(() => {
    return initialOverlay || createEmptyOverlay(meetingId, aiOutput.meta?.transcript_hash);
  });

  // Load overlay on mount
  useEffect(() => {
    if (initialOverlay) return;
    let isMounted = true;
    persistence.loadOverlay(meetingId).then((loaded) => {
      if (isMounted && loaded) {
        setOverlay(loaded);
      }
    });
    return () => {
      isMounted = false;
    };
  }, [meetingId, initialOverlay, persistence]);

  // Auto-persist overlay updates
  const updateOverlay = useCallback(
    (newOverlay: MeetingOverlay) => {
      setOverlay(newOverlay);
      persistence.saveOverlay(newOverlay).catch((err) => {
        console.warn('[Workspace] Auto-persist overlay failed:', err);
      });
    },
    [persistence]
  );

  // Pure merge of AI layer + User overlay -> Unified View Model
  const viewModel: MeetingViewModel = useMemo(
    () => mergeMeetingView(aiOutput, overlay),
    [aiOutput, overlay]
  );

  // Editable Meeting Title
  const [meetingTitle, setMeetingTitle] = useState(
    initialName || aiOutput.meta?.meeting_name || 'Biên bản cuộc họp'
  );
  const [isEditingTitle, setIsEditingTitle] = useState(false);

  // Confirmed Decisions only
  const confirmedDecisions = useMemo(() => {
    return (viewModel.decisions || []).filter((d) => d.status === 'confirmed');
  }, [viewModel.decisions]);

  // Tasks breakdown
  const activeTasks = useMemo(() => {
    return (viewModel.tasks || []).filter((t) => t.status !== 'done');
  }, [viewModel.tasks]);

  const completedTasks = useMemo(() => {
    return (viewModel.tasks || []).filter((t) => t.status === 'done');
  }, [viewModel.tasks]);

  // Urgent tasks count (overdue or due within 48h)
  const urgentTasksCount = useMemo(() => {
    return activeTasks.filter((t) => {
      const w = getDeadlineWarning(t.deadline_iso, false);
      return Boolean(w?.isWarning);
    }).length;
  }, [activeTasks]);

  // Open issues count
  const openIssuesCount = useMemo(() => {
    return (viewModel.issues || []).filter((i) => i.status === 'open').length;
  }, [viewModel.issues]);

  // Default section: first non-empty group
  const defaultSection = useMemo<ViewSection>(() => {
    if ((confirmedDecisions || []).length > 0) return 'decisions';
    if ((viewModel.tasks || []).length > 0) return 'todos';
    if ((viewModel.unresolved || []).length > 0) return 'unresolved';
    if ((viewModel.issues || []).length > 0) return 'issues';
    return 'decisions';
  }, [confirmedDecisions.length, viewModel.tasks?.length, viewModel.unresolved?.length, viewModel.issues?.length]);

  const [currentSection, setCurrentSection] = useState<ViewSection>(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const tabParam = params.get('tab') as ViewSection;
      if (tabParam && ['decisions', 'todos', 'unresolved', 'issues'].includes(tabParam)) {
        return tabParam;
      }
    }
    return defaultSection;
  });

  const handleSelectSection = (sec: ViewSection) => {
    setCurrentSection(sec);
    if (typeof window !== 'undefined' && window.history?.replaceState) {
      const url = new URL(window.location.href);
      url.searchParams.set('tab', sec);
      window.history.replaceState({}, '', url.toString());
    }
  };

  // Summary expansion (max 3 lines toggle)
  const [summaryExpanded, setSummaryExpanded] = useState(false);

  // Participant filter for Tasks
  const [taskAssigneeFilter, setTaskAssigneeFilter] = useState<string>('all');

  // ── TASK SELECTION & COMPACT ROW STATE ────────────────────────
  const [isSelectMode, setIsSelectMode] = useState(false);
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(new Set());

  // Task inline creation state
  const [showInlineTaskCreate, setShowInlineTaskCreate] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskAssignee, setNewTaskAssignee] = useState('');
  const [newTaskDate, setNewTaskDate] = useState('');
  const [newTaskTime, setNewTaskTime] = useState('');

  // Task 3-dots open menu id
  const [activeMenuTaskId, setActiveMenuTaskId] = useState<string | null>(null);

  // Task Detail Modal state (for clicking row to see details)
  const [detailModalTask, setDetailModalTask] = useState<ViewTask | null>(null);

  // Task Edit Modal state
  const [editingTask, setEditingTask] = useState<ViewTask | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editAssignee, setEditAssignee] = useState('');
  const [editDate, setEditDate] = useState('');
  const [editTime, setEditTime] = useState('');

  // Unresolved -> Task Conversion Modal state
  const [convertModalItem, setConvertModalItem] = useState<ViewUnresolvedItem | null>(null);
  const [convertTitle, setConvertTitle] = useState('');
  const [convertAssignee, setConvertAssignee] = useState('');
  const [convertDate, setConvertDate] = useState('');
  const [convertTime, setConvertTime] = useState('');

  const openEditTaskModal = (task: ViewTask) => {
    setEditingTask(task);
    setEditTitle(task.title);
    setEditAssignee(task.assignee || '');
    const { datePart, timePart } = parseDateAndTime(
      task.deadline_raw,
      task.deadline_iso,
      aiOutput.meta?.meeting_date ? parseInt(aiOutput.meta.meeting_date.substring(0, 4), 10) : 2026
    );
    setEditDate(datePart);
    setEditTime(timePart);
  };

  // Ticking row exit animation tracking
  const [exitingTaskIds, setExitingTaskIds] = useState<Set<string>>(new Set());

  // In-place expanded decisions
  const [expandedDecisionIds, setExpandedDecisionIds] = useState<Set<string>>(new Set());

  // Issues tab filter: 'open' | 'resolved'
  const [issueFilter, setIssueFilter] = useState<'open' | 'resolved'>('open');

  // Top bar overflow menu state
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menus on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
      // Close task 3-dots menu if clicking outside
      const target = e.target as HTMLElement;
      if (!target.closest('[data-task-menu]')) {
        setActiveMenuTaskId(null);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Theme toggle
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    if (typeof document !== 'undefined' && document.documentElement.classList.contains('dark')) {
      return 'dark';
    }
    return 'light';
  });

  const handleToggleTheme = () => {
    const next = theme === 'light' ? 'dark' : 'light';
    setTheme(next);
    localStorage.setItem('meeting_mind_theme', next);
    if (next === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  };

  // Transcript Panel State
  const [transcriptPanelOpen, setTranscriptPanelOpen] = useState(false);
  const [activeEvidence, setActiveEvidence] = useState<ActiveEvidence | null>(null);

  const handleOpenEvidence = (
    ev: Evidence | Evidence[],
    itemTitle: string,
    itemType: 'decision' | 'task' | 'unresolved' | 'issue',
    itemTypeLabel: string
  ) => {
    const list = Array.isArray(ev) ? ev : [ev];
    setActiveEvidence({
      evidence: list[0],
      evidenceList: list,
      activeEvidenceIndex: 0,
      itemTitle,
      itemTypeLabel,
      itemType,
    });
    setTranscriptPanelOpen(true);
  };

  // ── TASKS OPERATIONS ──────────────────────────────────────────
  const handleToggleTaskStatus = (task: ViewTask) => {
    const newStatus = task.status === 'done' ? 'pending' : 'done';
    const previousOverlay = overlay;

    if (newStatus === 'done') {
      // Trigger exit animation before state update
      setExitingTaskIds((prev) => new Set(prev).add(task.id));
      setTimeout(() => {
        const nextOverlay = applyTaskStatus(overlay, task.id, 'done');
        updateOverlay(nextOverlay);
        setExitingTaskIds((prev) => {
          const next = new Set(prev);
          next.delete(task.id);
          return next;
        });

        toast('Đã hoàn thành việc: ' + task.title, {
          action: {
            label: 'Hoàn tác',
            onClick: () => updateOverlay(previousOverlay),
          },
          duration: 4000,
        });
      }, 180);
    } else {
      const nextOverlay = applyTaskStatus(overlay, task.id, 'pending');
      updateOverlay(nextOverlay);
      toast('Đã mở lại việc: ' + task.title, {
        action: {
          label: 'Hoàn tác',
          onClick: () => updateOverlay(previousOverlay),
        },
        duration: 4000,
      });
    }
  };

  const handleDeleteTask = (task: ViewTask) => {
    const previousOverlay = overlay;
    setExitingTaskIds((prev) => new Set(prev).add(task.id));

    setTimeout(() => {
      const nextOverlay = applyTaskDelete(overlay, task.id);
      updateOverlay(nextOverlay);
      setExitingTaskIds((prev) => {
        const next = new Set(prev);
        next.delete(task.id);
        return next;
      });

      toast('Đã xóa việc: ' + task.title, {
        action: {
          label: 'Hoàn tác',
          onClick: () => updateOverlay(previousOverlay),
        },
        duration: 5000,
      });
    }, 180);
  };

  const handleCreateInlineTask = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTaskTitle.trim()) return;

    const previousOverlay = overlay;
    const finalDeadlineRaw = formatDeadlineToDisplay(newTaskDate, newTaskTime) || null;
    const finalDeadlineIso = newTaskDate
      ? `${newTaskDate}T${newTaskTime ? newTaskTime + ':00' : '23:59:59'}`
      : null;

    const { overlay: nextOverlay } = applyManualTask(overlay, {
      title: newTaskTitle.trim(),
      assignee: newTaskAssignee.trim() || null,
      deadline_raw: finalDeadlineRaw,
      deadline_iso: finalDeadlineIso,
    });
    updateOverlay(nextOverlay);
    setNewTaskTitle('');
    setNewTaskAssignee('');
    setNewTaskDate('');
    setNewTaskTime('');
    setShowInlineTaskCreate(false);

    toast('Đã thêm việc mới', {
      action: {
        label: 'Hoàn tác',
        onClick: () => updateOverlay(previousOverlay),
      },
      duration: 4000,
    });
  };

  const handleSaveEditTask = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingTask || !editTitle.trim()) return;
    const previousOverlay = overlay;
    const finalDeadlineRaw = formatDeadlineToDisplay(editDate, editTime) || null;
    const finalDeadlineIso = editDate
      ? `${editDate}T${editTime ? editTime + ':00' : '23:59:59'}`
      : null;

    const nextOverlay = applyTaskEdit(overlay, editingTask.id, {
      title: editTitle.trim(),
      assignee: editAssignee.trim() || null,
      deadline_raw: finalDeadlineRaw,
      deadline_iso: finalDeadlineIso,
    });
    updateOverlay(nextOverlay);
    setEditingTask(null);

    toast('Đã cập nhật công việc', {
      action: {
        label: 'Hoàn tác',
        onClick: () => updateOverlay(previousOverlay),
      },
      duration: 4000,
    });
  };

  // Bulk actions on selected tasks
  const handleBulkComplete = () => {
    const previousOverlay = overlay;
    let next = overlay;
    selectedTaskIds.forEach((id) => {
      next = applyTaskStatus(next, id, 'done');
    });
    updateOverlay(next);
    const count = selectedTaskIds.size;
    setSelectedTaskIds(new Set());
    setIsSelectMode(false);

    toast(`Đã hoàn thành ${count} việc`, {
      action: {
        label: 'Hoàn tác',
        onClick: () => updateOverlay(previousOverlay),
      },
      duration: 4000,
    });
  };

  const handleBulkDelete = () => {
    const previousOverlay = overlay;
    let next = overlay;
    selectedTaskIds.forEach((id) => {
      next = applyTaskDelete(next, id);
    });
    updateOverlay(next);
    const count = selectedTaskIds.size;
    setSelectedTaskIds(new Set());
    setIsSelectMode(false);

    toast(`Đã xóa ${count} việc`, {
      action: {
        label: 'Hoàn tác',
        onClick: () => updateOverlay(previousOverlay),
      },
      duration: 5000,
    });
  };

  // Filtered task rows
  const displayTasks = useMemo(() => {
    return activeTasks.filter((t) => {
      if (taskAssigneeFilter === 'all') return true;
      return t.assignee?.toLowerCase() === taskAssigneeFilter.toLowerCase();
    });
  }, [activeTasks, taskAssigneeFilter]);

  const handleToggleSelectAll = () => {
    if (selectedTaskIds.size === displayTasks.length) {
      setSelectedTaskIds(new Set());
    } else {
      setSelectedTaskIds(new Set(displayTasks.map((t) => t.id)));
    }
  };

  // ── UNRESOLVED CONVERSION (THÊM VIỆC) ────────────────────────
  const handleOpenConvertModal = (item: ViewUnresolvedItem) => {
    const cleaned = cleanTaskFields(
      item.content,
      item.suggested_assignee,
      item.suggested_deadline_raw,
      item.suggested_deadline_iso,
      aiOutput.meta?.meeting_date
    );
    setConvertModalItem(item);
    setConvertTitle(cleaned.title);
    setConvertAssignee(cleaned.assignee || '');
    setConvertDate(cleaned.datePart || '');
    setConvertTime(cleaned.timePart || '');
  };

  const handleSaveConvertUnresolved = (e: React.FormEvent) => {
    e.preventDefault();
    if (!convertModalItem || !convertTitle.trim()) return;

    const previousOverlay = overlay;
    const finalDeadlineRaw = formatDeadlineToDisplay(convertDate, convertTime) || null;
    const finalDeadlineIso = convertDate
      ? `${convertDate}T${convertTime ? convertTime + ':00' : '23:59:59'}`
      : null;

    let { overlay: nextOverlay, task: newTask } = applyConvertUnresolved(
      overlay,
      convertModalItem,
      convertAssignee.trim() || null,
      finalDeadlineRaw,
      finalDeadlineIso
    );

    // If user edited the title in the convert modal, apply it to the created task
    if (convertTitle.trim() && convertTitle.trim() !== newTask.title) {
      nextOverlay = applyTaskEdit(nextOverlay, newTask.id, {
        title: convertTitle.trim(),
      });
    }

    updateOverlay(nextOverlay);
    setConvertModalItem(null);

    toast(`Đã thêm vào việc cần làm: ${convertTitle.trim()}`, {
      action: {
        label: 'Hoàn tác',
        onClick: () => updateOverlay(previousOverlay),
      },
      duration: 4500,
    });
  };

  // ── ISSUES STATUS ─────────────────────────────────────────────
  const handleToggleIssueStatus = (issue: ViewIssue) => {
    const previousOverlay = overlay;
    const nextStatus = issue.status === 'open' ? 'resolved' : 'open';
    const nextOverlay = applyIssueStatus(overlay, issue.id, nextStatus);
    updateOverlay(nextOverlay);

    toast(
      nextStatus === 'resolved'
        ? 'Đã đánh dấu vấn đề được giải quyết'
        : 'Đã mở lại vấn đề',
      {
        action: {
          label: 'Hoàn tác',
          onClick: () => updateOverlay(previousOverlay),
        },
        duration: 4000,
      }
    );
  };

  // Participants unique list
  const allParticipants = useMemo(() => {
    const set = new Set<string>(aiOutput.participants || []);
    viewModel.tasks.forEach((t) => {
      if (t.assignee) set.add(t.assignee);
    });
    return Array.from(set).filter(Boolean);
  }, [aiOutput.participants, viewModel.tasks]);

  return (
    <div className="min-h-screen bg-[#FAFAF9] dark:bg-[#0B0B0F] text-zinc-900 dark:text-zinc-100 font-sans flex flex-col pb-20 md:pb-12 selection:bg-indigo-100 dark:selection:bg-indigo-950">
      {/* ── 1. STICKY TOP BAR (56px) ─────────────────────────── */}
      <header className="sticky top-0 z-40 h-14 bg-white/90 dark:bg-[#121217]/90 backdrop-blur-md border-b border-zinc-200 dark:border-zinc-800 px-4 sm:px-6 flex items-center justify-between gap-3">
        {/* Left: Back Arrow + Inline Editable Meeting Title + Date Chip */}
        <div className="flex items-center gap-2.5 min-w-0 flex-1">
          <button
            type="button"
            onClick={onBack}
            className="p-1.5 -ml-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer shrink-0"
            title="Quay lại màn hình chính"
            aria-label="Quay lại"
          >
            <ArrowLeft size={16} />
          </button>

          {isEditingTitle ? (
            <input
              value={meetingTitle}
              autoFocus
              onBlur={() => setIsEditingTitle(false)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') setIsEditingTitle(false);
              }}
              onChange={(e) => setMeetingTitle(e.target.value)}
              className="font-bold text-sm sm:text-base text-zinc-900 dark:text-zinc-100 bg-transparent border-b border-indigo-600 dark:border-indigo-400 outline-none px-1 py-0.5"
            />
          ) : (
            <div
              onClick={() => setIsEditingTitle(true)}
              className="flex items-center gap-1.5 font-bold text-sm sm:text-base text-zinc-900 dark:text-zinc-100 truncate cursor-pointer hover:opacity-80 transition-opacity group"
              title="Nhấp để sửa tên cuộc họp"
            >
              <span className="truncate">{meetingTitle}</span>
              <Pencil size={11} className="opacity-0 group-hover:opacity-60 shrink-0 text-zinc-400" />
            </div>
          )}

          {aiOutput.meta?.meeting_date && (
            <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 shrink-0">
              <Calendar size={11} />
              <span>{aiOutput.meta.meeting_date}</span>
            </span>
          )}
        </div>

        {/* Right Actions: 'Biên bản', 'Xuất', Overflow */}
        <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
          <button
            type="button"
            onClick={() => {
              setActiveEvidence(null);
              setTranscriptPanelOpen(true);
            }}
            className="px-2.5 sm:px-3 py-1.5 rounded-lg text-xs font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 border border-zinc-200 dark:border-zinc-800 transition-colors flex items-center gap-1.5 cursor-pointer"
            title="Mở toàn văn biên bản"
          >
            <FileText size={13} className="text-zinc-500" />
            <span>Biên bản</span>
          </button>

          <button
            type="button"
            onClick={() => exportMeeting(aiOutput, meetingTitle, overlay, transcript)}
            className="px-2.5 sm:px-3 py-1.5 rounded-lg text-xs font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 border border-zinc-200 dark:border-zinc-800 transition-colors flex items-center gap-1.5 cursor-pointer"
            title="Xuất dữ liệu kèm các chỉnh sửa dưới dạng JSON"
          >
            <Download size={13} className="text-zinc-500" />
            <span className="hidden sm:inline">Xuất JSON</span>
            <span className="sm:hidden">Xuất</span>
          </button>

          {/* Overflow Menu */}
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen(!menuOpen)}
              className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
              title="Tùy chọn khác"
              aria-label="Tùy chọn"
            >
              <MoreVertical size={16} />
            </button>

            {menuOpen && (
              <div className="absolute right-0 top-full mt-1.5 w-48 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-lg p-1 z-50 text-xs">
                <button
                  type="button"
                  onClick={() => {
                    handleToggleTheme();
                    setMenuOpen(false);
                  }}
                  className="w-full text-left px-3 py-2 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 flex items-center gap-2 cursor-pointer"
                >
                  {theme === 'dark' ? <Sun size={13} /> : <Moon size={13} />}
                  <span>{theme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối'}</span>
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    onBack();
                  }}
                  className="w-full text-left px-3 py-2 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 flex items-center gap-2 cursor-pointer"
                >
                  <RotateCcw size={13} />
                  <span>Phân tích mới</span>
                </button>

                <div className="my-1 border-t border-zinc-100 dark:border-zinc-800" />

                <button
                  type="button"
                  onClick={() => {
                    const empty = createEmptyOverlay(meetingId, aiOutput.meta?.transcript_hash);
                    updateOverlay(empty);
                    setMenuOpen(false);
                    toast('Đã đặt lại tất cả thay đổi cá nhân');
                  }}
                  className="w-full text-left px-3 py-2 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/40 text-red-600 dark:text-red-400 flex items-center gap-2 cursor-pointer"
                >
                  <Trash2 size={13} />
                  <span>Xóa thay đổi cá nhân</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-4xl w-full mx-auto px-4 sm:px-6 pt-5 flex-1 flex flex-col">
        {/* ── 2. TỔNG QUAN CUỘC HỌP & 4 KHỐI THỐNG KÊ ĐIỀU HƯỚNG ─── */}
        <div className="bg-white dark:bg-[#121217] border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 sm:p-5 shadow-xs mb-5 transition-all">
          <div className="flex items-center justify-between gap-3 mb-2">
            <span className="text-xs font-bold text-zinc-900 dark:text-zinc-100 tracking-tight">
              Tổng quan cuộc họp
            </span>
            {aiOutput.participants?.length > 0 && (
              <span className="text-[11px] text-zinc-400">
                {aiOutput.participants.length} người tham gia
              </span>
            )}
          </div>

          <div className="space-y-4 pt-1">
            {/* Summary text (max 3 lines + 'Xem thêm') */}
            {aiOutput.summary && (
              <div>
                <p
                  className={`text-xs sm:text-[13px] leading-relaxed text-zinc-600 dark:text-zinc-400 ${
                    summaryExpanded ? '' : 'line-clamp-3'
                  }`}
                >
                  {aiOutput.summary}
                </p>
                {aiOutput.summary.length > 200 && (
                  <button
                    type="button"
                    onClick={() => setSummaryExpanded(!summaryExpanded)}
                    className="text-[11px] font-medium text-indigo-600 dark:text-indigo-400 hover:underline mt-1 cursor-pointer"
                  >
                    {summaryExpanded ? 'Thu gọn' : 'Xem thêm'}
                  </button>
                )}
              </div>
            )}

            {/* Participant Filter Chips */}
            {allParticipants.length > 0 && (
              <div className="flex items-center gap-1.5 flex-wrap pt-1">
                <span className="text-[11px] text-zinc-400 mr-1">Lọc việc:</span>
                <button
                  type="button"
                  onClick={() => setTaskAssigneeFilter('all')}
                  className={`px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors cursor-pointer ${
                    taskAssigneeFilter === 'all'
                      ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
                      : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700'
                  }`}
                >
                  Tất cả
                </button>
                {allParticipants.map((p) => {
                  const isSelected = taskAssigneeFilter.toLowerCase() === p.toLowerCase();
                  return (
                    <button
                      key={p}
                      type="button"
                      onClick={() => {
                        setTaskAssigneeFilter(isSelected ? 'all' : p);
                        if (currentSection !== 'todos') setCurrentSection('todos');
                      }}
                      className={`px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors cursor-pointer flex items-center gap-1 ${
                        isSelected
                          ? 'bg-emerald-600 text-white dark:bg-emerald-500'
                          : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700'
                      }`}
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400"></span>
                      <span>{p}</span>
                    </button>
                  );
                })}
              </div>
            )}

            {/* 4 KHỐI THỐNG KÊ (ĐÓNG VAI TRÒ CHỌN DANH SÁCH DUY NHẤT, KHÔNG CẦN HÀNG TAB) */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 border-t border-zinc-100 dark:border-zinc-800/80">
              {/* 1. Quyết định */}
              <button
                type="button"
                onClick={() => handleSelectSection('decisions')}
                className={`p-3 rounded-xl border text-left transition-all cursor-pointer ${
                  currentSection === 'decisions'
                    ? 'border-2 border-indigo-600 dark:border-indigo-500 bg-indigo-50/40 dark:bg-indigo-950/30 shadow-xs'
                    : 'border-zinc-200/80 dark:border-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-700 bg-zinc-50/30 dark:bg-zinc-900/30'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className={`text-[11px] font-semibold ${currentSection === 'decisions' ? 'text-indigo-700 dark:text-indigo-300' : 'text-zinc-600 dark:text-zinc-400'}`}>
                    Quyết định
                  </span>
                  {currentSection === 'decisions' && (
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-600 dark:bg-indigo-400" />
                  )}
                </div>
                <div className="text-xl sm:text-2xl font-bold text-indigo-600 dark:text-indigo-400 mt-1 tabular-nums">
                  {confirmedDecisions.length}
                </div>
              </button>

              {/* 2. Việc cần làm */}
              <button
                type="button"
                onClick={() => handleSelectSection('todos')}
                className={`p-3 rounded-xl border text-left transition-all cursor-pointer relative ${
                  currentSection === 'todos'
                    ? 'border-2 border-emerald-600 dark:border-emerald-500 bg-emerald-50/40 dark:bg-emerald-950/30 shadow-xs'
                    : 'border-zinc-200/80 dark:border-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-700 bg-zinc-50/30 dark:bg-zinc-900/30'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className={`text-[11px] font-semibold ${currentSection === 'todos' ? 'text-emerald-700 dark:text-emerald-300' : 'text-zinc-600 dark:text-zinc-400'}`}>
                    Việc cần làm
                  </span>
                  <div className="flex items-center gap-1">
                    {urgentTasksCount > 0 && (
                      <span className="w-2 h-2 rounded-full bg-red-600 shrink-0" title={`${urgentTasksCount} việc cận hạn/quá hạn`} />
                    )}
                    {currentSection === 'todos' && (
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-600 dark:bg-emerald-400" />
                    )}
                  </div>
                </div>
                <div className="text-xl sm:text-2xl font-bold text-emerald-600 dark:text-emerald-400 mt-1 tabular-nums">
                  {activeTasks.length}
                </div>
              </button>

              {/* 3. Chưa thống nhất (Unresolved) */}
              <button
                type="button"
                onClick={() => handleSelectSection('unresolved')}
                className={`p-3 rounded-xl border text-left transition-all cursor-pointer ${
                  currentSection === 'unresolved'
                    ? 'border-2 border-amber-600 dark:border-amber-500 bg-amber-50/40 dark:bg-amber-950/30 shadow-xs'
                    : 'border-zinc-200/80 dark:border-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-700 bg-zinc-50/30 dark:bg-zinc-900/30'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className={`text-[11px] font-semibold ${currentSection === 'unresolved' ? 'text-amber-700 dark:text-amber-300' : 'text-zinc-600 dark:text-zinc-400'}`}>
                    Chưa thống nhất
                  </span>
                  {currentSection === 'unresolved' && (
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-600 dark:bg-amber-400" />
                  )}
                </div>
                <div className="text-xl sm:text-2xl font-bold text-amber-600 dark:text-amber-400 mt-1 tabular-nums">
                  {viewModel.unresolved.length}
                </div>
              </button>

              {/* 4. Vướng mắc (Issues) */}
              <button
                type="button"
                onClick={() => handleSelectSection('issues')}
                className={`p-3 rounded-xl border text-left transition-all cursor-pointer ${
                  currentSection === 'issues'
                    ? 'border-2 border-fuchsia-600 dark:border-fuchsia-500 bg-fuchsia-50/40 dark:bg-fuchsia-950/30 shadow-xs'
                    : 'border-zinc-200/80 dark:border-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-700 bg-zinc-50/30 dark:bg-zinc-900/30'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className={`text-[11px] font-semibold ${currentSection === 'issues' ? 'text-fuchsia-700 dark:text-fuchsia-300' : 'text-zinc-600 dark:text-zinc-400'}`}>
                    Vướng mắc
                  </span>
                  {currentSection === 'issues' && (
                    <span className="w-1.5 h-1.5 rounded-full bg-fuchsia-600 dark:bg-fuchsia-400" />
                  )}
                </div>
                <div className="text-xl sm:text-2xl font-bold text-fuchsia-600 dark:text-fuchsia-400 mt-1 tabular-nums">
                  {openIssuesCount}
                </div>
              </button>
            </div>
          </div>
        </div>

        {/* ── 3. DANH SÁCH CHI TIẾT TƯƠNG ỨNG VỚI KHỐI ĐƯỢC CHỌN ─── */}
        <div className="flex-1">
          {/* PHẦN 1: QUYẾT ĐỊNH */}
          {currentSection === 'decisions' && (
            <div className="space-y-3">
              {confirmedDecisions.length === 0 ? (
                <div className="p-8 text-center bg-white dark:bg-[#121217] rounded-xl border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-500">
                  Không có quyết định nào được xác lập trong cuộc họp.
                </div>
              ) : (
                confirmedDecisions.map((decision) => {
                  const isExpanded = expandedDecisionIds.has(decision.id);
                  const firstEvidence = decision.evidence?.[0];

                  return (
                    <div
                      key={decision.id}
                      className="bg-white dark:bg-[#121217] border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 shadow-xs border-l-[3px] border-l-indigo-600 dark:border-l-indigo-500 transition-all"
                    >
                      {/* Collapsed Header */}
                      <div
                        onClick={() => {
                          setExpandedDecisionIds((prev) => {
                            const next = new Set(prev);
                            if (next.has(decision.id)) next.delete(decision.id);
                            else next.add(decision.id);
                            return next;
                          });
                        }}
                        className="flex items-start justify-between gap-3 cursor-pointer select-none"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 mb-1 flex-wrap">
                            <span className="font-semibold text-xs text-indigo-600 dark:text-indigo-400">
                              {decision.topic || 'Quyết định'}
                            </span>

                            {decision.needs_review && (
                              <span
                                className="px-2 py-0.2 rounded-full text-[10px] font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 border border-zinc-200 dark:border-zinc-700"
                                title="Bằng chứng cần được đối soát lại"
                              >
                                Cần kiểm tra
                              </span>
                            )}
                          </div>

                          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 leading-snug">
                            {decision.content}
                          </h3>

                          {/* One meta line */}
                          <div className="flex items-center gap-2 text-[11px] text-zinc-500 dark:text-zinc-400 mt-1">
                            {decision.proposed_by && (
                              <span>Đề xuất: {decision.proposed_by}</span>
                            )}
                            {decision.proposed_by && decision.confirmed_by && (
                              <span>·</span>
                            )}
                            {decision.confirmed_by && (
                              <span>Đồng thuận: {decision.confirmed_by}</span>
                            )}
                          </div>
                        </div>

                        <ChevronDown
                          size={15}
                          className={`text-zinc-400 mt-1 transition-transform duration-150 ${
                            isExpanded ? 'rotate-180' : ''
                          }`}
                        />
                      </div>

                      {/* In-place Expansion: Details, Trail, Evidence */}
                      {isExpanded && (
                        <div className="mt-3 pt-3 border-t border-zinc-100 dark:border-zinc-800 space-y-3">
                          {decision.condition && (
                            <div className="text-xs text-zinc-600 dark:text-zinc-400 bg-zinc-50 dark:bg-zinc-900 p-2.5 rounded-lg border border-zinc-100 dark:border-zinc-800">
                              <span className="font-semibold text-zinc-800 dark:text-zinc-200">Điều kiện kèm theo: </span>
                              <span>{decision.condition}</span>
                            </div>
                          )}

                          {/* Decision Trail */}
                          <DecisionTrail
                            history={decision.history}
                            topic={decision.topic}
                            onViewEvidence={(ev, title) =>
                              handleOpenEvidence(ev, title, 'decision', 'Quyết định')
                            }
                          />

                          {/* Single Evidence Button */}
                          {firstEvidence && (
                            <div className="pt-2 flex justify-end">
                              <button
                                type="button"
                                onClick={() =>
                                  handleOpenEvidence(
                                    decision.evidence || firstEvidence,
                                    `Quyết định: ${decision.topic || decision.content}`,
                                    'decision',
                                    'Quyết định'
                                  )
                                }
                                className="px-3 py-1.5 rounded-lg text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-950/40 border border-indigo-200 dark:border-indigo-900/60 transition-colors flex items-center gap-1.5 cursor-pointer"
                              >
                                <MessageSquareQuote size={13} />
                                <span>Xem bằng chứng</span>
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          )}

          {/* PHẦN 2: VIỆC CẦN LÀM (TỐI GIẢN, HIỆN ĐẠI, 1 NÚT TRÒN ĐẦU HÀNG, MENU BA CHẤM, CHẾ ĐỘ CHỌN) */}
          {currentSection === 'todos' && (
            <div className="space-y-3">
              {/* Header điều khiển: Số lượng việc + Nút "+ Thêm việc" + Nút "Chọn" */}
              <div className="flex items-center justify-between gap-3 text-xs">
                <div className="text-zinc-500 dark:text-zinc-400 font-medium">
                  {displayTasks.length} việc cần làm
                  {taskAssigneeFilter !== 'all' && ` (giao cho ${taskAssigneeFilter})`}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      if (isSelectMode) {
                        setIsSelectMode(false);
                        setSelectedTaskIds(new Set());
                      } else {
                        setIsSelectMode(true);
                      }
                    }}
                    className={`px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer border ${
                      isSelectMode
                        ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 border-transparent'
                        : 'border-zinc-200 dark:border-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800'
                    }`}
                  >
                    {isSelectMode ? 'Xong' : 'Chọn'}
                  </button>

                  <button
                    type="button"
                    onClick={() => setShowInlineTaskCreate(!showInlineTaskCreate)}
                    className="px-2.5 py-1.5 rounded-lg text-xs font-medium bg-emerald-600 hover:bg-emerald-700 text-white transition-colors flex items-center gap-1 cursor-pointer"
                  >
                    <Plus size={13} />
                    <span>Thêm việc</span>
                  </button>
                </div>
              </div>

              {/* Form Thêm việc nội tuyến */}
              {showInlineTaskCreate && (
                <form
                  onSubmit={handleCreateInlineTask}
                  className="p-3.5 bg-white dark:bg-[#121217] border border-emerald-300 dark:border-emerald-800/80 rounded-xl shadow-xs space-y-2.5"
                >
                  <input
                    value={newTaskTitle}
                    onChange={(e) => setNewTaskTitle(e.target.value)}
                    placeholder="Nội dung việc cần làm..."
                    className="w-full px-3 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 outline-none focus:border-emerald-500"
                    autoFocus
                  />

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    <input
                      value={newTaskAssignee}
                      onChange={(e) => setNewTaskAssignee(e.target.value)}
                      placeholder="Người phụ trách (VD: Tuấn, Lan...)"
                      className="w-full px-3 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 outline-none focus:border-emerald-500"
                    />
                    <input
                      type="date"
                      value={newTaskDate}
                      onChange={(e) => setNewTaskDate(e.target.value)}
                      className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 outline-none focus:border-emerald-500 cursor-pointer"
                    />
                    <input
                      type="time"
                      value={newTaskTime}
                      onChange={(e) => setNewTaskTime(e.target.value)}
                      className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 outline-none focus:border-emerald-500 cursor-pointer"
                    />
                  </div>

                  {(newTaskDate || newTaskTime) && (
                    <div className="text-[11px] text-zinc-500">
                      Hạn chót: <span className="font-semibold text-emerald-700 dark:text-emerald-400">{formatDeadlineToDisplay(newTaskDate, newTaskTime)}</span>
                    </div>
                  )}

                  <div className="flex items-center justify-end gap-2 pt-1">
                    <button
                      type="button"
                      onClick={() => setShowInlineTaskCreate(false)}
                      className="px-3 py-1 text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 cursor-pointer"
                    >
                      Hủy
                    </button>
                    <button
                      type="submit"
                      disabled={!newTaskTitle.trim()}
                      className="px-3.5 py-1 text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg cursor-pointer disabled:opacity-50"
                    >
                      Lưu việc
                    </button>
                  </div>
                </form>
              )}

              {/* Danh sách Task: Mỗi task là 1 hàng gọn, nút tròn đầu hàng, menu 3 chấm cuối hàng */}
              {displayTasks.length === 0 ? (
                <div className="p-8 text-center bg-white dark:bg-[#121217] rounded-xl border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-500">
                  {taskAssigneeFilter !== 'all'
                    ? `Không có việc nào được giao cho ${taskAssigneeFilter}.`
                    : 'Tất cả công việc đã hoàn thành!'}
                </div>
              ) : (
                <div className="space-y-1.5">
                  {displayTasks.map((task) => {
                    const isExiting = exitingTaskIds.has(task.id);
                    const isSelected = selectedTaskIds.has(task.id);
                    const warning = getDeadlineWarning(task.deadline_iso, false);
                    const isMenuOpen = activeMenuTaskId === task.id;

                    return (
                      <div
                        key={task.id}
                        onClick={() => {
                          if (isSelectMode) {
                            setSelectedTaskIds((prev) => {
                              const next = new Set(prev);
                              if (next.has(task.id)) next.delete(task.id);
                              else next.add(task.id);
                              return next;
                            });
                          } else {
                            setDetailModalTask(task);
                          }
                        }}
                        className={`group px-3 py-2.5 rounded-lg border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-[#121217] hover:border-zinc-300 dark:hover:border-zinc-700 shadow-2xs flex items-center gap-3 transition-all cursor-pointer ${
                          isExiting ? 'row-exit-animate' : ''
                        } ${isSelected ? 'ring-1 ring-emerald-500 bg-emerald-50/20 dark:bg-emerald-950/20' : ''}`}
                      >
                        {/* 1. NÚT TRÒN HOÀN THÀNH (HOẶC CHECKBOX KHI Ở CHẾ ĐỘ CHỌN) */}
                        {isSelectMode ? (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedTaskIds((prev) => {
                                const next = new Set(prev);
                                if (next.has(task.id)) next.delete(task.id);
                                else next.add(task.id);
                                return next;
                              });
                            }}
                            className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 cursor-pointer ${
                              isSelected
                                ? 'bg-emerald-600 border-emerald-600 text-white'
                                : 'border-zinc-300 dark:border-zinc-600 hover:border-zinc-400'
                            }`}
                          >
                            {isSelected && <Check size={11} className="stroke-[3]" />}
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleToggleTaskStatus(task);
                            }}
                            className="w-4 h-4 rounded-full border border-zinc-300 dark:border-zinc-600 hover:border-emerald-600 dark:hover:border-emerald-400 flex items-center justify-center shrink-0 cursor-pointer transition-colors"
                            title="Đánh dấu hoàn thành"
                          />
                        )}

                        {/* 2. TÊN CÔNG VIỆC */}
                        <div className="flex-1 min-w-0 flex items-center gap-2">
                          <span className="text-xs sm:text-[13px] font-medium text-zinc-900 dark:text-zinc-100 truncate">
                            {task.title}
                          </span>
                        </div>

                        {/* 3. NGƯỜI PHỤ TRÁCH */}
                        {task.assignee && (
                          <span className="hidden sm:inline-flex items-center gap-1 text-[11px] text-zinc-500 dark:text-zinc-400 shrink-0">
                            <User size={11} className="text-zinc-400" />
                            <span>{task.assignee}</span>
                          </span>
                        )}

                        {/* 4. HẠN CHÓT & CẢNH BÁO */}
                        {task.deadline_raw && (
                          <span className="hidden md:inline-flex items-center gap-1 text-[11px] text-zinc-400 dark:text-zinc-500 shrink-0">
                            <Clock size={11} />
                            <span>{task.deadline_raw}</span>
                          </span>
                        )}

                        {/* Overdue/Near-due Warning (chỉ hiển thị đỏ khi cảnh báo) */}
                        {warning?.isWarning && (
                          <span className="badge-overdue text-[10px] px-2 py-0.2 rounded-full font-semibold flex items-center gap-1 shrink-0">
                            <AlertTriangle size={10} />
                            <span>{warning.label}</span>
                          </span>
                        )}

                        {/* 5. NÚT BA CHẤM DUY NHẤT (CHỨA CÁC THAO TÁC ÍT DÙNG) */}
                        <div className="relative shrink-0" data-task-menu>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setActiveMenuTaskId(isMenuOpen ? null : task.id);
                            }}
                            className="p-1 rounded text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
                            title="Tùy chọn thao tác"
                          >
                            <MoreHorizontal size={14} />
                          </button>

                          {/* Popover Menu của nút 3 chấm */}
                          {isMenuOpen && (
                            <div className="absolute right-0 top-full mt-1 w-40 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-lg p-1 z-50 text-xs animate-in fade-in duration-100">
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setActiveMenuTaskId(null);
                                  openEditTaskModal(task);
                                }}
                                className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 flex items-center gap-2 cursor-pointer"
                              >
                                <Pencil size={12} />
                                <span>Chỉnh sửa việc</span>
                              </button>

                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setActiveMenuTaskId(null);
                                  handleDeleteTask(task);
                                }}
                                className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/40 text-red-600 dark:text-red-400 flex items-center gap-2 cursor-pointer"
                              >
                                <Trash2 size={12} />
                                <span>Xóa việc</span>
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Danh sách việc đã hoàn thành */}
              {completedTasks.length > 0 && (
                <div className="mt-5 pt-3 border-t border-zinc-200 dark:border-zinc-800">
                  <div className="text-xs font-semibold text-zinc-400 dark:text-zinc-500 mb-2">
                    Đã hoàn thành ({completedTasks.length})
                  </div>
                  <div className="space-y-1.5">
                    {completedTasks.map((task) => (
                      <div
                        key={task.id}
                        className="px-3 py-2 rounded-lg border border-zinc-200/50 dark:border-zinc-800/50 bg-zinc-50/50 dark:bg-zinc-900/30 flex items-center justify-between gap-3 text-xs opacity-65 hover:opacity-100 transition-opacity"
                      >
                        <div className="flex items-center gap-2.5 min-w-0 flex-1">
                          {/* Nút tròn hoàn thành */}
                          <button
                            type="button"
                            onClick={() => handleToggleTaskStatus(task)}
                            className="w-4 h-4 rounded-full bg-zinc-300 dark:bg-zinc-600 text-white flex items-center justify-center shrink-0 cursor-pointer"
                            title="Đánh dấu chưa hoàn thành"
                          >
                            <Check size={10} className="stroke-[3]" />
                          </button>
                          <span className="line-through text-zinc-500 dark:text-zinc-400 truncate">
                            {task.title}
                          </span>
                        </div>
                        <span className="text-[11px] text-zinc-400 shrink-0">
                          {task.assignee || ''}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Thanh công cụ thao tác hàng loạt khi chọn ít nhất 1 task */}
              {isSelectMode && selectedTaskIds.size > 0 && (
                <div className="fixed bottom-16 md:bottom-6 left-1/2 -translate-x-1/2 z-40 bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 px-4 py-2.5 rounded-xl shadow-xl flex items-center gap-3 text-xs animate-in fade-in slide-in-from-bottom-2 duration-150 border border-zinc-700 dark:border-zinc-300">
                  <span className="font-semibold">{selectedTaskIds.size} việc đã chọn</span>
                  <div className="w-px h-4 bg-zinc-700 dark:bg-zinc-300" />
                  <button
                    type="button"
                    onClick={handleToggleSelectAll}
                    className="hover:underline cursor-pointer font-medium"
                  >
                    {selectedTaskIds.size === displayTasks.length ? 'Bỏ chọn hết' : 'Chọn tất cả'}
                  </button>
                  <button
                    type="button"
                    onClick={handleBulkComplete}
                    className="text-emerald-400 dark:text-emerald-600 hover:underline cursor-pointer font-medium"
                  >
                    Đánh dấu hoàn thành
                  </button>
                  <button
                    type="button"
                    onClick={handleBulkDelete}
                    className="text-red-400 dark:text-red-600 hover:underline cursor-pointer font-medium"
                  >
                    Xóa
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedTaskIds(new Set());
                      setIsSelectMode(false);
                    }}
                    className="text-zinc-400 dark:text-zinc-600 hover:underline cursor-pointer"
                  >
                    Hủy
                  </button>
                </div>
              )}
            </div>
          )}

          {/* PHẦN 3: CHƯA THỐNG NHẤT (UNRESOLVED) - NÚT "THÊM VIỆC" HOẠT ĐỘNG CHUẨN XÁC */}
          {currentSection === 'unresolved' && (
            <div className="space-y-4">
              {viewModel.unresolved.length === 0 ? (
                <div className="p-8 text-center bg-white dark:bg-[#121217] rounded-xl border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-500">
                  Không có nội dung nào chưa thống nhất trong cuộc họp.
                </div>
              ) : (
                <>
                  {/* Nhóm 1: Việc chưa ai nhận (unconfirmed_task) */}
                  {viewModel.unresolved.filter((u) => u.kind === 'unconfirmed_task').length > 0 && (
                    <div className="space-y-2.5">
                      <div className="text-xs font-bold text-amber-700 dark:text-amber-400 uppercase tracking-wide">
                        Việc chưa ai nhận
                      </div>
                      {viewModel.unresolved
                        .filter((u) => u.kind === 'unconfirmed_task')
                        .map((item) => (
                          <div
                            key={item.id}
                            className="bg-white dark:bg-[#121217] border border-zinc-200 dark:border-zinc-800 rounded-xl p-3.5 shadow-xs border-l-[3px] border-l-amber-600 dark:border-l-amber-500 space-y-2"
                          >
                            <div className="text-xs sm:text-[13px] font-semibold text-zinc-900 dark:text-zinc-100 leading-snug">
                              {item.content}
                            </div>

                            {item.reason_unresolved && (
                              <div className="text-[11px] text-zinc-500 dark:text-zinc-400">
                                Lý do: {item.reason_unresolved}
                              </div>
                            )}

                            <div className="flex items-center justify-between gap-2 pt-1 flex-wrap text-xs">
                              {item.suggested_assignee && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
                                  <span>Gợi ý: {item.suggested_assignee}</span>
                                </span>
                              )}

                              <div className="flex items-center gap-2 ml-auto">
                                {item.evidence && item.evidence.length > 0 && (
                                  <button
                                    type="button"
                                    onClick={() =>
                                      handleOpenEvidence(item.evidence, item.content, 'unresolved', 'Chưa thống nhất')
                                    }
                                    className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 text-xs font-medium cursor-pointer"
                                  >
                                    Xem bằng chứng
                                  </button>
                                )}

                                <button
                                  type="button"
                                  onClick={() => handleOpenConvertModal(item)}
                                  className="px-2.5 py-1 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-medium text-xs flex items-center gap-1 cursor-pointer transition-colors shadow-2xs"
                                >
                                  <Plus size={11} />
                                  <span>Thêm việc</span>
                                </button>
                              </div>
                            </div>
                          </div>
                        ))}
                    </div>
                  )}

                  {/* Nhóm 2: Nội dung chưa chốt (open_decision) */}
                  {viewModel.unresolved.filter((u) => u.kind !== 'unconfirmed_task').length > 0 && (
                    <div className="space-y-2.5">
                      <div className="text-xs font-bold text-amber-700 dark:text-amber-400 uppercase tracking-wide">
                        Nội dung chưa chốt
                      </div>
                      {viewModel.unresolved
                        .filter((u) => u.kind !== 'unconfirmed_task')
                        .map((item) => (
                          <div
                            key={item.id}
                            className="bg-white dark:bg-[#121217] border border-zinc-200 dark:border-zinc-800 rounded-xl p-3.5 shadow-xs border-l-[3px] border-l-amber-600 dark:border-l-amber-500 space-y-2"
                          >
                            <div className="text-xs sm:text-[13px] font-semibold text-zinc-900 dark:text-zinc-100 leading-snug">
                              {item.content}
                            </div>

                            {item.reason_unresolved && (
                              <div className="text-[11px] text-zinc-500 dark:text-zinc-400">
                                Lý do: {item.reason_unresolved}
                              </div>
                            )}

                            <div className="flex items-center justify-end gap-2 pt-1 text-xs">
                              {item.evidence && item.evidence.length > 0 && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    handleOpenEvidence(item.evidence, item.content, 'unresolved', 'Chưa thống nhất')
                                  }
                                  className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 text-xs font-medium cursor-pointer"
                                >
                                  Xem bằng chứng
                                </button>
                              )}

                              <button
                                type="button"
                                onClick={() => handleOpenConvertModal(item)}
                                className="px-2.5 py-1 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-medium text-xs flex items-center gap-1 cursor-pointer transition-colors shadow-2xs"
                              >
                                <Plus size={11} />
                                <span>Thêm việc</span>
                              </button>
                            </div>
                          </div>
                        ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* PHẦN 4: VƯỚNG MẮC (ISSUES) */}
          {currentSection === 'issues' && (
            <SectionErrorBoundary
              fallbackTitle="Không thể tải danh sách vướng mắc"
              fallbackMessage="Đã xảy ra lỗi khi hiển thị mục vướng mắc. Bạn có thể bấm Thử lại để tải lại nội dung."
            >
              <div className="space-y-3">
                {/* Phân đoạn: 'Còn tồn tại' | 'Đã xử lý' */}
                <div className="flex items-center justify-between gap-3 text-xs">
                  <div className="inline-flex p-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-800">
                    <button
                      type="button"
                      onClick={() => setIssueFilter('open')}
                      className={`px-3 py-1 rounded-md font-medium transition-colors cursor-pointer ${
                        issueFilter === 'open'
                          ? 'bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                          : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
                      }`}
                    >
                      Còn tồn tại ({openIssuesCount})
                    </button>
                    <button
                      type="button"
                      onClick={() => setIssueFilter('resolved')}
                      className={`px-3 py-1 rounded-md font-medium transition-colors cursor-pointer ${
                        issueFilter === 'resolved'
                          ? 'bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                          : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
                      }`}
                    >
                      Đã xử lý ({Math.max(0, (viewModel.issues || []).length - openIssuesCount)})
                    </button>
                  </div>
                </div>

                {(viewModel.issues || []).filter((i) => i.status === issueFilter).length === 0 ? (
                  <div className="p-8 text-center bg-white dark:bg-[#121217] rounded-xl border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-500">
                    {issueFilter === 'open'
                      ? 'Không có vướng mắc nào đang tồn đọng!'
                      : 'Chưa có vướng mắc nào được đánh dấu giải quyết.'}
                  </div>
              ) : (
                viewModel.issues
                  .filter((i) => i.status === issueFilter)
                  .map((issue) => (
                    <div
                      key={issue.id}
                      className="bg-white dark:bg-[#121217] border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 shadow-xs border-l-[3px] border-l-fuchsia-600 dark:border-l-fuchsia-500 space-y-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <h3 className="text-xs sm:text-[13px] font-semibold text-zinc-900 dark:text-zinc-100 leading-snug">
                            {issue.content}
                          </h3>

                          {issue.owner && (
                            <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-1">
                              Phụ trách: {issue.owner}
                            </div>
                          )}
                        </div>

                        <button
                          type="button"
                          onClick={() => handleToggleIssueStatus(issue)}
                          className={`px-2.5 py-1 rounded-lg text-xs font-medium cursor-pointer transition-colors shrink-0 ${
                            issue.status === 'resolved'
                              ? 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400 hover:bg-zinc-200'
                              : 'bg-fuchsia-50 text-fuchsia-700 dark:bg-fuchsia-950 dark:text-fuchsia-300 hover:bg-fuchsia-100'
                          }`}
                        >
                          {issue.status === 'resolved' ? 'Mở lại' : 'Đánh dấu giải quyết'}
                        </button>
                      </div>

                      {issue.evidence && issue.evidence.length > 0 && (
                        <div className="flex items-center gap-2 pt-1 text-xs">
                          <button
                            type="button"
                            onClick={() =>
                              handleOpenEvidence(issue.evidence, issue.content, 'issue', 'Vướng mắc')
                            }
                            className="text-fuchsia-600 dark:text-fuchsia-400 hover:underline cursor-pointer font-medium"
                          >
                            Xem bằng chứng
                          </button>
                        </div>
                      )}

                      {/* In-place Issue Notes */}
                      <SectionErrorBoundary
                        fallbackTitle="Không thể tải danh sách ghi chú"
                        fallbackMessage="Đã xảy ra lỗi khi tải ghi chú cho vấn đề này. Bạn có thể bấm Thử lại."
                      >
                        <IssueNotes
                          issueId={issue.id}
                          notes={issue.notes ?? viewModel.issue_notes ?? []}
                          onAddNote={(content, authorId, authorName) => {
                            const res = applyIssueNote(overlay, issue.id, {
                              authorId,
                              authorName,
                              content,
                            });
                            updateOverlay(res.overlay);
                          }}
                          onEditNote={(noteId, newContent) => {
                            const next = applyEditIssueNote(overlay, noteId, newContent);
                            updateOverlay(next);
                          }}
                          onDeleteNote={(noteId) => {
                            const previous = overlay;
                            const next = applyDeleteIssueNote(overlay, noteId);
                            updateOverlay(next);
                            toast('Đã xóa ghi chú', {
                              action: {
                                label: 'Hoàn tác',
                                onClick: () => updateOverlay(previous),
                              },
                            });
                          }}
                        />
                      </SectionErrorBoundary>
                    </div>
                  ))
              )}
            </div>
          </SectionErrorBoundary>
        )}
        </div>
      </main>

      {/* ── 4. MODAL XEM CHI TIẾT CÔNG VIỆC KHI NHẤP VÀO HÀNG ─── */}
      {detailModalTask && (
        <div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in duration-150"
          onClick={() => setDetailModalTask(null)}
        >
          <div
            className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl p-5 max-w-md w-full shadow-xl space-y-3.5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                  Chi tiết việc cần làm
                </span>
                <h3 className="text-sm sm:text-base font-bold text-zinc-900 dark:text-zinc-100 mt-1 leading-snug">
                  {detailModalTask.title}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setDetailModalTask(null)}
                className="p-1 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 cursor-pointer rounded-lg"
              >
                <X size={15} />
              </button>
            </div>

            <div className="space-y-2 text-xs bg-zinc-50 dark:bg-zinc-950 p-3 rounded-xl border border-zinc-100 dark:border-zinc-800">
              <div className="flex items-center justify-between">
                <span className="text-zinc-500">Người phụ trách:</span>
                <span className="font-semibold text-zinc-800 dark:text-zinc-200">
                  {detailModalTask.assignee || 'Chưa giao'}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-zinc-500">Hạn chót:</span>
                <span className="font-semibold text-zinc-800 dark:text-zinc-200">
                  {detailModalTask.deadline_raw || 'Chưa đặt hạn chót'}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-zinc-500">Trạng thái:</span>
                <span className="font-semibold text-zinc-800 dark:text-zinc-200">
                  {detailModalTask.status === 'done' ? 'Đã hoàn thành' : 'Đang xử lý'}
                </span>
              </div>
            </div>

            {/* Action buttons at bottom: Dẫn chứng and Sửa việc */}
            <div className="pt-2 flex items-center gap-2 border-t border-zinc-100 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => {
                  const task = detailModalTask;
                  setDetailModalTask(null);
                  handleOpenEvidence(
                    task.evidence && task.evidence.length > 0 ? task.evidence : [],
                    task.title,
                    'task',
                    'Việc cần làm'
                  );
                }}
                className="flex-1 py-2 px-3 text-xs font-semibold text-emerald-700 dark:text-emerald-300 bg-emerald-50 hover:bg-emerald-100 dark:bg-emerald-950/50 dark:hover:bg-emerald-900/50 rounded-xl border border-emerald-200 dark:border-emerald-800 transition-colors flex items-center justify-center gap-1.5 cursor-pointer"
                title="Xem dẫn chứng trong biên bản"
              >
                <MessageSquareQuote size={13} />
                <span>Dẫn chứng</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  const task = detailModalTask;
                  setDetailModalTask(null);
                  openEditTaskModal(task);
                }}
                className="flex-1 py-2 px-3 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 rounded-xl transition-colors flex items-center justify-center gap-1.5 cursor-pointer shadow-xs"
                title="Chỉnh sửa việc cần làm"
              >
                <Pencil size={13} />
                <span>Sửa việc</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 5. MODAL CHỈNH SỬA CÔNG VIỆC ──────── */}
      {editingTask && (
        <div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in duration-150"
          onClick={() => setEditingTask(null)}
        >
          <form
            onSubmit={handleSaveEditTask}
            className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl p-5 max-w-md w-full shadow-xl space-y-3.5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-1">
              <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-900 dark:text-zinc-100">
                Chỉnh sửa việc cần làm
              </h4>
              <button
                type="button"
                onClick={() => setEditingTask(null)}
                className="p-1 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 cursor-pointer rounded-lg"
              >
                <X size={14} />
              </button>
            </div>

            <div>
              <label className="block text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                Tên công việc
              </label>
              <textarea
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                rows={2}
                className="w-full px-3 py-2 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 outline-none focus:border-emerald-500 resize-none leading-relaxed"
                autoFocus
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                Người phụ trách
              </label>
              <input
                value={editAssignee}
                onChange={(e) => setEditAssignee(e.target.value)}
                placeholder="VD: Tuấn, Team DevOps..."
                className="w-full px-3 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 outline-none focus:border-emerald-500"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                  Ngày hết hạn (Lịch)
                </label>
                <input
                  type="date"
                  value={editDate}
                  onChange={(e) => setEditDate(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 outline-none focus:border-emerald-500 cursor-pointer"
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                  Giờ hết hạn
                </label>
                <input
                  type="time"
                  value={editTime}
                  onChange={(e) => setEditTime(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 outline-none focus:border-emerald-500 cursor-pointer"
                />
              </div>
            </div>

            {(editDate || editTime) && (
              <div className="text-[11px] text-zinc-500 bg-emerald-50/50 dark:bg-emerald-950/20 px-2.5 py-1.5 rounded-lg border border-emerald-200/60 dark:border-emerald-900/40">
                <span>Hạn chót hiển thị: </span>
                <span className="font-semibold text-emerald-800 dark:text-emerald-300">
                  {formatDeadlineToDisplay(editDate, editTime)}
                </span>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-zinc-100 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setEditingTask(null)}
                className="px-3 py-1.5 text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 cursor-pointer"
              >
                Hủy
              </button>
              <button
                type="submit"
                disabled={!editTitle.trim()}
                className="px-4 py-1.5 text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg cursor-pointer disabled:opacity-50 transition-colors shadow-xs"
              >
                Lưu thay đổi
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── 6. MODAL THÊM VÀO VIỆC CẦN LÀM TỪ CHƯA THỐNG NHẤT ─── */}
      {convertModalItem && (
        <div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in duration-150"
          onClick={() => setConvertModalItem(null)}
        >
          <form
            onSubmit={handleSaveConvertUnresolved}
            className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl p-5 max-w-md w-full shadow-xl space-y-3.5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400">
                  Thêm vào việc cần làm
                </span>
                <p className="text-xs text-zinc-500 mt-0.5">
                  Chuyển nội dung chưa thống nhất thành công việc cụ thể
                </p>
              </div>
              <button
                type="button"
                onClick={() => setConvertModalItem(null)}
                className="p-1 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 cursor-pointer rounded-lg"
              >
                <X size={15} />
              </button>
            </div>

            <div>
              <label className="block text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                Tên công việc
              </label>
              <textarea
                value={convertTitle}
                onChange={(e) => setConvertTitle(e.target.value)}
                rows={2}
                className="w-full px-3 py-2 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 outline-none focus:border-amber-500 resize-none leading-relaxed"
                autoFocus
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                Người phụ trách
              </label>
              <input
                value={convertAssignee}
                onChange={(e) => setConvertAssignee(e.target.value)}
                placeholder="VD: Tuấn, Team DevOps..."
                className="w-full px-3 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 outline-none focus:border-amber-500"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                  Ngày hết hạn (Lịch)
                </label>
                <input
                  type="date"
                  value={convertDate}
                  onChange={(e) => setConvertDate(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 outline-none focus:border-amber-500 cursor-pointer"
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                  Giờ hết hạn
                </label>
                <input
                  type="time"
                  value={convertTime}
                  onChange={(e) => setConvertTime(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 outline-none focus:border-amber-500 cursor-pointer"
                />
              </div>
            </div>

            {(convertDate || convertTime) && (
              <div className="text-[11px] text-zinc-500 bg-amber-50/50 dark:bg-amber-950/20 px-2.5 py-1.5 rounded-lg border border-amber-200/60 dark:border-amber-900/40">
                <span>Hạn chót hiển thị: </span>
                <span className="font-semibold text-amber-800 dark:text-amber-300">
                  {formatDeadlineToDisplay(convertDate, convertTime)}
                </span>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-zinc-100 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setConvertModalItem(null)}
                className="px-3 py-1.5 text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 cursor-pointer"
              >
                Hủy
              </button>
              <button
                type="submit"
                disabled={!convertTitle.trim()}
                className="px-4 py-1.5 text-xs font-semibold bg-amber-600 hover:bg-amber-700 text-white rounded-lg cursor-pointer disabled:opacity-50 transition-colors shadow-xs"
              >
                Lưu việc
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── 6. MOBILE BOTTOM NAVIGATION (<768px) ───────────────── */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-white/95 dark:bg-[#121217]/95 backdrop-blur-md border-t border-zinc-200 dark:border-zinc-800 grid grid-cols-4 h-14">
        <button
          type="button"
          onClick={() => handleSelectSection('decisions')}
          className={`flex flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition-colors cursor-pointer ${
            currentSection === 'decisions'
              ? 'text-indigo-600 dark:text-indigo-400 font-bold'
              : 'text-zinc-500 dark:text-zinc-400'
          }`}
        >
          <span>Quyết định</span>
          <span className="text-[9px] tabular-nums">({confirmedDecisions.length})</span>
        </button>

        <button
          type="button"
          onClick={() => handleSelectSection('todos')}
          className={`flex flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition-colors cursor-pointer ${
            currentSection === 'todos'
              ? 'text-emerald-600 dark:text-emerald-400 font-bold'
              : 'text-zinc-500 dark:text-zinc-400'
          }`}
        >
          <div className="flex items-center gap-1">
            <span>Việc làm</span>
            {urgentTasksCount > 0 && <span className="w-1.5 h-1.5 rounded-full bg-red-600" />}
          </div>
          <span className="text-[9px] tabular-nums">({activeTasks.length})</span>
        </button>

        <button
          type="button"
          onClick={() => handleSelectSection('unresolved')}
          className={`flex flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition-colors cursor-pointer ${
            currentSection === 'unresolved'
              ? 'text-amber-600 dark:text-amber-400 font-bold'
              : 'text-zinc-500 dark:text-zinc-400'
          }`}
        >
          <span>Chưa thống nhất</span>
          <span className="text-[9px] tabular-nums">({viewModel.unresolved.length})</span>
        </button>

        <button
          type="button"
          onClick={() => handleSelectSection('issues')}
          className={`flex flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition-colors cursor-pointer ${
            currentSection === 'issues'
              ? 'text-fuchsia-600 dark:text-fuchsia-400 font-bold'
              : 'text-zinc-500 dark:text-zinc-400'
          }`}
        >
          <span>Vướng mắc</span>
          <span className="text-[9px] tabular-nums">({openIssuesCount})</span>
        </button>
      </nav>

      {/* ── 7. KHUNG ĐỐI CHIẾU BIÊN BẢN (EVIDENCE REVIEW) ───────── */}
      <TranscriptPanel
        isOpen={transcriptPanelOpen}
        onClose={() => setTranscriptPanelOpen(false)}
        transcript={transcript}
        activeEvidence={activeEvidence}
      />
    </div>
  );
}