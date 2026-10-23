import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Action } from '../api';
import { ApprovalDecision, describeAction } from '../views/ApprovalDecision';
import { ActionDetail } from '../views/actionDetail';

afterEach(cleanup);

const notice: Action = {
  id: 'a_n1', case_id: 'c_1', type: 'SEND_RETAILER_NOTICE', status: 'PENDING_APPROVAL', requires_approval: true,
  target: { batch_id: 'FG-2302', shipment_id: 'L-590', to: 'Retailer DC 9' },
  result: { draft_id: 'M-1', to: 'Retailer DC 9', subject: 'Product withdrawal: Granola Fruit Bar batch FG-2302 (shipment L-590)',
            body: 'Dear Retailer DC 9,\n\nPlease withdraw this batch from sale.' },
};
const query: Action = {
  id: 'a_q1', case_id: 'c_1', type: 'SEND_SUPPLIER_QUERY', status: 'PENDING_APPROVAL', requires_approval: true,
  target: { notice_id: 'n_1', to: 'supplier-portal:s_valley' },
  result: { draft_id: 'M-2', to: 'supplier-portal:s_valley', subject: 'Clarification needed: Upcoming change', body: '- the effective lot is missing' },
};
const ticket: Action = {
  id: 'a_t1', case_id: 'c_1', type: 'CREATE_RELABEL_TICKET', status: 'VERIFIED', requires_approval: false,
  target: { sku: 'HGB-200' }, result: { ticket_id: 'T-ABC', summary: 'Relabel HGB-200 (Honey Granola Bites). FG-1041: label does not declare soy.' },
};

describe('action descriptions', () => {
  it('names tickets, messages and hold locations in words', () => {
    expect(describeAction(ticket)).toBe('Relabel ticket for HGB-200');
    expect(describeAction(notice)).toBe('Withdrawal notice to Retailer DC 9 for FG-2302 (shipment L-590)');
    expect(describeAction(query)).toBe('Clarification request to supplier-portal:s_valley');
    const hold = { ...ticket, type: 'PLACE_HOLD', target: { batch_id: 'FG-1042', location: 'PLANT-1' } } as Action;
    expect(describeAction(hold)).toBe('Hold FG-1042 at PLANT-1');  // two holds on one batch are now distinguishable
  });
});

describe('ticket and message details', () => {
  it('shows the relabel ticket summary', async () => {
    render(<ActionDetail action={ticket} />);
    await userEvent.click(screen.getByText('Ticket T-ABC'));
    expect(screen.getByText(/FG-1041: label does not declare soy/)).toBeVisible();
  });

  it('shows a pending message as an unsent draft with recipient, subject and body', () => {
    render(<ActionDetail action={notice} open />);
    const message = screen.getByLabelText('Message M-1');
    expect(within(message).getByText('Draft - not sent')).toBeInTheDocument();
    expect(within(message).getByText('Retailer DC 9')).toBeInTheDocument();
    expect(within(message).getByText(/Product withdrawal: Granola Fruit Bar/)).toBeInTheDocument();
    expect(within(message).getByText(/Please withdraw this batch from sale/)).toBeInTheDocument();
  });

  it('distinguishes sent and rejected messages', () => {
    const { unmount } = render(<ActionDetail action={{ ...notice, status: 'VERIFIED', result: { ...notice.result, sent_at: '2026-10-23T12:00:00Z' } }} open />);
    expect(screen.getAllByText(/^Sent /).length).toBeGreaterThan(0);
    unmount();
    render(<ActionDetail action={{ ...notice, status: 'REJECTED' }} open />);
    expect(screen.getAllByText(/Rejected - not sent/).length).toBeGreaterThan(0);
  });

  it('renders nothing extra for other action types', () => {
    const { container } = render(<ActionDetail action={{ ...ticket, type: 'PLACE_HOLD', result: { hold_id: 'H-1' } } as Action} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('approving a message', () => {
  it('shows the exact text that will be sent before confirming', async () => {
    render(<ApprovalDecision action={query} description={describeAction(query)} token="mock:daniel.qam" onDecision={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    const dialog = screen.getByRole('dialog', { name: 'Confirm approve a_q1' });
    expect(dialog).toHaveTextContent('Approving sends this message outside the company exactly as written');
    expect(dialog).toHaveTextContent('supplier-portal:s_valley');
    expect(dialog).toHaveTextContent('Clarification needed: Upcoming change');
    expect(dialog).toHaveTextContent('the effective lot is missing');
  });

  it('shows the message on rejection too, without the send warning', async () => {
    render(<ApprovalDecision action={notice} description={describeAction(notice)} token="mock:daniel.qam" onDecision={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: 'Reject' }));
    const dialog = screen.getByRole('dialog', { name: 'Confirm reject a_n1' });
    expect(dialog).toHaveTextContent('Please withdraw this batch from sale');
    expect(dialog).not.toHaveTextContent('Approving sends this message');
  });

  it('does not add a message preview for non-message actions', async () => {
    const removal = { ...notice, id: 'a_r1', type: 'REMOVE_FROM_SHIPMENT', target: { batch_id: 'FG-1043', shipment_id: 'L-552' }, result: null } as Action;
    render(<ApprovalDecision action={removal} description={describeAction(removal)} token="mock:daniel.qam" onDecision={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(screen.getByRole('dialog')).not.toHaveTextContent('Approving sends this message');
  });
});
