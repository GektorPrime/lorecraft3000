import {
  Outlet,
  RouterProvider,
  createHashRouter,
  redirect,
  useMatches,
  type LoaderFunctionArgs,
  type RouteObject,
} from 'react-router-dom'
import { BudgetProvider } from './api/BudgetProvider'
import { OptionsProvider } from './api/OptionsProvider'
import { Header } from './components/Header'
import { Home } from './pages/Home'
import { NotFoundPage } from './pages/NotFoundPage'
import { CharacterDetailPage } from './pages/characters/CharacterDetailPage'
import { CharacterFormPage } from './pages/characters/CharacterFormPage'
import { CharacterListPage } from './pages/characters/CharacterListPage'
import { GenerationDetailPage } from './pages/panels/GenerationDetailPage'
import { PanelFormPage } from './pages/panels/PanelFormPage'
import { PanelListPage } from './pages/panels/PanelListPage'
import { PanelPreviewPage } from './pages/panels/PanelPreviewPage'
import { StyleFormPage } from './pages/styles/StyleFormPage'
import { StyleListPage } from './pages/styles/StyleListPage'
import { parseRouteId } from './routing/parseRouteId'
import { usePageTitle } from './routing/usePageTitle'

interface RouteHandle {
  title?: string
}

function StaticRouteTitle() {
  const matches = useMatches()
  const title = matches.reduce<string | undefined>((current, match) => {
    const handle = match.handle as RouteHandle | undefined
    return handle?.title ?? current
  }, undefined)
  usePageTitle(title)
  return null
}

function RouteLayout() {
  return (
    <>
      <StaticRouteTitle />
      <Outlet />
    </>
  )
}

function ConfiguredAppLayout() {
  return (
    <>
      <OptionsProvider>
        <BudgetProvider>
          <Header />
          <main className="app-main">
            <Outlet />
          </main>
        </BudgetProvider>
      </OptionsProvider>
    </>
  )
}

function requireRouteId({ params }: LoaderFunctionArgs) {
  return parseRouteId(params.id) === null ? redirect('/not-found') : null
}

const appRoutes: RouteObject[] = [
  {
    element: <RouteLayout />,
    children: [
      {
        path: 'not-found',
        element: <NotFoundPage />,
        handle: { title: 'Page Not Found' } satisfies RouteHandle,
      },
      {
        path: '*',
        element: <NotFoundPage />,
        handle: { title: 'Page Not Found' } satisfies RouteHandle,
      },
      {
        element: <ConfiguredAppLayout />,
        children: [
          { index: true, element: <Home />, handle: { title: 'Home' } satisfies RouteHandle },
          {
            path: 'characters',
            element: <CharacterListPage />,
            handle: { title: 'Characters' } satisfies RouteHandle,
          },
          {
            path: 'characters/new',
            element: <CharacterFormPage />,
            handle: { title: 'New Character' } satisfies RouteHandle,
          },
          {
            path: 'characters/:id',
            loader: requireRouteId,
            element: <CharacterDetailPage />,
            handle: { title: 'Loading Character' } satisfies RouteHandle,
          },
          {
            path: 'characters/:id/edit',
            loader: requireRouteId,
            element: <CharacterFormPage />,
            handle: { title: 'Edit Character' } satisfies RouteHandle,
          },
          {
            path: 'styles',
            element: <StyleListPage />,
            handle: { title: 'Styles' } satisfies RouteHandle,
          },
          {
            path: 'styles/new',
            element: <StyleFormPage />,
            handle: { title: 'New Style' } satisfies RouteHandle,
          },
          {
            path: 'styles/:id/edit',
            loader: requireRouteId,
            element: <StyleFormPage />,
            handle: { title: 'Edit Style' } satisfies RouteHandle,
          },
          {
            path: 'panels',
            element: <PanelListPage />,
            handle: { title: 'Panels' } satisfies RouteHandle,
          },
          {
            path: 'panels/new',
            element: <PanelFormPage />,
            handle: { title: 'New Panel' } satisfies RouteHandle,
          },
          {
            path: 'panels/:id/edit',
            loader: requireRouteId,
            element: <PanelFormPage />,
            handle: { title: 'Edit Panel' } satisfies RouteHandle,
          },
          {
            path: 'panels/:id/preview',
            loader: requireRouteId,
            element: <PanelPreviewPage />,
            handle: { title: 'Loading Panel Preview' } satisfies RouteHandle,
          },
          {
            path: 'generations/:id',
            loader: requireRouteId,
            element: <GenerationDetailPage />,
            handle: { title: 'Loading Generation' } satisfies RouteHandle,
          },
        ],
      },
    ],
  },
]

/**
 * Hash routing keeps every client route under the server's root path, so hard
 * refreshes and direct links do not collide with backend paths.
 */
const router = createHashRouter(appRoutes)

function App() {
  return <RouterProvider router={router} />
}

export default App
