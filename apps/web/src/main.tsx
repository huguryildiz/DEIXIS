import "@fontsource-variable/inter"
import "@fontsource-variable/source-serif-4"
import "@fontsource-variable/source-serif-4/wght-italic.css"
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ToastProvider } from './Toast'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>,
)
