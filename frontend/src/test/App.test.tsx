import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../auth';
import { App } from '../App';
import { mockControls } from '../api/mocks';
import inboxExample from '../../../contracts/examples/inbox.json';

function start(path = '/login') {
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
}
async function signIn(username: string) {
  await userEvent.click(screen.getByRole('button', { name: new RegExp(username, 'i') }));
  await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
}
beforeEach(() => { localStorage.clear(); mockControls.reset(); });
afterEach(cleanup);

describe('role routing', () => {
  it.each([
    ['valley.ingredients', 'Supplier portal'], ['priya.qa', 'QA inbox'],
    ['daniel.qam', 'QA inbox'], ['marco.ship', 'Cases'],
    ['admin', 'Settings'], ['labellock-agent', 'Service account'],
  ])('%s opens %s', async (username, heading) => {
    start(); await signIn(username);
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
  });

  it('blocks a supplier who opens the QA inbox', async () => {
    localStorage.setItem('labellock_token', 'mock:valley.ingredients');
    start('/inbox');
    expect(await screen.findByRole('heading', { name: 'Not permitted for your role' })).toBeInTheDocument();
  });
});

describe('supplier notice', () => {
  it('rejects non-PDF files and confirms a valid notice', async () => {
    start(); await signIn('valley.ingredients');
    await screen.findByRole('heading', { name: 'Supplier portal' });
    await userEvent.type(screen.getByLabelText(/subject/i), 'Changed ingredient');
    await userEvent.type(screen.getByLabelText(/message body/i), 'Effective from lot VL-2201');
    await userEvent.upload(screen.getByLabelText(/specification pdf/i), new File(['text'], 'spec.txt', { type: 'text/plain' }), { applyAccept: false });
    await userEvent.click(screen.getByRole('button', { name: /submit notice/i }));
    expect(screen.getByText('Choose a PDF file.')).toBeInTheDocument();
    await userEvent.upload(screen.getByLabelText(/specification pdf/i), new File(['%PDF-1.4'], 'spec.pdf', { type: 'application/pdf' }));
    await userEvent.click(screen.getByRole('button', { name: /submit notice/i }));
    expect(await screen.findByText('Received by Northfield QA')).toBeInTheDocument();
    expect(screen.getByText('n_101')).toBeInTheDocument();
    expect(await within(screen.getByRole('heading', { name: 'My notices' }).closest('section')!).findByText('Changed ingredient')).toBeInTheDocument();
  });
});

describe('QA inbox', () => {
  it('renders example notices with status text', async () => {
    start(); await signIn('priya.qa');
    const table = await screen.findByRole('table', {}, { timeout: 3000 });
    for (const item of inboxExample) {
      expect(within(table).getByText(item.subject)).toBeInTheDocument();
      expect(within(table).getAllByText(item.case_status.replaceAll('_', ' ')).length).toBeGreaterThan(0);
    }
  });

  it('shows an error and retries successfully', async () => {
    mockControls.setInboxError(true);
    start(); await signIn('priya.qa');
    expect(await screen.findByText('Inbox temporarily unavailable')).toBeInTheDocument();
    mockControls.setInboxError(false);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument());
  });

  it('opens a case when the row is clicked', async () => {
    start(); await signIn('priya.qa');
    const table = await screen.findByRole('table', {}, { timeout: 3000 });
    await userEvent.click(within(table).getAllByText(inboxExample[0].supplier)[0]);
    expect(await screen.findByRole('heading', { name: 'Case workspace' })).toBeInTheDocument();
    expect(screen.getByText('Coming in M2')).toBeInTheDocument();
  });
});
