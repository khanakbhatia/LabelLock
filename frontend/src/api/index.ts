import { client } from './client';
import { mocks } from './mocks';

export const api = import.meta.env.VITE_USE_MOCKS === 'true' ? mocks : client;
export * from './types';
