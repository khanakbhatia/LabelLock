import { beforeEach, afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../auth';
import { App } from '../App';
import { mockControls, mocks } from '../api/mocks';
import summaries from '../../../contracts/examples/case_summary_list.json';

function start(path: string, who = 'priya.qa') {
  localStorage.setItem('labellock_token', `mock:${who}`);
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
}
beforeEach(() => { localStorage.clear(); mockControls.reset(); });
afterEach(cleanup);

describe('cases list', () => {
  it('shows example cases, statuses and warning flags, and opens a case', async () => {
    mockControls.setCaseFlags(['SUPPLIER_UNVERIFIED']);
    start('/cases');
    const table = await screen.findByRole('table', {}, { timeout: 4000 });
    for (const example of summaries) expect(within(table).getByText(example.subject)).toBeInTheDocument();
    expect(within(table).getByText('Unverified sender')).toBeInTheDocument();
    expect(within(table).getByText('AWAITING APPROVAL')).toBeInTheDocument();
    await userEvent.click(within(table).getByRole('link', { name: summaries[1].subject }));
    expect(await screen.findByRole('heading', { name: summaries[1].subject })).toBeInTheDocument();
  });
  it('retries an API error', async () => {
    mockControls.setCasesError(true); start('/cases');
    expect(await screen.findByRole('alert', {}, { timeout: 3000 })).toHaveTextContent('Cases temporarily unavailable');
    mockControls.setCasesError(false);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('table')).toBeInTheDocument();
  });
});

describe('case workspace', () => {
  it('returns the contract 403 for unauthorized API reads and run/report calls', async () => {
    for (const call of [() => mocks.listCases('mock:valley.ingredients'), () => mocks.getCase('mock:valley.ingredients', 'c_001'), () => mocks.getTimeline('mock:valley.ingredients', 'c_001'), () => mocks.runCase('mock:marco.ship', 'c_001'), () => mocks.getReport('mock:marco.ship', 'c_001')]) {
      await expect(call()).rejects.toMatchObject({ status: 403, code: 'FORBIDDEN', response: { error: { request_id: expect.any(String) } } });
    }
  });
  it('shows the contract detail in all five tabs, evidence and failure', async () => {
    mockControls.setActionStatus('VERIFY_FAILED');
    start('/cases/c_001');
    expect(await screen.findByRole('heading', { name: 'Lecithin source change from lot VL-2291' }, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText('MISSING')).toBeInTheDocument();
    expect(within(screen.getByRole('row', { name: /may contain/i })).getByText('No evidence')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Batch Detective' }));
    expect(screen.getByText(/Material lot VL-2291/)).toBeInTheDocument();
    expect(screen.getAllByText('HELD').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('tab', { name: 'Label Check' }));
    expect(screen.getByText(/LBL-MISSING-ALLERGEN/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Actions' }));
    expect(screen.getByText('VERIFY FAILED')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Timeline' }));
    expect(await screen.findByText('NOTICE RECEIVED')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'View report' }));
    expect(await screen.findByRole('region', { name: 'Case report' })).toHaveTextContent('431');
  });
  it('denies a supplier and hides run and report for shipping supervisor', async () => {
    const view = start('/cases/c_001', 'valley.ingredients');
    expect(await screen.findByRole('heading', { name: 'Not permitted for your role' })).toBeInTheDocument();
    view.unmount(); localStorage.clear();
    start('/cases/c_001', 'marco.ship');
    expect(await screen.findByRole('heading', { name: 'Lecithin source change from lot VL-2291' }, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run agent' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'View report' })).not.toBeInTheDocument();
  });
  it('polls a background run from analyzing to awaiting approval', async () => {
    start('/cases/c_001');
    await screen.findByRole('button', { name: 'Run agent' }, { timeout: 4000 });
    await userEvent.click(screen.getByRole('button', { name: 'Run agent' }));
    expect(await screen.findByText('ANALYZING', {}, { timeout: 4000 })).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText('AWAITING APPROVAL').length).toBeGreaterThan(0), { timeout: 6000 });
    expect(screen.getByRole('status')).toHaveTextContent('Agent finished');
  }, 12000);
  it('shows the contract conflict error instead of hiding it', async () => {
    mockControls.setRunConflict(true); start('/cases/c_001');
    await userEvent.click(await screen.findByRole('button', { name: 'Run agent' }, { timeout: 4000 }));
    expect(await screen.findByRole('alert')).toHaveTextContent('CONFLICT: Agent already running');
  });
});
