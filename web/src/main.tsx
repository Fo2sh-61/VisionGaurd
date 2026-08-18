import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider } from '@/app/AuthContext';
import { CameraProvider } from '@/app/CameraContext';
import { SiteProvider } from '@/app/SiteContext';
import { ThemeProvider } from '@/app/ThemeContext';
import { AppRoutes } from '@/app/routes';
import '@/styles/app.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      {/* SiteProvider fetches the school name, the site's today and the camera
          tally once, so the chrome and every page agree on them. */}
      <SiteProvider>
        {/* CameraProvider owns the roster: which cameras exist. Held above the
            router so it survives navigation and outages — every page shows the
            same cameras, and they stay on screen as NO SIGNAL when the engine
            is unreachable rather than vanishing. */}
        <CameraProvider>
          <AuthProvider>
            <BrowserRouter>
              <AppRoutes />
            </BrowserRouter>
          </AuthProvider>
        </CameraProvider>
      </SiteProvider>
    </ThemeProvider>
  </StrictMode>,
);
