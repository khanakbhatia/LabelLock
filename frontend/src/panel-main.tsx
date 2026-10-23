import React from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import { AuthProvider } from './auth';
import { App } from './App';
import './panel.css';

document.documentElement.dataset.appMode = 'panel';
createRoot(document.getElementById('root')!).render(<React.StrictMode><HashRouter><AuthProvider><App /></AuthProvider></HashRouter></React.StrictMode>);
