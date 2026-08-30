import { Badge, Card, CardHeader, DataNotice, Empty, LoadError, PageHeader } from '@/components/ui';
import { getUsers } from '@/services/api';
import { useLanguage, useT } from '@/app/LanguageContext';
import { CAPABILITIES } from '@/services/content';
import type { MessageKey } from '@/i18n';
import type { User } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';

const NO_USERS: User[] = [];

export function Users() {
  const t = useT();
  const { language } = useLanguage();
  const capability = useCapability('users');
  const { data: users, error, loading, reload } = useAsync(() => getUsers(language), [language], NO_USERS);

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

        {loading && <Empty>{t('users.loadingAccounts')}</Empty>}
        {counted && users.length === 0 && (
          <Empty>{t('users.none')}</Empty>
        )}

        {users.map((user) => (
          <div
            key={user.id}
            className="row"
            style={{ gridTemplateColumns: '1.2fr .7fr 1.6fr .9fr .5fr' }}
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
            <button type="button" className="linkbtn">
              Edit
            </button>
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
