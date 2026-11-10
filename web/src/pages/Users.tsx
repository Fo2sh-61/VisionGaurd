import { useState } from 'react';
import { Badge, Card, CardHeader, DataNotice, Empty, LoadError, PageHeader, Select } from '@/components/ui';
import { getUsers, updateUserRole } from '@/services/api';
import { useLanguage, useT } from '@/app/LanguageContext';
import { useToast } from '@/app/ToastContext';
import { CAPABILITIES } from '@/services/content';
import type { MessageKey } from '@/i18n';
import type { Role, User } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';

const NO_USERS: User[] = [];
const ROLES: Role[] = ['admin', 'it'];

export function Users() {
  const t = useT();
  const { language } = useLanguage();
  const capability = useCapability('users');
  const { data: users, error, loading, reload } = useAsync(() => getUsers(language), [language], NO_USERS);
  const toast = useToast();
  // The reason the engine gave for the last refused change, shown beside the
  // list where it can be read. A toast is for success only.
  const [roleError, setRoleError] = useState<string | null>(null);

  async function changeRole(user: User, role: Role) {
    if (role === user.role) return;
    setRoleError(null);
    try {
      await updateUserRole(user.id, role);
      toast.show(t('users.roleChanged', { name: user.name, role: t(role === 'admin' ? 'role.admin' : 'role.it') }));
      reload();
    } catch (err) {
      setRoleError(t('users.roleFailed', {
        reason: err instanceof Error ? err.message : t('common.engineRefused'),
      }));
      // The select shows what the server holds, not what was tried.
      reload();
    }
  }

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
            ? t('users.canSignIn', { count: users.length })
            : t('users.whoCanSignIn')}
          sub={t('users.adminsOnly')}
        />

        {roleError && (
          <div role="alert" style={{ fontSize: 13.5, color: 'var(--rd)', background: 'var(--rd-bg)', padding: '8px 14px', borderRadius: 10, marginBottom: 10 }}>
            {roleError}
          </div>
        )}

        {counted && users.length > 0 && (
          <div className="row row--head" style={{ gridTemplateColumns: '1.2fr .7fr 1.6fr .9fr 1fr' }}>
            <span>{t('users.nameHead')}</span>
            <span>{t('users.roleHead')}</span>
            <span>{t('users.emailHead')}</span>
            <span>{t('users.lastSignedIn')}</span>
            <span />
          </div>
        )}
        {loading && <Empty>{t('users.loadingAccounts')}</Empty>}
        {counted && users.length === 0 && (
          <Empty>{t('users.none')}</Empty>
        )}

        {users.map((user) => (
          <div
            key={user.id}
            className="row"
            style={{ gridTemplateColumns: '1.2fr .7fr 1.6fr .9fr 1fr' }}
          >
            <span className="row__name">{user.name}</span>
            <span>
              <Badge tone={user.role === 'admin' ? 'good' : 'neutral'}>
                {t(user.role === 'admin' ? 'role.admin' : 'role.it')}
              </Badge>
            </span>
            <span
              className="row__muted"
              style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}
            >
              {user.email}
            </span>
            <span className="row__muted">{user.lastActive}</span>
            <span aria-label={t('users.changeRole', { name: user.name })}>
              <Select
                value={user.role}
                onChange={(value) => void changeRole(user, value as Role)}
                options={ROLES}
                label={(r) => t(r === 'admin' ? 'role.admin' : 'role.it')}
              />
            </span>
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
