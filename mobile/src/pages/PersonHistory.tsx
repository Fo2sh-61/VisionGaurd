import { useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { Badge, Stats } from '@/components/ui';
import { getHistory } from '@/services/api';
import type { PersonHistory as PersonHistoryData } from '@/types';

export function PersonHistory() {
  const { name = '' } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as { from?: 'people' | 'group'; groupName?: string } | null;
  const [history, setHistory] = useState<PersonHistoryData | null>(null);

  useEffect(() => {
    void getHistory(decodeURIComponent(name)).then(setHistory);
  }, [name]);

  if (!history) return null;

  const backTo = state?.from === 'group' && state.groupName ? `/people/groups/${encodeURIComponent(state.groupName)}` : '/people';

  return (
    <div className="screen">
      <div className="tool-header" style={{ padding: 0 }}>
        <button type="button" className="tool-header__back" onClick={() => navigate(backTo)}>
          ‹
        </button>
        <div className="tool-header__title">{history.name}</div>
      </div>
      <p className="screen__lead" style={{ marginTop: 10 }}>
        {history.sub} · attendance this term
      </p>

      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ fontWeight: 700, fontSize: 21, letterSpacing: '-.02em', lineHeight: 1.2 }}>{history.heading}</div>
        <div style={{ fontSize: 13, color: 'var(--tx2)', marginTop: 3, lineHeight: 1.4 }}>{history.lead}</div>
        <div style={{ marginTop: 16 }}>
          <Stats items={history.stats} />
        </div>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ fontWeight: 700, fontSize: 14.5, marginBottom: 12 }}>Arrival times, last 10 school days</div>
        <div className="stack" style={{ gap: 9 }}>
          {history.bars.map((bar) => (
            <div key={bar.day} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 46, fontSize: 12, color: 'var(--tx2)', flexShrink: 0 }}>{bar.day}</span>
              <div className="bar-track">
                <div
                  className="bar-fill"
                  style={{ width: `${bar.pct}%`, background: bar.tone === 'bad' ? 'var(--rd)' : bar.tone === 'warn' ? 'var(--am)' : 'var(--ac)' }}
                />
              </div>
              <span
                style={{
                  width: 56,
                  textAlign: 'right',
                  fontSize: 12,
                  fontWeight: 600,
                  flexShrink: 0,
                  color: bar.tone === 'bad' ? 'var(--rd)' : bar.tone === 'warn' ? 'var(--am)' : 'var(--ac)',
                }}
              >
                {bar.label}
              </span>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 12, lineHeight: 1.4 }}>
          Bar length is how late in the morning they arrived. Amber is after the 8:00am cut-off, red is an absence.
        </div>
      </div>

      <div className="card" style={{ padding: '4px 18px' }}>
        <div style={{ padding: '14px 0 4px', fontWeight: 700, fontSize: 14.5 }}>Days that needed follow-up</div>
        {history.flags.map((f) => (
          <div key={f.date} className="row" style={{ borderTop: '1px solid var(--line)', borderBottom: 'none' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="row__name">{f.date}</div>
              <div className="row__sub">{f.detail}</div>
            </div>
            <Badge tone={f.tone}>{f.badge}</Badge>
          </div>
        ))}
      </div>
    </div>
  );
}
