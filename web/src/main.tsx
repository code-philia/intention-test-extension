import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './index.css';

const body = document.body;
if (body.hasAttribute('theme-mode')) {
  body.removeAttribute('theme-mode');
}
if (body.classList.contains('vscode-dark')) {
  body.setAttribute('theme-mode', 'dark');
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
