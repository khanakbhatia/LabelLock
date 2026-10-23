import type { ReactNode } from 'react';
import type { UncertaintyFlag } from '../api';
import styles from './Workspace.module.css';
export const formatTime = (value: string) => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
export const flagLabel = (value: UncertaintyFlag) => value === 'SUPPLIER_UNVERIFIED' ? 'Unverified sender' : value.replaceAll('_', ' ');
export function Chip({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'warning' | 'danger' | 'good' }) { return <span className={`${styles.chip} ${styles[tone]}`}>{children}</span>; }
