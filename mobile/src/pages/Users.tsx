import { useState } from 'react';
import {
  Badge, Card, CardHeader, DataNotice, Empty, Field, LoadError, PageHeader, Select, Toggle,
} from '@/components/ui';
import { getUsers, updateUser } from '@/services/api';
import { ApiError } from '@/services/http';
import { useLanguage, useT } from '@/app/LanguageContext';
import { CAPABILITIES } from '@/services/content';
import type { MessageKey } from '@/i18n';
import type { Role, User, UserChanges } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';

const NO_USERS: User[] = [];

/** Accounts — who can sign in (spec 015, contracts/phone-screens.md
 *  "Accounts").
 *
 *  Built from `web/src/pages/Users.tsx`: the same call, the same "0 people
 *  can sign in" rule (a claim only made once the engine has actually
 *  answered), and the same role/capability matrix. Rearranged as a card of
 *  list rows instead of a five-column table row. Each row has an Edit that
 *  opens the same form the console has (spec 016, US4): name, role, and
 *  whether the account can sign in. */
function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const first = parts[0]!.charAt(0);
  const last = parts.length > 1 ? parts[parts.length - 1]!.charAt(0) : '';
  return (first + last).toUpperCase();
}

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

        {users.length > 0 && (
          <div className="list" style={{ marginTop: 10 }}>
            {users.map((user) => (
              <div key={user.id}>
                <div className="li">
                  <span className="avatar" aria-hidden="true">{initialsOf(user.name)}</span>
                  <span className="li__main">
                    <span className="li__title">{user.name}</span>
                    <span className="li__sub">{user.email}</span>
                    <span className="li__sub">{user.lastActive}</span>
                  </span>
                  <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
                    <Badge tone={user.role === 'admin' ? 'good' : 'neutral'}>
                      {t(user.role === 'admin' ? 'role.admin' : 'role.it')}
                    </Badge>
                    {user.disabled && <Badge tone="warn">{t('users.disabled')}</Badge>}
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      aria-expanded={editing === user.id}
                      onClick={() => setEditing(editing === user.id ? null : user.id)}
                    >
                      {t('users.edit')}
                    </button>
                  </span>
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
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title={t('users.roleWhatEachCanDo')} />
        <div style={{ marginTop: 4 }}>
          {CAPABILITIES.map((row) => (
            <Capability key={row.capability} {...row} />
          ))}
        </div>
      </Card>
    </>
  );
}

const ROLES: readonly Role[] = ['admin', 'it'];

/** The console's edit form, stacked for a phone. Only what changed is sent;
 *  a 409 (it would leave no active administrator) shows the engine's reason. */
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
  const ready = Object.keys(changes).length > 0 && name.trim() !== '';

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
    <div style={{ display: 'grid', gap: 12, padding: '12px 14px 16px' }}>
      <div style={{ fontSize: 14, fontWeight: 700 }}>{t('users.editTitle', { name: user.name })}</div>
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
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <span style={{ fontSize: 14 }}>{t('users.canSignInToggle')}</span>
        <Toggle on={active} onToggle={() => setActive(!active)} label={t('users.canSignInToggle')} />
      </div>
      {problem && (
        <div role="alert" style={{ color: 'var(--rd)', fontSize: 13.5 }}>{problem}</div>
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <button type="button" className="btn" disabled={!ready || saving} onClick={() => void save()}>
          {saving ? t('users.saving') : t('users.save')}
        </button>
        <button type="button" className="btn btn--ghost" onClick={onCancel}>
          {t('action.cancel')}
        </button>
      </div>
    </div>
  );
}

/* One capability per block rather than one cell per role: a bare "Yes" next
 * to a bare "No" only means something under a column header, and a phone
 * card has nowhere honest to keep that header attached once the row wraps.
 * Naming the role next to its answer keeps the fact readable on its own. */
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
  const yes = { fontSize: 13, fontWeight: 600, color: 'var(--ac2)' } as const;
  const no = { fontSize: 13, fontWeight: 600, color: 'var(--tx3)' } as const;

  return (
    <div style={{ padding: '12px 0', borderTop: '1px solid var(--line)' }}>
      <div style={{ fontSize: 14, marginBottom: 6 }}>{t(capability)}</div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <span style={admin ? yes : no}>
          {t('role.admin')}: {t(admin ? 'common.yes' : 'common.no')}
        </span>
        <span style={it ? yes : no}>
          {t('role.it')}: {t(it ? 'common.yes' : 'common.no')}
        </span>
      </div>
    </div>
  );
}
