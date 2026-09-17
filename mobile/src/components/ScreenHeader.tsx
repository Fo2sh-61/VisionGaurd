import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useT } from '@/app/LanguageContext';
import { Icon } from './Icon';

/** The header of every screen below a tab: a way back, and what this is
 *  (spec 015, P13-FR-044).
 *
 *  Back goes to the screen this one was opened from. When there is none in
 *  this visit - the browser reloaded a discarded tab, or a link opened the app
 *  straight here - it goes to the screen's parent instead, never out of the
 *  app. React Router numbers its own history entries in `history.state.idx`;
 *  zero means this is the first. */
export function ScreenHeader({
  title,
  parent,
  action,
}: {
  title: string;
  parent: string;
  action?: ReactNode;
}) {
  const t = useT();
  const navigate = useNavigate();

  function back() {
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    if (idx > 0) navigate(-1);
    else navigate(parent, { replace: true });
  }

  return (
    <header className="screenhead">
      <button type="button" className="iconbtn" aria-label={t('phone.back')} onClick={back}>
        <Icon name="back" size={22} strokeWidth={2} mirror />
      </button>
      <h1 className="screenhead__title">{title}</h1>
      {action && <div className="screenhead__action">{action}</div>}
    </header>
  );
}
