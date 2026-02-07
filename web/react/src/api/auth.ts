import client from "./client";

export async function login(email: string, password: string) {
  const res = await client.post("/auth/login", { email, password });
  // if token in body:
  const token = res.data.access_token;
  localStorage.setItem("merid-token", token);
  client.defaults.headers.common["Authorization"] = `Bearer ${token}`;
}

export function initAuth() {
  const token = localStorage.getItem("merid-token");
  if (token) {
    client.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  }
}

// Call this on app startup
initAuth();
