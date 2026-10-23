import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../auth';
import { App } from '../App';
import { mockControls, mocks } from '../api/mocks';
import { ApiError } from '../api/types';

function start(path: string, user = 'priya.qa') {
  localStorage.setItem('labellock_token', `mock:${user}`);
  render(<MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
}
beforeEach(() => { localStorage.clear(); mockControls.reset(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('ROI dashboard', () => {
  it('renders contract measurements, separated assumptions and measured comparison', async () => {
    start('/roi');
    const measured = await screen.findByRole('region', { name: 'Measured results' }, { timeout: 5000 });
    for (const value of ['16 / 20', '0', '90.9%', '84.4%', '50.0%']) expect(within(measured).getByText(value)).toBeInTheDocument();
    expect(within(measured).getByText(/x faster/)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Assumptions' })).toHaveTextContent('Estimate from assumptions');
  });
  it('omits speed-up without manual runs, then logs a run and refreshes median', async () => {
    mockControls.setInitialManualRuns(0);
    start('/roi');
    expect(await screen.findByText('No manual runs logged yet - use the timer below', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.queryByText(/x faster/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Start' }));
    await userEvent.click(screen.getByRole('button', { name: 'Stop' }));
    await userEvent.type(screen.getByLabelText('Batches found'), '2');
    await userEvent.type(screen.getByLabelText('False holds'), '0');
    await userEvent.click(screen.getByRole('button', { name: 'Log manual run' }));
    expect(await screen.findByText(/Manual run b_101 logged/, {}, { timeout: 5000 })).toBeInTheDocument();
    const roi = await mocks.getRoi('mock:priya.qa');
    expect(roi.measured.manual_runs).toBe(1);
    expect(roi.measured.manual_median_seconds).not.toBeNull();
  }, 12000);
  it('rejects unknown scenarios and unauthorized roles with typed errors', async () => {
    const body = { scenario_id: 'S21', mode: 'manual' as const, seconds: 30, batches_found: 0, false_holds: 0, operator: 'Priya' };
    await expect(mocks.logBenchmark('mock:priya.qa', body)).rejects.toMatchObject({ status: 422, code: 'VALIDATION_ERROR', message: 'Unknown scenario id' });
    await expect(mocks.logBenchmark('mock:marco.ship', { ...body, scenario_id: 'S01' })).rejects.toMatchObject({ status: 403, code: 'FORBIDDEN' });
  });
  it('shows a 422 field message and request ID returned by the server', async () => {
    start('/roi');
    await screen.findByText('16 / 20', {}, { timeout: 5000 });
    vi.spyOn(mocks, 'logBenchmark').mockRejectedValueOnce(new ApiError(422, { error: { code: 'VALIDATION_ERROR', message: 'Unknown scenario', request_id: 'req_invalid', details: { fields: [{ field: 'body.scenario_id', message: 'not a scenario in backend/scenarios' }] } } }));
    await userEvent.click(screen.getByRole('button', { name: 'Start' }));
    await userEvent.click(screen.getByRole('button', { name: 'Stop' }));
    await userEvent.type(screen.getByLabelText('Batches found'), '2');
    await userEvent.type(screen.getByLabelText('False holds'), '0');
    await userEvent.click(screen.getByRole('button', { name: 'Log manual run' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('body.scenario_id: not a scenario in backend/scenarios');
    expect(screen.getByRole('alert')).toHaveTextContent('Request ID: req_invalid');
  }, 10000);
  it('lets admin open ROI and retries a loading error', async () => {
    mockControls.setRoiError(true); start('/roi', 'admin');
    expect(await screen.findByRole('alert', {}, { timeout: 5000 })).toHaveTextContent('ROI temporarily unavailable');
    mockControls.setRoiError(false);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('16 / 20')).toBeInTheDocument();
  });
  it('recalculates local estimates, restores defaults, and excludes recall cost', async () => {
    start('/roi');
    const assumptions = await screen.findByRole('region', { name: 'Assumptions' }, { timeout: 5000 });
    const original = within(assumptions).getByText(/QA hours saved per month/).textContent;
    const volume = screen.getByLabelText(/Supplier change notices handled per month/);
    await userEvent.clear(volume); await userEvent.type(volume, '60');
    expect(within(assumptions).getByText(/QA hours saved per month/).textContent).not.toBe(original);
    const beforeCost = within(assumptions).getByText(/Estimated QA time cost:/).textContent;
    const recall = screen.getByLabelText(/Direct cost of one undeclared-allergen recall/);
    await userEvent.clear(recall); await userEvent.type(recall, '25000000');
    expect(within(assumptions).getByText(/Estimated QA time cost:/).textContent).toBe(beforeCost);
    await userEvent.click(screen.getByRole('button', { name: 'Reset to defaults' }));
    expect(volume).toHaveValue(30); expect(recall).toHaveValue(10000000);
    expect(within(assumptions).getByText(/QA hours saved per month/).textContent).toBe(original);
  }, 12000);
});

describe('demo settings', () => {
  it('lets admin see controls and blocks QA users', async () => {
    start('/settings', 'admin');
    expect(await screen.findByRole('heading', { name: 'Demo controls' }, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'WMS silently fails holds' })).toHaveAttribute('aria-checked', 'false');
    cleanup(); start('/settings', 'priya.qa');
    expect(await screen.findByText('Not permitted for your role', {}, { timeout: 5000 })).toBeInTheDocument();
  });
  it('requires confirmation, supports cancel and clears fault on reset', async () => {
    start('/settings', 'admin');
    await screen.findByRole('heading', { name: 'Demo controls' }, { timeout: 5000 });
    await userEvent.click(screen.getByRole('switch', { name: 'WMS silently fails holds' }));
    expect(await screen.findByText('WMS silent hold failure on.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Reset demo' }));
    const dialog = screen.getByRole('dialog', { name: 'Confirm demo reset' });
    expect(dialog).toHaveTextContent('All cases, notices, actions and audit events are deleted');
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Reset demo' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm reset' }));
    expect(await screen.findByText('Demo reset. Fault switch is off.')).toBeInTheDocument();
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
  }, 12000);
  it('shows disabled message on 404', async () => {
    mockControls.setDemoDisabled(true); start('/settings', 'admin');
    await screen.findByRole('heading', { name: 'Demo controls' }, { timeout: 5000 });
    await userEvent.click(screen.getByRole('switch', { name: 'WMS silently fails holds' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Demo controls are disabled on this server (DEMO_MODE=false)');
  });
});
