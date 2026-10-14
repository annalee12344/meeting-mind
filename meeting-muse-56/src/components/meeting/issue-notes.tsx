import React, { useState } from 'react';
import {
  MessageSquare,
  Send,
  Pencil,
  Trash2,
  Check,
  X,
  User,
} from 'lucide-react';
import type { IssueNote } from '@/lib/types.generated';
import { canEditNote, canDeleteNote, useUserIdentity } from '@/lib/identity';

interface IssueNotesProps {
  issueId: string;
  notes?: IssueNote[];
  onAddNote: (content: string, authorId: string, authorName: string) => void;
  onEditNote: (noteId: string, newContent: string) => void;
  onDeleteNote: (noteId: string) => void;
}

export function IssueNotes({
  issueId,
  notes = [],
  onAddNote,
  onEditNote,
  onDeleteNote,
}: IssueNotesProps) {
  const { identity, clientId, displayName, isIdentified, updateDisplayName } = useUserIdentity();
  const [newContent, setNewContent] = useState('');
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [showInlineNamePrompt, setShowInlineNamePrompt] = useState(false);
  const [tempName, setTempName] = useState('');

  const safeNotes = Array.isArray(notes) ? notes : [];
  const issueNotes = safeNotes.filter((n) => n && (n.issue_id === issueId || !n.issue_id));

  const handleStartSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newContent.trim()) return;

    if (!isIdentified) {
      setShowInlineNamePrompt(true);
      return;
    }

    if (clientId && displayName) {
      onAddNote(newContent.trim(), clientId, displayName);
      setNewContent('');
    }
  };

  const handleConfirmName = (e: React.FormEvent) => {
    e.preventDefault();
    if (!tempName.trim()) return;
    const saved = updateDisplayName(tempName.trim());
    setShowInlineNamePrompt(false);
    if (newContent.trim()) {
      onAddNote(newContent.trim(), saved.clientId, saved.displayName);
      setNewContent('');
    }
  };

  const handleStartEdit = (note: IssueNote) => {
    setEditingNoteId(note.id);
    setEditContent(note.content);
  };

  const handleSaveEdit = (noteId: string) => {
    if (!editContent.trim()) return;
    onEditNote(noteId, editContent.trim());
    setEditingNoteId(null);
  };

  return (
    <div className="mt-3 pt-3 border-t border-zinc-100 dark:border-zinc-800 space-y-2.5">
      <div className="flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400">
        <div className="flex items-center gap-1.5 font-semibold text-zinc-700 dark:text-zinc-300">
          <MessageSquare size={13} className="text-fuchsia-600 dark:text-fuchsia-400" />
          <span>Ghi chú thảo luận ({issueNotes.length})</span>
        </div>
        {displayName && (
          <span className="text-[11px] text-zinc-400 dark:text-zinc-500">
            Tác giả: <strong className="text-zinc-700 dark:text-zinc-300 font-medium">{displayName}</strong>
          </span>
        )}
      </div>

      {/* Notes list */}
      {issueNotes.length > 0 && (
        <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
          {issueNotes.map((note) => {
            const isAuthor = canEditNote(note.author_id, clientId);
            const isEditing = editingNoteId === note.id;
            const isEdited = note.updated_at && note.created_at && note.updated_at !== note.created_at;
            const formattedDate = new Date(note.created_at).toLocaleTimeString('vi-VN', {
              hour: '2-digit',
              minute: '2-digit',
              day: '2-digit',
              month: '2-digit',
            });

            const initial = note.author_name ? note.author_name.trim().charAt(0).toUpperCase() : '?';

            return (
              <div
                key={note.id}
                className={`p-2.5 rounded-lg border text-xs group transition-colors ${
                  isAuthor
                    ? 'bg-fuchsia-50/25 dark:bg-fuchsia-950/20 border-fuchsia-200/60 dark:border-fuchsia-900/40'
                    : 'bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800'
                }`}
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <div className="flex items-center gap-1.5">
                    <span className="w-4 h-4 rounded-full bg-zinc-200 dark:bg-zinc-700 text-zinc-700 dark:text-zinc-300 flex items-center justify-center text-[9px] font-bold">
                      {initial}
                    </span>
                    <span className="font-semibold text-zinc-800 dark:text-zinc-200 text-[11px]">{note.author_name}</span>
                    {isAuthor && (
                      <span className="text-[9px] font-medium px-1.5 py-0.2 rounded bg-fuchsia-100 text-fuchsia-800 dark:bg-fuchsia-950 dark:text-fuchsia-300">
                        Bạn
                      </span>
                    )}
                    <span className="text-[10px] text-zinc-400 dark:text-zinc-500">{formattedDate}</span>
                    {isEdited && (
                      <span className="text-[10px] italic text-zinc-400 dark:text-zinc-500">(đã chỉnh sửa)</span>
                    )}
                  </div>

                  {/* Actions for Author ONLY on hover */}
                  {isAuthor && !isEditing && (
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        type="button"
                        onClick={() => handleStartEdit(note)}
                        className="p-1 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded transition-colors cursor-pointer"
                        title="Sửa ghi chú"
                      >
                        <Pencil size={11} />
                      </button>
                      <button
                        type="button"
                        onClick={() => onDeleteNote(note.id)}
                        className="p-1 text-zinc-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40 rounded transition-colors cursor-pointer"
                        title="Xóa ghi chú"
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>
                  )}
                </div>

                {isEditing ? (
                  <div className="mt-1.5 flex items-center gap-1.5">
                    <input
                      value={editContent}
                      onChange={(e) => setEditContent(e.target.value)}
                      className="flex-1 px-2.5 py-1 text-xs border border-fuchsia-300 dark:border-fuchsia-700 rounded-lg outline-none bg-white dark:bg-zinc-950 text-zinc-800 dark:text-zinc-200"
                      autoFocus
                    />
                    <button
                      type="button"
                      onClick={() => handleSaveEdit(note.id)}
                      className="p-1.5 bg-fuchsia-600 hover:bg-fuchsia-700 text-white rounded-lg cursor-pointer"
                      title="Lưu thay đổi"
                    >
                      <Check size={12} />
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingNoteId(null)}
                      className="p-1.5 bg-zinc-200 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 rounded-lg hover:bg-zinc-300 dark:hover:bg-zinc-700 cursor-pointer"
                      title="Hủy"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ) : (
                  <p className="text-zinc-800 dark:text-zinc-200 text-xs leading-relaxed break-words">
                    {note.content}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Inline author setup prompt directly above compose box for first-time authors (no modal) */}
      {showInlineNamePrompt && !isIdentified && (
        <form
          onSubmit={handleConfirmName}
          className="p-2.5 rounded-lg border border-fuchsia-200 dark:border-fuchsia-900/60 bg-fuchsia-50/40 dark:bg-fuchsia-950/30 flex flex-col sm:flex-row items-stretch sm:items-center gap-2 text-xs"
        >
          <div className="flex items-center gap-1.5 text-zinc-700 dark:text-zinc-300 shrink-0 font-medium">
            <User size={13} className="text-fuchsia-600 dark:text-fuchsia-400" />
            <span>Tên hiển thị của bạn:</span>
          </div>
          <input
            value={tempName}
            onChange={(e) => setTempName(e.target.value)}
            placeholder="VD: Tuấn (Backend), Lan (QA)..."
            className="flex-1 px-2.5 py-1 rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-xs text-zinc-800 dark:text-zinc-200 outline-none focus:border-fuchsia-500"
            autoFocus
          />
          <div className="flex items-center justify-end gap-1.5">
            <button
              type="button"
              onClick={() => setShowInlineNamePrompt(false)}
              className="px-2.5 py-1 text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 cursor-pointer"
            >
              Hủy
            </button>
            <button
              type="submit"
              disabled={!tempName.trim()}
              className="px-3 py-1 bg-fuchsia-600 hover:bg-fuchsia-700 text-white font-medium rounded-md cursor-pointer disabled:opacity-50"
            >
              Lưu tên
            </button>
          </div>
        </form>
      )}

      {/* Note input form */}
      <form onSubmit={handleStartSubmit} className="flex items-center gap-1.5">
        <input
          value={newContent}
          onChange={(e) => setNewContent(e.target.value)}
          placeholder={
            isIdentified
              ? `Thêm ghi chú với tư cách ${displayName}...`
              : 'Nhập ghi chú ý kiến cho vấn đề này...'
          }
          className="flex-1 px-3 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 text-zinc-800 dark:text-zinc-200 outline-none focus:border-fuchsia-500 focus:ring-1 focus:ring-fuchsia-500/20 transition-all"
        />
        <button
          type="submit"
          disabled={!newContent.trim()}
          className={`px-3 py-1.5 rounded-lg font-medium text-xs transition-colors flex items-center gap-1 cursor-pointer ${
            newContent.trim()
              ? 'bg-fuchsia-600 hover:bg-fuchsia-700 text-white'
              : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-600 cursor-not-allowed'
          }`}
        >
          <Send size={11} />
          <span>Gửi</span>
        </button>
      </form>
    </div>
  );
}

