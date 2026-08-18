import { useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAccount } from '@/app/AuthContext';
import { homeTools, pathFor } from '@/app/navigation';
import { Badge } from '@/components/ui';
import { ask } from '@/services/ask';
import { SUGGESTED_QUESTIONS } from '@/services/content';
import { useAttention } from '@/app/useAttention';
import type { ToolId } from '@/types';

export function Home() {
  const account = useAccount();
  const navigate = useNavigate();
  const [question, setQuestion] = useState('');
  const [note, setNote] = useState('');

  const firstName = account.name.split(' ')[0];
  const attention = useAttention();
  const tools = homeTools();

  function open(tool: ToolId, autoRun = true) {
    navigate(pathFor(tool), { state: { autoRun } });
  }

  async function submit(text: string) {
    // An empty box is the commonest way to press this button by accident.
    // Saying so beats routing nowhere and looking broken.
    if (!text.trim()) {
      setNote('Type a question first — or tap one of the examples.');
      return;
    }
    const outcome = await ask(text, account.role);
    if (outcome.kind === 'route') {
      setNote('');
      open(outcome.tool);
    } else if (outcome.kind === 'note') {
      setNote(outcome.message);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') void submit(question);
  }

  return (
    <>
      <h1 style={{ fontWeight: 700, fontSize: 29, letterSpacing: '-.02em', margin: 0 }}>
        Good morning, {firstName}.
      </h1>
      <p style={{ fontSize: 15, color: 'var(--tx2)', marginTop: 5 }}>
        Ask in plain words — I’ll open the right tool.
      </p>

      <div style={{ display: 'flex', gap: 10, margin: '24px 0 12px', maxWidth: 700 }}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="e.g. Who was absent today?"
          aria-label="Ask a question"
          style={{
            flex: 1,
            height: 56,
            border: 'none',
            borderRadius: 14,
            padding: '0 20px',
            fontSize: 15.5,
            background: 'var(--card)',
            color: 'var(--tx)',
            outline: 'none',
            boxShadow: 'var(--sh)',
          }}
        />
        <button
          type="button"
          className="btn"
          style={{ height: 56, borderRadius: 14, padding: '0 26px', fontSize: 15 }}
          onClick={() => void submit(question)}
        >
          Ask
        </button>
      </div>

      {note && (
        <div
          style={{
            fontSize: 13.5,
            color: 'var(--am)',
            background: 'var(--am-bg)',
            display: 'inline-block',
            padding: '8px 14px',
            borderRadius: 10,
            marginBottom: 12,
          }}
        >
          {note}
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 42 }}>
        {SUGGESTED_QUESTIONS.map((q) => (
          <button
            type="button"
            key={q}
            onClick={() => {
              setQuestion(q);
              void submit(q);
            }}
            style={{
              padding: '7px 14px',
              borderRadius: 10,
              fontSize: 13,
              color: 'var(--ac2)',
              background: 'var(--chip)',
              fontWeight: 500,
              border: 'none',
              cursor: 'pointer',
            }}
          >
            {q}
          </button>
        ))}
      </div>

      <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 12 }}>
        Needs your attention{' '}
        <span style={{ fontWeight: 500, color: 'var(--tx3)', fontSize: 13.5 }}>
          · {attention.length} items, that’s all
        </span>
      </div>
      <div className="grid-2" style={{ marginBottom: 42 }}>
        {attention.map((item) => (
          <div
            key={item.id}
            style={{
              background: 'var(--card)',
              borderRadius: 14,
              padding: 18,
              boxShadow: 'var(--sh)',
            }}
          >
            <div style={{ marginBottom: 10 }}>
              <Badge tone={item.tone} icon={item.icon}>
                {item.kind}
              </Badge>
            </div>
            <div style={{ fontWeight: 600, fontSize: 14.5 }}>{item.title}</div>
            <div style={{ fontSize: 13, color: 'var(--tx3)', margin: '3px 0 12px' }}>
              {item.sub}
            </div>
            <button type="button" className="linkbtn" onClick={() => open(item.to)}>
              {item.action} →
            </button>
          </div>
        ))}
      </div>

      <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 12 }}>Tools</div>
      <div className="grid-4" style={{ marginBottom: 0 }}>
        {tools.map((tool) => (
          <button
            type="button"
            key={tool.id}
            onClick={() => open(tool.id, false)}
            style={{
              background: 'var(--card)',
              borderRadius: 12,
              padding: 15,
              boxShadow: 'var(--sh)',
              border: 'none',
              cursor: 'pointer',
              textAlign: 'left',
              color: 'var(--tx)',
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 13.5 }}>{tool.label}</div>
            <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 2 }}>{tool.blurb}</div>
          </button>
        ))}
      </div>
    </>
  );
}
