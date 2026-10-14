# Meeting Mind — UI Audit Report: Remove / Merge / Keep

**Date:** 2026-10-14  
**Scope:** Interface redesign, visual hierarchy, interaction audit, typography, and motion review.  
**Objective:** Transform Meeting Mind into a calm, minimal, "smart", and highly focused tool adhering to the 7 core design principles:
1. Every element earns its place.
2. Progressive disclosure in place.
3. Direct manipulation & autosave.
4. Reversible beats confirm (Undo toasts).
5. Dismiss via outside click & Esc (no redundant visible X buttons on overlays).
6. Meaningful motion explaining state change.
7. Short Vietnamese microcopy without internal technical IDs.

---

## 1. UI Inventory: Remove / Merge / Keep Table

| Current UI Element | Location | Issue / Defect | Action | Proposed Replacement / Justification |
| :--- | :--- | :--- | :--- | :--- |
| **Mindy Mascot & Scanning Modal** | Home (`routes/index.tsx`), Header, Modal | Playful decorative mascot with colored blobs and spinning illustrations distracts from professional meeting analysis. | **REMOVE** | Replace with a calm, focused single card. Analysis state transforms inline within the card (4 steps: Chuẩn bị, Trích xuất, Đối chiếu, Kiểm chứng) with a quiet "Hủy" link. |
| **Hero Title & Multi-paragraph Intro** | Home | Cluttered heading with accent colors, period mark, and 3 paragraphs of value pitch. | **MERGE / SIMPLIFY** | Product title + one calm line of value text: "Trích xuất quyết định, việc cần làm, rào cản và đối soát bằng chứng từ biên bản cuộc họp." |
| **Separate Sample Selector & Dropdown Menu** | Home | A separate dropdown menu with 5 items alongside file upload buttons. | **MERGE** | Subtle horizontal sample chips directly under the card ("Thử với mẫu: Sprint 24, Thay đổi lịch, ..."). Clicking directly opens the instant verified result. |
| **Redundant "Nhập JSON" in Header** | Home & Header | Clutters the top navigation when results screen already has Export/Import. | **MERGE** | Consolidate into an overflow / secondary menu; primary landing page focuses 100% on pasting transcript or picking a sample. |
| **Duplicate "Đối chiếu" & "Chi tiết" Buttons** | All items in Workspace (`workspace.tsx`) | Items have separate buttons: one opens transcript, one expands details or opens a modal. | **MERGE** | Clicking anywhere on a card expands details in place (progressive disclosure). A single evidence icon button (`Quote` / `FileText`) opens the Transcript Sheet at the cited line. |
| **Internal IDs (`T001`, `D002`, `U012`, `A001`)** | Item headers, badges, tags | Technical identifiers confuse non-technical users and reveal pipeline internals. | **REMOVE** | Replace with natural contextual info: "Nam · dòng 12" or timestamp "09:12". |
| **Visible "X" Buttons on Overlays** | Transcript Sheet, Modals, Popovers | Users already expect to click outside (scrim) or hit `Esc` to dismiss overlays. | **REMOVE** | Remove visible X button from all dismissible overlays; retain visually-hidden button with `sr-only` for screen readers. Explicit button only for forms with unsaved input. |
| **Confirmation Dialogs for Delete** | Tasks Tab (Single delete & Bulk delete) | Modal popups interrupting flow: "Bạn có chắc chắn muốn xóa nhiệm vụ này?". | **REPLACE** | Instant direct soft-delete + Sonner Undo toast ("Đã xóa nhiệm vụ · Hoàn tác" for 6 seconds). |
| **Modal Dialog for "Thêm nhiệm vụ"** | Tasks Tab | Heavy modal popup with title, assignee, deadline inputs. | **REPLACE** | "+ Thêm việc" inserts an inline editable row at the top with title auto-focused. `Enter` saves, `Esc` cancels. |
| **Heavy Table Layout for Tasks** | Tasks Tab desktop view | Fixed-width table headers, borders, and rigid column structure look like a spreadsheet. | **REPLACE** | Clean desktop row list with flex alignment: `[checkbox] Title | assignee | deadline chip | evidence icon`, row actions on hover. Clean cards on mobile (<768px). |
| **Duplicate Red Status Colors & Badges** | Overview, Tasks, Issues | Red (#DC2626) is overused for labels, tags, and standard badges. | **RESTRICT** | Red is strictly reserved for Overdue / Due-in-48h warnings and system errors. Done tasks use muted gray with a checkmark. |
| **Redundant Tab Header inside Panel** | All 4 tabs | Tab panels repeat the tab label as an `<h2>` ("Quyết định quan trọng (Decisions)"). | **REMOVE** | The sticky 48px tab bar already clearly identifies the current view. Panel starts directly with a slim toolbar and list items. |
| **Unresolved Tab Clutter** | Unresolved Tab | Unorganized cards mixing unassigned tasks and open decisions without clear grouping. | **MERGE / GROUP** | Two distinct groups: "Việc chưa ai nhận" and "Nội dung chưa chốt". Unassigned task cards feature suggested assignee chip, date, and a "Chuyển thành việc" button that pulses Tasks counter. |
| **Modal Prompt for Note Author Name** | Issues Tab (`issue-notes.tsx`) | Pop-up modal asking for user's display name upon first comment. | **REPLACE** | Inline prompt directly above the comment compose box on first interaction. Autosaves to local identity. |
| **Static Non-interactive Stat Tiles** | Overview Card | Stat numbers are purely decorative and do not navigate to tabs. | **CONVERT** | 2x2 interactive button tiles (`count + label + status line`, e.g. "2 quá hạn", "1 cần kiểm tra"). Clicking immediately switches to that tab and scrolls to list top. |
| **Transcript Sheet Navigation** | Transcript Panel (`transcript-panel.tsx`) | Lacks multi-evidence pagination, focus trap, and return-to-trigger focus restoration. | **ENHANCE** | Right-side 480px sheet, light scrim, auto-scroll to centered line with 1.2s pulse, 2 lines before/after at full contrast with other lines dimmed. Multi-evidence shows "1/3" with prev/next controls. |

---

## 2. Design Token Specifications

- **Typography:** `"Be Vietnam Pro", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`.
  - Body: 16px / line-height 1.6
  - Item Title: 16px / font-weight 600
  - Metadata: 13px / muted text
  - Section Title: 20px / font-weight 700
  - Page Title: 24px / font-weight 700
  - Stat Numbers: 28px / font-weight 700 with `tabular-nums`
- **Neutrals (Zinc scale):**
  - Light mode: Background `#FAFAF9`, Card `#FFFFFF`, Border `#E4E4E7` (zinc-200), Text `#18181B` (zinc-900), Muted `#71717A` (zinc-500).
  - Dark mode: Background `#0B0B0F`, Card `#121217`, Border `#27272A` (zinc-800), Text `#F4F4F5` (zinc-100), Muted `#A1A1AA` (zinc-400).
- **Group Accent Colors (3px card left border, icons, 8% alpha badges):**
  - **Decisions:** `indigo-600` (`#4F46E5`, dark: `#818CF8`)
  - **Tasks:** `emerald-600` (`#059669`, dark: `#34D399`)
  - **Unresolved:** `amber-600` (`#D97706`, dark: `#FBBF24`)
  - **Issues:** `fuchsia-600` (`#C026D3`, dark: `#E879F9`)
- **Strict Color Rules:**
  - Red (`#DC2626`) is ONLY for Overdue / Due-within-48h and error banners.
  - Done state = muted gray with checkmark, never green.
- **Radii & Spacing Grid:**
  - Cards: `rounded-xl` (12px)
  - Controls & Buttons: `rounded-lg` (8px)
  - Chips & Pills: `rounded-full` (999px)
  - Spacing grid: 4px base (card padding 16px mobile, 20px desktop).
- **Motion:**
  - Durations: 150ms – 250ms ease-out.
  - Transitions strictly restricted to opacity, transform, and `grid-template-rows`.
  - `prefers-reduced-motion` fully respected.
