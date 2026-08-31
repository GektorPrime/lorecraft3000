import { HashRouter, Route, Routes } from 'react-router-dom'
import { OptionsProvider } from './api/OptionsProvider'
import { Header } from './components/Header'
import { CharacterDetailPage } from './pages/characters/CharacterDetailPage'
import { CharacterFormPage } from './pages/characters/CharacterFormPage'
import { CharacterListPage } from './pages/characters/CharacterListPage'
import { GenerationDetailPage } from './pages/panels/GenerationDetailPage'
import { PanelFormPage } from './pages/panels/PanelFormPage'
import { PanelListPage } from './pages/panels/PanelListPage'
import { PanelPreviewPage } from './pages/panels/PanelPreviewPage'
import { Home } from './pages/Home'
import { StyleFormPage } from './pages/styles/StyleFormPage'
import { StyleListPage } from './pages/styles/StyleListPage'

/**
 * Client-side routing uses a hash router deliberately: every LoreCraft3000
 * route lives under a single server path ("/"), so a hash fragment (e.g.
 * "/#/characters") never collides with the legacy server-rendered Jinja
 * routes registered at the SAME-LOOKING paths in app/routes/*.py (e.g. GET
 * /characters), and a hard refresh on any frontend route still resolves
 * correctly (see app/main.py for the server-side rationale).
 */
function App() {
  return (
    <HashRouter>
      <OptionsProvider>
        <Header />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/characters" element={<CharacterListPage />} />
            <Route path="/characters/new" element={<CharacterFormPage />} />
            <Route path="/characters/:id" element={<CharacterDetailPage />} />
            <Route path="/characters/:id/edit" element={<CharacterFormPage />} />
            <Route path="/styles" element={<StyleListPage />} />
            <Route path="/styles/new" element={<StyleFormPage />} />
            <Route path="/styles/:id/edit" element={<StyleFormPage />} />
            <Route path="/panels" element={<PanelListPage />} />
            <Route path="/panels/new" element={<PanelFormPage />} />
            <Route path="/panels/:id/edit" element={<PanelFormPage />} />
            <Route path="/panels/:id/preview" element={<PanelPreviewPage />} />
            <Route path="/generations/:id" element={<GenerationDetailPage />} />
          </Routes>
        </main>
      </OptionsProvider>
    </HashRouter>
  )
}

export default App
