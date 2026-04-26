/**
 * Tests for auth.ts - authentication utilities
 */

import { authHeaders, login, initAuth } from '../auth';
import { AUTH_TOKEN_KEY } from '../../config/constants';

// Mock localStorage
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
};
Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
});

// Mock client
jest.mock('../client', () => ({
  post: jest.fn(),
  defaults: {
    headers: {
      common: {},
    },
  },
}));

import client from '../client';

describe('authHeaders', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should return empty object when no token exists', () => {
    localStorageMock.getItem.mockReturnValue(null);
    
    const result = authHeaders();
    
    expect(result).toEqual({});
    expect(localStorageMock.getItem).toHaveBeenCalledWith(AUTH_TOKEN_KEY);
  });

  it('should return headers with Bearer token when token exists', () => {
    const mockToken = 'test-token-123';
    localStorageMock.getItem.mockReturnValue(mockToken);
    
    const result = authHeaders();
    
    expect(result).toEqual({
      Authorization: `Bearer ${mockToken}`,
      'X-Session-ID': mockToken,
    });
  });
});

describe('login', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should store token and set client headers on successful login', async () => {
    const mockToken = 'new-token-456';
    const mockResponse = { data: { access_token: mockToken } };
    (client.post as jest.Mock).mockResolvedValue(mockResponse);
    
    await login('test@example.com', 'password123');
    
    expect(client.post).toHaveBeenCalledWith('/auth/login', {
      email: 'test@example.com',
      password: 'password123',
    });
    expect(localStorageMock.setItem).toHaveBeenCalledWith(AUTH_TOKEN_KEY, mockToken);
    expect(client.defaults.headers.common['Authorization']).toBe(`Bearer ${mockToken}`);
    expect(client.defaults.headers.common['X-Session-ID']).toBe(mockToken);
  });
});

describe('initAuth', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Reset client headers
    client.defaults.headers.common = {};
  });

  it('should set client headers when token exists in localStorage', () => {
    const mockToken = 'existing-token-789';
    localStorageMock.getItem.mockReturnValue(mockToken);
    
    initAuth();
    
    expect(localStorageMock.getItem).toHaveBeenCalledWith(AUTH_TOKEN_KEY);
    expect(client.defaults.headers.common['Authorization']).toBe(`Bearer ${mockToken}`);
    expect(client.defaults.headers.common['X-Session-ID']).toBe(mockToken);
  });

  it('should not set headers when no token exists', () => {
    localStorageMock.getItem.mockReturnValue(null);
    
    initAuth();
    
    expect(client.defaults.headers.common['Authorization']).toBeUndefined();
    expect(client.defaults.headers.common['X-Session-ID']).toBeUndefined();
  });
});
