/**
 * Deadline Warning Calculation Utilities.
 * 
 * Replaces old regex-based heuristics with deterministic date math on ISO 8601 strings.
 * Rules:
 * 1. Warning triggered when overdue (past deadline) OR due within 48 hours.
 * 2. If deadline_iso is null or empty: display raw text with no warning flag (never guess).
 * 3. If task is already completed (isDone = true): no warning ever.
 * 4. Never convey status by color alone: includes icon key and descriptive text.
 */

export const NEAR_DUE_HOURS_THRESHOLD = 48;

export type DeadlineSeverity = 'overdue' | 'due_soon' | 'normal';

export interface DeadlineWarning {
  severity: DeadlineSeverity;
  isWarning: boolean; // true if overdue or due within 48h
  isOverdue: boolean;
  isDueSoon: boolean;
  hoursRemaining: number;
  label: string; // e.g., "Quá hạn 2 ngày", "Còn 18 giờ", "Hạn: 15/10"
  badgeClass: string;
}

/**
 * Calculates deadline warning status based on date math against current time.
 *
 * @param deadlineIso ISO 8601 date string, e.g. "2026-10-15" or "2026-10-15T18:00:00"
 * @param isDone Whether the task has already been completed
 * @param now Reference timestamp (defaults to current system time, injectable for testing)
 * @returns DeadlineWarning details, or null if no warning applies or date is unset
 */
export function getDeadlineWarning(
  deadlineIso: string | null | undefined,
  isDone: boolean = false,
  now: Date = new Date()
): DeadlineWarning | null {
  // Rule 3: No warning for completed tasks
  if (isDone) {
    return null;
  }

  // Rule 2: If deadline_iso is null/empty/invalid: no warning, do not guess
  if (!deadlineIso || typeof deadlineIso !== 'string') {
    return null;
  }

  const trimmed = deadlineIso.trim();
  if (!trimmed) {
    return null;
  }

  // Parse ISO date
  const deadlineDate = new Date(trimmed);
  if (isNaN(deadlineDate.getTime())) {
    return null;
  }

  // If input is date-only (e.g. "2026-10-15"), set deadline to end of that day (23:59:59)
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
    deadlineDate.setHours(23, 59, 59, 999);
  }

  const diffMs = deadlineDate.getTime() - now.getTime();
  const diffHours = diffMs / (1000 * 60 * 60);

  // Overdue
  if (diffMs < 0) {
    const overdueHours = Math.abs(diffHours);
    let label = 'Đã quá hạn';
    if (overdueHours >= 24) {
      const days = Math.floor(overdueHours / 24);
      label = `Quá hạn ${days} ngày`;
    } else {
      const hours = Math.max(1, Math.floor(overdueHours));
      label = `Quá hạn ${hours} giờ`;
    }

    return {
      severity: 'overdue',
      isWarning: true,
      isOverdue: true,
      isDueSoon: false,
      hoursRemaining: diffHours,
      label,
      badgeClass: 'bg-rose-50 text-rose-700 border-rose-200/80',
    };
  }

  // Due within 48h
  if (diffHours <= NEAR_DUE_HOURS_THRESHOLD) {
    let label = 'Sắp đến hạn';
    if (diffHours < 1) {
      label = 'Hạn trong 1 giờ';
    } else if (diffHours < 24) {
      const hours = Math.round(diffHours);
      label = `Còn ${hours} giờ`;
    } else {
      const days = Math.round(diffHours / 24);
      label = `Còn ${days} ngày`;
    }

    return {
      severity: 'due_soon',
      isWarning: true,
      isOverdue: false,
      isDueSoon: true,
      hoursRemaining: diffHours,
      label,
      badgeClass: 'bg-amber-50 text-amber-800 border-amber-200/80',
    };
  }

  // Normal deadline (more than 48 hours away)
  return {
    severity: 'normal',
    isWarning: false,
    isOverdue: false,
    isDueSoon: false,
    hoursRemaining: diffHours,
    label: `Hạn: ${deadlineDate.toLocaleDateString('vi-VN')}`,
    badgeClass: 'bg-slate-100 text-slate-700 border-slate-200/70',
  };
}
