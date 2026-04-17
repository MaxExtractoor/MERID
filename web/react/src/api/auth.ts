import client from "./client";
import { AUTH_TOKEN_KEY } from "../config/constants";

export async function login(email: string, password: string) {
  const res = await client.post("/auth/login", { email, password });
  const token = res.data.access_token;
  localStorage.setItem(AUTH_TOKEN_KEY, token);
  client.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  client.defaults.headers.common["X-Session-ID"] = token;
}

export function initAuth() {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (token) {
    client.defaults.headers.common["Authorization"] = `Bearer ${token}`;
    client.defaults.headers.common["X-Session-ID"] = token;
  }
}

// Call this on app startup
initAuth();

export function authHeaders(): Record<string, string> {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (!token) return {};
  return {
    Authorization: `Bearer ${token}`,
    "X-Session-ID": token,
  };
}
