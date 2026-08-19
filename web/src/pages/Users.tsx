import { useEffect, useState } from 'react';
import { Badge, Card, CardHeader, DataNotice, PageHeader } from '@/components/ui';
import { getUsers } from '@/services/api';
import { CAPABILITIES } from '@/services/content';
import type { User } from '@/types';
import { useCapability } from '@/app/CapabilityContext';

export function Users() {
  const capability = useCapability('users');
  const [users, setUsers] = useState<User[]>([]);

  useEffect(() => {
    void getUsers().then(setUsers);
  }, []);

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader title="Users" lead="Who can sign in, and what they are allowed to do." />

      <Card>
        <CardHeader
          title={`${users.length} people can sign in`}
          sub="Only admins can add or change accounts."
        />

        {users.map((user) => (
          <div
            key={user.id}
            className="row"
            style={{ gridTemplateColumns: '1.2fr .7fr 1.6fr .9fr .5fr' }}
          >
            <span className="row__name">{user.name}</span>
            <span>
              <Badge tone={user.role === 'admin' ? 'good' : 'neutral'}>
                {user.role === 'admin' ? 'Admin' : 'IT'}
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
          What each role can do
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr .6fr .6fr', fontSize: 13.5 }}>
          <span className="row--head">CAPABILITY</span>
          <span className="row--head">ADMIN</span>
          <span className="row--head">IT</span>

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
  capability: string;
  admin: boolean;
  it: boolean;
}) {
  const cell = { padding: '9px 0', borderTop: '1px solid var(--line)' } as const;
  const yes = { ...cell, color: 'var(--ac2)', fontWeight: 600 } as const;
  const no = { ...cell, color: 'var(--tx3)' } as const;

  return (
    <>
      <span style={cell}>{capability}</span>
      <span style={admin ? yes : no}>{admin ? 'Yes' : 'No'}</span>
      <span style={it ? yes : no}>{it ? 'Yes' : 'No'}</span>
    </>
  );
}
