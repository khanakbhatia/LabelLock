import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../auth';
import { App } from '../App';
import { ApprovalDecision } from '../views/ApprovalDecision';
import { mockControls, mocks } from '../api/mocks';
import approvalsExample from '../../../contracts/examples/approvals.json';

function start(path: string, username = 'daniel.qam') {
  localStorage.setItem('labellock_token', `mock:${username}`);
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
}
beforeEach(() => { localStorage.clear(); mockControls.reset(); });
afterEach(cleanup);

describe('approvals queue', () => {
  it('shows human action, case, requester and age; approves after confirmation', async () => {
    start('/approvals');
    const row = await screen.findByRole('region', { name: 'Action a_012' }, { timeout: 5000 });
    expect(within(row).getByText('Remove FG-1043 from shipment L-552 to Retailer DC 7')).toBeInTheDocument();
    expect(within(row).getByText(/labellock-agent/)).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: 'View case c_001' })).toBeInTheDocument();
    expect(within(row).getByText(/ago|Just now/)).toBeInTheDocument();
    await userEvent.click(within(row).getByRole('button', { name: 'Approve' }));
    const dialog = screen.getByRole('dialog', { name: 'Confirm approve a_012' });
    expect(dialog).toHaveTextContent('Remove FG-1043 from shipment L-552 to Retailer DC 7');
    await userEvent.type(within(dialog).getByLabelText('Comment (optional)'), 'QA reviewed trace');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm approve' }));
    expect(await within(row).findByText('APPROVED')).toBeInTheDocument();
    await waitFor(async () => expect((await mocks.getCase('mock:daniel.qam', 'c_001')).actions.find(a => a.id === 'a_012')?.status).toBe('VERIFIED'), { timeout: 5000 });
  }, 12000);

  it('requires a reason before rejection and shows the returned status', async () => {
    start('/approvals');
    const row = await screen.findByRole('region', { name: 'Action a_012' }, { timeout: 5000 });
    await userEvent.click(within(row).getByRole('button', { name: 'Reject' }));
    const dialog = screen.getByRole('dialog', { name: 'Confirm reject a_012' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm reject' }));
    expect(within(dialog).getByText('A reason is required to reject this action.')).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText('Reason (required)'), 'Shipment already departed');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm reject' }));
    expect(await within(row).findByText('REJECTED')).toBeInTheDocument();
  }, 10000);

  it('keeps specialist read only but exposes a forced API 403 with request ID', async () => {
    start('/approvals', 'priya.qa');
    const row = await screen.findByRole('region', { name: 'Action a_012' }, { timeout: 5000 });
    expect(screen.getByText(/A QA manager must approve or reject/)).toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
    const forced = render(<ApprovalDecision action={approvalsExample[0] as Parameters<typeof ApprovalDecision>[0]['action']} description="Remove FG-1043 from shipment L-552" token="mock:priya.qa" onDecision={() => { throw Error('Should not approve'); }} />);
    await userEvent.click(within(forced.container).getByRole('button', { name: 'Approve' }));
    await userEvent.click(within(forced.container).getByRole('button', { name: 'Confirm approve' }));
    expect(await within(forced.container).findByRole('alert')).toHaveTextContent('FORBIDDEN');
    expect(within(forced.container).getByRole('alert')).toHaveTextContent('Request ID: req_');
  }, 10000);
});

describe('case action governance', () => {
  it('approves in the workspace and polls the action to VERIFIED', async () => {
    start('/cases/c_001');
    await screen.findByRole('heading', { name: 'Lecithin source change from lot VL-2291' }, { timeout: 5000 });
    await userEvent.click(screen.getByRole('tab', { name: 'Actions' }));
    const row = screen.getByRole('row', { name: /REMOVE FROM SHIPMENT/i });
    await userEvent.click(within(row).getByRole('button', { name: 'Approve' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Remove FG-1043 from shipment L-552 to Retailer DC 7');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm approve' }));
    await waitFor(() => expect(within(row).getByText('VERIFIED')).toBeInTheDocument(), { timeout: 6500 });
  }, 12000);

  it('shows the policy error before disposition, then creates a pending release action', async () => {
    start('/cases/c_001');
    await screen.findByRole('heading', { name: 'Lecithin source change from lot VL-2291' }, { timeout: 5000 });
    await userEvent.click(screen.getByRole('tab', { name: 'Actions' }));
    const held = screen.getByRole('article', { name: 'Held batch FG-1041' });
    await userEvent.type(within(held).getByLabelText('Reason (required)'), 'Verified safe for controlled release');
    await userEvent.click(within(held).getByRole('button', { name: 'Request release' }));
    expect(await within(held).findByRole('alert')).toHaveTextContent('needs an approved disposition first');
    expect(within(held).getByRole('alert')).toHaveTextContent('POLICY_VIOLATION');
    expect(within(held).getByRole('alert')).toHaveTextContent('Request ID: req_91ab');
    await userEvent.click(within(held).getByRole('button', { name: 'Record disposition' }));
    expect(within(held).getByRole('alert')).toHaveTextContent('Evidence is required');
    await userEvent.type(within(held).getByLabelText('Evidence (required)'), 'Signed QA review and lab results');
    await userEvent.click(within(held).getByRole('button', { name: 'Record disposition' }));
    expect(await within(held).findByText(/Disposition RELABEL recorded/)).toBeInTheDocument();
    await userEvent.click(within(held).getByRole('button', { name: 'Request release' }));
    expect(await screen.findByRole('row', { name: /RELEASE HOLD.*PENDING APPROVAL/i }, { timeout: 4000 })).toBeInTheDocument();
  }, 16000);

  it('allows a specialist or shipping supervisor to request release but not record disposition', async () => {
    for (const role of ['mock:priya.qa', 'mock:marco.ship']) {
      await expect(mocks.recordDisposition(role, 'c_001', { batch_id: 'FG-1041', disposition: 'RELABEL', evidence: 'signed' })).rejects.toMatchObject({ status: 403, code: 'FORBIDDEN' });
      await expect(mocks.requestRelease(role, 'c_001', { batch_id: 'FG-1041', reason: 'Test' })).rejects.toMatchObject({ status: 409, code: 'POLICY_VIOLATION' });
    }
  });
});
