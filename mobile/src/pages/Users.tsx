import { Badge, Card, CardHeader, DataNotice, Empty, LoadError, PageHeader } from '@/components/ui';
import { getUsers } from '@/services/api';
import { useLanguage, useT } from '@/app/LanguageContext';
import { CAPABILITIES } from '@/services/content';
import type { MessageKey } from '@/i18n';
import type { User } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';

const NO_USERS: User[] = [];

/** Accounts — who can sign in (spec 015, contracts/phone-screens.md
 *  "Accounts").
 *
 *  Built from `web/src/pages/Users.tsx`: the same call, the same "0 people
 *  can sign in" rule (a claim only made once the engine has actually
 *  answered), and the same role/capability matrix. Rearranged as a card of
 *  list rows instead of a five-column table row, because a table row is
 *  exactly the shape the inventory found broken here: the console's per-row
 *  "Edit" button has no click handler at all (research R10). That is left
 *  out rather than copied — a button that does nothing is a fact this app
 *  does not get to invent. */
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

        {users.length > 0 && (
          <div className="list" style={{ marginTop: 10 }}>
            {users.map((user) => (
              <div key={user.id} className="li">
                <span className="avatar" aria-hidden="true">{initialsOf(user.name)}</span>
                <span className="li__main">
                  <span className="li__title">{user.name}</span>
                  <span className="li__sub">{user.email}</span>
                  <span className="li__sub">{user.lastActive}</span>
                </span>
                <Badge tone={user.role === 'admin' ? 'good' : 'neutral'}>
                  {t(user.role === 'admin' ? 'role.admin' : 'role.it')}
                </Badge>
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
