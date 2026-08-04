import {
  HeadContent,
  Link,
  Scripts,
  createRootRouteWithContext,
} from '@tanstack/react-router'
import { TanStackRouterDevtoolsPanel } from '@tanstack/react-router-devtools'
import { TanStackDevtools } from '@tanstack/react-devtools'

import TanStackQueryDevtools from '../integrations/tanstack-query/devtools'
import { AuthProvider, useAuth } from '../lib/auth'

import appCss from '../styles.css?url'

import type { QueryClient } from '@tanstack/react-query'

interface MyRouterContext {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<MyRouterContext>()({
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { name: 'theme-color', content: '#0ea5e9' },
      { title: 'Vagas' },
    ],
    links: [{ rel: 'stylesheet', href: appCss }],
  }),
  shellComponent: RootDocument,
})

const NAV = [
  { to: '/', label: 'Vagas', icon: 'M3 12h18M3 6h18M3 18h18' },
  { to: '/searches', label: 'Buscas', icon: 'M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z' },
  {
    to: '/profile',
    label: 'Perfil',
    icon: 'M16 21v-2a4 4 0 00-8 0v2M12 11a4 4 0 100-8 4 4 0 000 8z',
  },
]

function NavIcon({ path }: { path: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-5 w-5"
      aria-hidden="true"
    >
      <path d={path} />
    </svg>
  )
}

/** Tab bar no mobile, sidebar a partir de md. */
function Shell({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const authed = Boolean(user) && !loading

  return (
    <div className="min-h-dvh bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      {authed ? (
        <aside className="fixed inset-y-0 left-0 hidden w-56 flex-col border-r border-zinc-200 bg-white p-4 md:flex dark:border-zinc-800 dark:bg-zinc-900">
          <div className="mb-6 px-2 text-lg font-bold tracking-tight">Vagas</div>
          <nav className="flex flex-col gap-1">
            {NAV.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                activeProps={{
                  className:
                    'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium bg-sky-500/10 text-sky-700 dark:text-sky-300',
                }}
                activeOptions={{ exact: item.to === '/' }}
              >
                <NavIcon path={item.icon} />
                {item.label}
              </Link>
            ))}
          </nav>
        </aside>
      ) : null}

      <main className={authed ? 'pb-20 md:ml-56 md:pb-0' : ''}>{children}</main>

      {authed ? (
        <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-zinc-200 bg-white/95 backdrop-blur md:hidden dark:border-zinc-800 dark:bg-zinc-900/95">
          {NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="flex flex-1 flex-col items-center gap-1 py-2.5 text-xs text-zinc-500 dark:text-zinc-500"
              activeProps={{
                className:
                  'flex flex-1 flex-col items-center gap-1 py-2.5 text-xs text-sky-600 dark:text-sky-400',
              }}
              activeOptions={{ exact: item.to === '/' }}
            >
              <NavIcon path={item.icon} />
              {item.label}
            </Link>
          ))}
        </nav>
      ) : null}
    </div>
  )
}

function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <head>
        <HeadContent />
      </head>
      <body>
        <AuthProvider>
          <Shell>{children}</Shell>
        </AuthProvider>
        <TanStackDevtools
          config={{ position: 'bottom-right' }}
          plugins={[
            { name: 'Tanstack Router', render: <TanStackRouterDevtoolsPanel /> },
            TanStackQueryDevtools,
          ]}
        />
        <Scripts />
      </body>
    </html>
  )
}
