import { useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAccount } from '@/app/AuthContext';
import { Badge, HomeStats } from '@/components/ui';
import { ask } from '@/services/ask';
import { ATTENTION, CAMERA_ONLINE, CAMERA_TOTAL, RECENT, SUGGESTED_QUESTIONS, TODAY_STATS } from '@/services/mockData';
import type { ToolId } from '@/types';

export function Home() {
  const account = useAccount();
  const navigate = useNavigate();
  const [question, setQuestion] = useState('');
  const [note, setNote] = useState('');

  const firstName = account.name.split(' ')[0];
  const statusLine =
    CAMERA_ONLINE === CAMERA_TOTAL
      ? `Campus is calm · ${CAMERA_TOTAL} cameras`
      : `${CAMERA_ONLINE} of ${CAMERA_TOTAL} cameras up`;

  function open(tool: ToolId) {
    navigate(`/tool/${tool}`, { state: { autoRun: true } });
  }

  function submit(text: string) {
    const outcome = ask(text);
    if (outcome.kind === 'route') {
      setNote('');
      open(outcome.tool);
    } else if (outcome.kind === 'note') {
      setNote(outcome.message);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') submit(question);
  }

  return (
    <div className="screen">
      <div className="mob-header">
        <div className="mob-header__brand">
          <div
            style={{
              width: 30,
              height: 30,
              borderRadius: 10,
              background: 'var(--ac)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <div style={{ width: 13, height: 13, borderRadius: '50% 50% 50% 4px', background: 'var(--bg)' }} />
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 14.5, lineHeight: 1.15 }}>VisionGuard AI</div>
            <div style={{ fontSize: 11, color: 'var(--tx3)' }}>{statusLine}</div>
          </div>
        </div>
        <button type="button" className="mob-avatar" onClick={() => navigate('/account')}>
          {account.initials}
        </button>
      </div>

      <div style={{ fontWeight: 700, fontSize: 25, letterSpacing: '-.02em', lineHeight: 1.2 }}>
        Good morning, {firstName}.
        <br />
        What do you need to know?
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          background: 'var(--card)',
          borderRadius: 16,
          padding: '0 6px 0 16px',
          height: 54,
          boxShadow: 'var(--sh)',
          margin: '16px 0 12px',
        }}
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask in plain words…"
          aria-label="Ask a question"
          style={{ flex: 1, minWidth: 0, border: 'none', background: 'transparent', fontSize: 15, color: 'var(--tx)', outline: 'none' }}
        />
        <button type="button" className="btn" style={{ width: 'auto', height: 42, padding: '0 18px', borderRadius: 12, fontSize: 14.5 }} onClick={() => submit(question)}>
          Ask
        </button>
      </div>

      {note && (
        <div style={{ fontSize: 13, color: 'var(--am)', background: 'var(--am-bg)', padding: '9px 13px', borderRadius: 11, marginBottom: 12 }}>
          {note}
        </div>
      )}

      <div className="chip-row" style={{ marginBottom: 26 }}>
        {SUGGESTED_QUESTIONS.map((c) => (
          <button key={c.q} type="button" className="chip" onClick={() => submit(c.q)}>
            {c.q}
          </button>
        ))}
      </div>

      <div className="section-title">Needs your attention</div>
      <div className="stack" style={{ marginBottom: 26 }}>
        {ATTENTION.map((item) => (
          <button key={item.id} type="button" className="card" style={{ textAlign: 'left', border: 'none', cursor: 'pointer' }} onClick={() => open(item.tool)}>
            <div style={{ marginBottom: 9 }}>
              <Badge tone={item.tone} icon={item.icon}>
                {item.kind}
              </Badge>
            </div>
            <div style={{ fontWeight: 600, fontSize: 14.5, lineHeight: 1.3 }}>{item.title}</div>
            <div style={{ fontSize: 12.5, color: 'var(--tx3)', margin: '3px 0 10px' }}>{item.sub}</div>
            <span style={{ fontWeight: 600, fontSize: 13.5, color: 'var(--ac)' }}>{item.action} →</span>
          </button>
        ))}
      </div>

      <div className="section-title">Campus today</div>
      <div style={{ marginBottom: 26 }}>
        <HomeStats items={TODAY_STATS} />
      </div>

      <div className="section-title">Pick up where you left off</div>
      <div className="stack">
        {RECENT.map((r) => (
          <button key={r.id} type="button" className="card row row--pressable" style={{ padding: '15px 16px' }} onClick={() => open(r.tool)}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="row__name">{r.title}</div>
              <div className="row__sub">{r.sub}</div>
            </div>
            <span className="row__chevron">›</span>
          </button>
        ))}
      </div>
    </div>
  );
}
