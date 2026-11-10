import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from 'react';
import { Toast } from '@/components/ui';
import type { Tone } from '@/types';

/** The confirmation after a save, dismissal or acknowledgement (spec 022,
 *  FR-108). Console only. It is for success: a failure stays on the page as
 *  an inline notice, where the person can read the reason and retry. */

const SHOW_MS = 4000;

interface ToastValue {
  show: (text: string, tone?: Tone) => void;
}

const ToastContext = createContext<ToastValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ id: number; text: string; tone: Tone } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const counter = useRef(0);

  const show = useCallback((text: string, tone: Tone = 'good') => {
    if (timer.current) clearTimeout(timer.current);
    counter.current += 1;
    setToast({ id: counter.current, text, tone });
    timer.current = setTimeout(() => setToast(null), SHOW_MS);
  }, []);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const value = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {toast && <Toast key={toast.id} text={toast.text} tone={toast.tone} />}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}
