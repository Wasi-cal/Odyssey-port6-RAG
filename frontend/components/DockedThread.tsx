'use client';

import { MessageBubble } from './MessageBubble';
import type { Message } from '@/lib/types';

interface DockedThreadProps {
  messages: Message[];
  citeSources: boolean;
  onOpenSource: (doc?: string) => void;
}

export function DockedThread({ messages, citeSources, onOpenSource }: DockedThreadProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto pb-3 pt-7">
      {messages.map((m, i) => (
        <MessageBubble key={i} message={m} citeSources={citeSources} onOpenSource={onOpenSource} />
      ))}
    </div>
  );
}
