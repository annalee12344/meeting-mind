/**
 * Task utilities for cleaning task titles, separating assignees and deadlines,
 * and parsing date/time inputs.
 */

export interface CleanedTaskInfo {
  title: string;
  assignee: string | null;
  deadline_raw: string | null;
  deadline_iso: string | null;
  datePart: string; // YYYY-MM-DD or ''
  timePart: string; // HH:mm or ''
}

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Format date & time into display string: e.g. "10:00 ngày 21/10/2026"
 */
export function formatDeadlineToDisplay(datePart: string, timePart: string): string {
  const trimmedDate = datePart.trim();
  const trimmedTime = timePart.trim();

  if (!trimmedDate && !trimmedTime) return '';
  if (!trimmedDate && trimmedTime) return trimmedTime;

  // Format YYYY-MM-DD -> DD/MM/YYYY
  const parts = trimmedDate.split('-');
  const formattedDate =
    parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : trimmedDate;

  if (trimmedTime) {
    return `${trimmedTime} ngày ${formattedDate}`;
  }
  return `ngày ${formattedDate}`;
}

/**
 * Parses date & time from deadline strings or ISO.
 */
export function parseDateAndTime(
  deadlineRaw?: string | null,
  deadlineIso?: string | null,
  referenceYear: number = new Date().getFullYear()
): { datePart: string; timePart: string; iso: string | null; formattedRaw: string } {
  let datePart = '';
  let timePart = '';

  // 1. Try from ISO if valid
  if (deadlineIso && typeof deadlineIso === 'string') {
    const trimmedIso = deadlineIso.trim();
    const isoMatch = trimmedIso.match(/^(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?/);
    if (isoMatch) {
      datePart = isoMatch[1];
      if (isoMatch[2] && isoMatch[2] !== '23:59' && isoMatch[2] !== '00:00') {
        timePart = isoMatch[2];
      }
    }
  }

  // 2. Parse from deadlineRaw if date or time missing
  if (deadlineRaw && typeof deadlineRaw === 'string') {
    const text = deadlineRaw.trim();

    // Check time HH:mm
    if (!timePart) {
      const timeMatch = text.match(/\b([0-2]?\d:[0-5]\d)\b/);
      if (timeMatch) {
        const [h, m] = timeMatch[1].split(':');
        timePart = `${h.padStart(2, '0')}:${m}`;
      }
    }

    // Check date DD/MM or DD/MM/YYYY
    if (!datePart) {
      const dateMatch = text.match(/\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b/);
      if (dateMatch) {
        const day = dateMatch[1].padStart(2, '0');
        const month = dateMatch[2].padStart(2, '0');
        let year = dateMatch[3] ? parseInt(dateMatch[3], 10) : referenceYear;
        if (year < 100) year += 2000;
        datePart = `${year}-${month}-${day}`;
      }
    }
  }

  let iso: string | null = null;
  if (datePart) {
    iso = `${datePart}T${timePart ? timePart + ':00' : '23:59:59'}`;
  }

  const formattedRaw = formatDeadlineToDisplay(datePart, timePart) || deadlineRaw || '';

  return { datePart, timePart, iso, formattedRaw };
}

/**
 * Cleans task title by stripping out request/assignee prefixes and deadline phrases.
 * Pushes extracted assignee and deadline to their dedicated fields.
 */
export function cleanTaskFields(
  rawTitle: string,
  assignee?: string | null,
  deadlineRaw?: string | null,
  deadlineIso?: string | null,
  meetingDateStr?: string | null
): CleanedTaskInfo {
  let title = (rawTitle || '').trim();
  let finalAssignee = (assignee || '').trim() || null;
  let finalDeadlineRaw = (deadlineRaw || '').trim() || null;
  let finalDeadlineIso = (deadlineIso || '').trim() || null;

  // Determine reference year from meetingDateStr or fallback to 2026/current
  let referenceYear = 2026;
  if (meetingDateStr) {
    const yMatch = meetingDateStr.match(/\d{4}/);
    if (yMatch) referenceYear = parseInt(yMatch[0], 10);
  }

  // 1. EXTRACT AND STRIP DEADLINE FROM TITLE
  // Pattern: "trước 10:00 ngày 21/10", "trước 17:00", "trước ngày 21/10", "hạn chót 10:00 ngày 21/10", etc.
  const deadlineRegex =
    /\s*(?:,\s*)?(?:trước|hạn chót|deadline|trước lúc|vào lúc|hạn cuối)\s+([0-2]?\d:[0-5]\d(?:\s*(?:sáng|chiều|tối))?(?:\s*(?:ngày\s+)?\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)?|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|[0-2]?\d:[0-5]\d(?:\s*(?:sáng|chiều|tối))?)(.*)$/i;

  const dlMatch = title.match(deadlineRegex);
  if (dlMatch) {
    const matchedPhrase = dlMatch[0];
    const extractedTimeDate = dlMatch[1];
    const tailExtra = dlMatch[2] || '';

    // If tail has purposive clause (e.g. "để em test nhận callback IPN..."), keep the purposive clause!
    const purposeMatch = tailExtra.match(/\s+(để\s+.+)$/i);
    const purposeText = purposeMatch ? ' ' + purposeMatch[1].trim() : '';

    if (!finalDeadlineRaw) {
      finalDeadlineRaw = extractedTimeDate.trim();
    }

    // Cut out the deadline phrase from title, keep purpose if any
    title = title.substring(0, dlMatch.index).trim() + purposeText;
  }

  // 2. EXTRACT AND STRIP ASSIGNEE / REQUEST PREFIX FROM TITLE
  // e.g. "Nhờ team DevOps mở...", "Giao cho Lan viết...", "Yêu cầu team Data kiểm tra..."
  const prefixRegex =
    /^(?:Nhờ|Giao cho|Giao|Yêu cầu|Đề nghị|Phân công cho|Phân công)\s+(?:team\s+|nhóm\s+|bạn\s+|anh\s+|chị\s+|em\s+)?([\p{L}0-9_\s]+?)\s+(?=(?:mở|cấu hình|làm|tạo|viết|kiểm tra|review|fix|sửa|deploy|gửi|chuẩn bị|hỗ trợ|check|test|chuyển|tích hợp|thiết kế|setup|bổ sung|hoàn thành|thực hiện|cập nhật|xử lý)(?:\s|$))/iu;

  const prefixMatch = title.match(prefixRegex);
  if (prefixMatch) {
    const fullPrefix = prefixMatch[0];
    let extractedName = prefixMatch[1].trim();

    // If the original title was "Nhờ team DevOps", preserve "Team DevOps"
    if (fullPrefix.toLowerCase().includes('team ')) {
      extractedName = 'Team ' + extractedName.replace(/^team\s+/i, '');
    }

    if (!finalAssignee) {
      finalAssignee = extractedName;
    }

    // Strip prefix from title
    title = title.substring(fullPrefix.length).trim();
  } else if (finalAssignee) {
    // If assignee was already given (e.g. "Team DevOps"), check if title starts with "Nhờ Team DevOps "
    const assigneePattern = new RegExp(
      '^(?:Nhờ|Giao cho|Giao|Yêu cầu|Đề nghị|Phân công cho|Phân công)\\s+(?:team\\s+)?' +
        escapeRegex(finalAssignee.replace(/^team\s+/i, '')) +
        '\\s+',
      'iu'
    );
    title = title.replace(assigneePattern, '').trim();
  }

  // 3. CLEAN UP AND CAPITALIZE FIRST LETTER
  // Remove any leftover leading punctuation or conjunctions like "và"
  title = title.replace(/^[,;:\-\s]+/, '');
  if (title.length > 0) {
    title = title.charAt(0).toUpperCase() + title.slice(1);
  }

  // 4. PARSE DATE & TIME
  const { datePart, timePart, iso, formattedRaw } = parseDateAndTime(
    finalDeadlineRaw,
    finalDeadlineIso,
    referenceYear
  );

  return {
    title,
    assignee: finalAssignee,
    deadline_raw: formattedRaw || finalDeadlineRaw,
    deadline_iso: iso || finalDeadlineIso,
    datePart,
    timePart,
  };
}
