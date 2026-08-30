import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider } from '@/app/AuthContext';
import { CameraProvider } from '@/app/CameraContext';
import { CapabilityProvider } from '@/app/CapabilityContext';
import { LanguageProvider } from '@/app/LanguageContext';
import { SiteProvider } from '@/app/SiteContext';
import { ThemeProvider } from '@/app/ThemeContext';
import { AppRoutes } from '@/app/routes';
import '@/styles/app.css';

/*  The nesting order is a real constraint, not a preference:
 *
 *      AuthProvider      needs nothing else
 *      LanguageProvider  needs Auth      — the account decides the language
 *      CameraProvider    needs Language  — a camera's status is a sentence
 *
 *  Language sat below CameraProvider until 29 Aug 2026 and the whole console
 *  threw on load. `tsc` cannot see it: a context read is only wrong at
 *  runtime, in a particular tree. Anything that starts calling `useLanguage`
 *  has to sit under LanguageProvider, and moving a provider means checking
 *  this list again.
 */
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <AuthProvider>
        {/* Inside AuthProvider because the account is what decides the
            language — the gate station is shared, and a browser-wide setting
            would give the next guard on shift the previous guard's language.
            Outside the router so the sign-in page is readable before there is
            an account to ask. */}
        <LanguageProvider>
          {/* SiteProvider fetches the school name, the site's today and the
              camera tally once, so the chrome and every page agree on them. */}
          <SiteProvider>
            {/* CameraProvider owns the roster: which cameras exist. Held above
                the router so it survives navigation and outages — every page
                shows the same cameras, and they stay on screen as NO SIGNAL
                when the engine is unreachable rather than vanishing. */}
            <CameraProvider>
              {/* CapabilityProvider says which features are measured and which
                  are not, with the reason. Pages check it before rendering a
                  number, because an empty register and a broken one arrive
                  looking identical. */}
              <CapabilityProvider>
                <BrowserRouter>
                  <AppRoutes />
                </BrowserRouter>
              </CapabilityProvider>
            </CameraProvider>
          </SiteProvider>
        </LanguageProvider>
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>,
);
