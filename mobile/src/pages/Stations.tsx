import { useT } from '@/app/LanguageContext';

/** Work stations on the phone: an honest "not here yet".
 *
 *  Stations are drawn and read on the console. The Home alert for an empty
 *  station links to `/stations`, a path the byte-shared `useAttention.ts`
 *  produces; without this route it fell through to the catch-all and sent the
 *  guard back to Home with no word said. The Tools list does not offer a
 *  Stations tile (see `PHONE_TOOL_PATHS` in `app/tabs.ts`), so this page is
 *  reached only from that link. It shows nothing measured, because the phone
 *  has nothing to measure it with. */
export function Stations() {
  const t = useT();
  return (
    <>
      <h1 className="h1">{t('mobile.stations.title')}</h1>
      <div className="card">
        <p className="lead" style={{ margin: 0 }}>{t('mobile.stations.body')}</p>
      </div>
    </>
  );
}
