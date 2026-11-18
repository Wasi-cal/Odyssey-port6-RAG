'use client';

import { useEffect, useRef } from 'react';
import { MessageBubble } from './MessageBubble';
import type { Message } from '@/lib/types';

interface DockedThreadProps {
  messages: Message[];
  citeSources: boolean;
  onOpenSource: (doc?: string) => void;
}

// How close to the bottom (in px) counts as "at the bottom" for the
// stick-to-bottom heuristic below -- a few px of slack so sub-pixel
// scroll rounding never falsely reads as "the user scrolled away".
const BOTTOM_THRESHOLD_PX = 48;

/**
 * Message list -- owns its own scroll container and auto-scroll behavior
 * (bug fix: there was previously no scroll-to-bottom logic here at all, so
 * new messages/responses could render below the fold with no indication).
 * "Stick to bottom unless the user scrolled away to read history" is
 * implemented with a ref flag (stickToBottom) toggled by the container's
 * own onScroll handler, checked before every auto-scroll -- so a user who
 * has scrolled up to reread an earlier answer isn't yanked back down by a
 * new message arriving.
 */
export function DockedThread({ messages, citeSources, onOpenSource }: DockedThreadProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distanceFromBottom <= BOTTOM_THRESHOLD_PX;
  };

  // Runs after every render triggered by a messages change (new question,
  // new answer, or a whole conversation swapped in via selectHistoryItem)
  // -- scrollHeight is read only after the DOM has actually updated with
  // the new content, so this never scrolls based on the previous, shorter
  // layout (the stale-ref/too-early-effect failure mode this was fixing).
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    if (stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto pb-3 pt-7"
    >
      {messages.map((m, i) => (
        <MessageBubble key={i} message={m} citeSources={citeSources} onOpenSource={onOpenSource} />
      ))}
    </div>
  );
}
