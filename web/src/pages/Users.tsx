import { useState } from 'react';
import {
  Badge, Card, CardHeader, DataNotice, Empty, Field, LoadError, PageHeader, Select, Toggle,
} from '@/components/ui';
import { getUsers, unlockUser, updateUser } from '@/services/api';
import { ApiError } from '@/services/http';
import { useLanguage, useT } from '@/app/LanguageContext';
import { CAPABILITIES } from '@/services/content';
import type { MessageKey } from '@/i18n';
import type { Role, User, UserChanges } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';

const NO_USERS: User[] = [];

export function Users() {
  const t = useT();
  const { language } = useLanguage();
  const capability = useCapability('users');
  const { data: users, error, loading, reload } = useAsync(() => getUsers(language), [language], NO_USERS);
  const [editing, setEditing] = useState<string | null>(null);

  // "0 people can sign in" is a claim, and we can only make it when the
  // engine actually answered with none. While loading, or after a failure,
  // the honest header is the one that counts nothing.
  const counted = !loading && !error;

  return (
    <>
      <DataNotice capability={capability} />
      <LoadError error={error} onRetry={reload} what="load.accountList" />
      <PageHeader title={t('users.title')} lead={t('users.lead')} />

      <Card>
        <CardHeader
          title={counted
            ? t('users.canSignIn', { count: users.filter((u) => !u.disabled).length })
            : t('users.whoCanSignIn')}
          sub={t('users.adminsOnly')}
        />

        {loading && <Empty>{t('users.loadingAccounts')}</Empty>}
        {counted && users.length === 0 && (
          <Empty>{t('users.none')}</Empty>
        )}

        {users.map((user) => (
          <div key={user.id}>
            <div
              className="row"
              style={{ gridTemplateColumns: '1.2fr .7fr 1.6fr .9fr .5fr' }}
            >
              <span className="row__name">{user.name}</span>
              <span style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <Badge tone={user.role === 'admin' ? 'good' : 'neutral'}>
                  {t(user.role === 'admin' ? 'role.admin' : 'role.it')}
                </Badge>
                {user.disabled && <Badge tone="warn">{t('users.disabled')}</Badge>}
                {user.lockedUntil && (
                  <>
                    <Badge tone="warn">{user.lockedUntil}</Badge>
                    <UnlockButton user={user} onDone={reload} />
                  </>
                )}
              </span>
              <span
                className="row__muted"
                style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}
              >
                {user.email}
              </span>
              <span className="row__muted">{user.lastActive}</span>
              <button
                type="button"
                className="linkbtn"
                aria-expanded={editing === user.id}
                onClick={() => setEditing(editing === user.id ? null : user.id)}
              >
                {t('users.edit')}
              </button>
            </div>
            {editing === user.id && (
              <EditAccount
                user={user}
                onDone={() => {
                  setEditing(null);
                  reload();
                }}
                onCancel={() => setEditing(null)}
              />
            )}
          </div>
        ))}

        <div className="section-title" style={{ marginTop: 22, marginBottom: 10 }}>
          {t('users.roleWhatEachCanDo')}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr .6fr .6fr', fontSize: 13.5 }}>
          <span className="row--head">{t('users.capabilityHead')}</span>
          <span className="row--head">{t('users.adminHead')}</span>
          <span className="row--head">{t('users.itHead')}</span>

          {CAPABILITIES.map((row) => (
            <Capability key={row.capability} {...row} />
          ))}
        </div>
      </Card>
    </>
  );
}

/** Lift a sign-in lock now (spec 020). The engine audits it; a refusal or an
 *  unreachable engine is said in place, never shown as unlocked. */
function UnlockButton({ user, onDone }: { user: User; onDone: () => void }) {
  const t = useT();
  const { language } = useLanguage();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function unlock() {
    setBusy(true);
    setProblem(null);
    try {
      await unlockUser(user.id, language);
      onDone();
    } catch (err) {
      setProblem(
        err instanceof ApiError && err.offline
          ? t('users.notSavedOffline')
          : t('users.notUnlocked', { reason: err instanceof Error ? err.message : String(err) }),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className="linkbtn" disabled={busy} onClick={() => void unlock()}>
        {busy ? t('users.unlocking') : t('users.unlock')}
      </button>
      {problem && <span role="alert" style={{ color: 'var(--rd)', fontSize: 13 }}>{problem}</span>}
    </>
  );
}

const ROLES: readonly Role[] = ['admin', 'it'];

/** Name, role and whether the account can sign in. Only what changed is sent.
 *
 *  The engine decides: a change that would leave no active administrator
 *  comes back 409 with its reason, which is shown as it is. Nothing here
 *  claims a save the engine did not make. */
function EditAccount({
  user,
  onDone,
  onCancel,
}: {
  user: User;
  onDone: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const { language } = useLanguage();
  const [name, setName] = useState(user.name);
  const [role, setRole] = useState<Role>(user.role);
  const [active, setActive] = useState(!user.disabled);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const changes: UserChanges = {};
  if (name.trim() !== user.name) changes.name = name.trim();
  if (role !== user.role) changes.role = role;
  if (active === user.disabled) changes.disabled = !active;
  const changed = Object.keys(changes).length > 0;

  async function save() {
    setSaving(true);
    setProblem(null);
    try {
      await updateUser(user.id, changes, language);
      onDone();
    } catch (err) {
      setProblem(
        err instanceof ApiError && err.offline
          ? t('users.notSavedOffline')
          : t('users.notSaved', { reason: err instanceof Error ? err.message : String(err) }),
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ padding: '14px 0 18px', borderTop: '1px solid var(--line)' }}>
      <div className="section-title" style={{ marginBottom: 10 }}>
        {t('users.editTitle', { name: user.name })}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr .8fr .8fr', gap: 14, alignItems: 'end' }}>
        <Field label={t('users.name')}>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t('users.role')}>
          <Select
            value={role}
            onChange={(v) => setRole(v as Role)}
            options={ROLES}
            label={(o) => t(o === 'admin' ? 'role.admin' : 'role.it')}
          />
        </Field>
        <Field label={t('users.canSignInToggle')}>
          <Toggle on={active} onToggle={() => setActive(!active)} label={t('users.canSignInToggle')} />
        </Field>
      </div>
      {problem && (
        <div role="alert" style={{ color: 'var(--rd)', fontSize: 13.5, marginTop: 10 }}>{problem}</div>
      )}
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <button
          type="button"
          className={`chip-btn ${changed && name.trim() ? 'chip-btn--on' : 'chip-btn--off'}`}
          disabled={!changed || !name.trim() || saving}
          onClick={() => void save()}
        >
          {saving ? t('users.saving') : t('users.save')}
        </button>
        <button type="button" className="chip-btn chip-btn--off" onClick={onCancel}>
          {t('action.cancel')}
        </button>
      </div>
    </div>
  );
}

function Capability({
  capability,
  admin,
  it,
}: {
  capability: MessageKey;
  admin: boolean;
  it: boolean;
}) {
  const t = useT();
  const cell = { padding: '9px 0', borderTop: '1px solid var(--line)' } as const;
  const yes = { ...cell, color: 'var(--ac2)', fontWeight: 600 } as const;
  const no = { ...cell, color: 'var(--tx3)' } as const;

  return (
    <>
      <span style={cell}>{t(capability)}</span>
      <span style={admin ? yes : no}>{t(admin ? 'common.yes' : 'common.no')}</span>
      <span style={it ? yes : no}>{t(it ? 'common.yes' : 'common.no')}</span>
    </>
  );
}
